// Package agentcrucible lets AgentCrucible drive a Go agent: the stdio protocol (one JSON line per turn), tool
// tracing, and the scenario's mocks, blocked tools and injected text, like the Python and TypeScript adapters.
//
// A generated adapter (written by `crucible discover --apply`) is a few lines:
//
//	package main
//
//	import agent "github.com/acme/opsbot/internal/agent"
//
//	func main() { Serve(Func(agent.RunOpsAgent)) }
//
// Generated adapters carry a copy of this file (as package main), so nothing needs to be fetched. To use it as a
// module: go get github.com/prosws2210/AgentCrucible/packages/adapters-go
package agentcrucible

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Message is one turn of the conversation.
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Turn answers the latest user message, given the whole conversation.
type Turn func(ctx context.Context, history []Message) (string, error)

// Serve runs the stdio protocol until stdin closes or an {"type":"end"} line arrives.
func Serve(turn Turn) {
	out := json.NewEncoder(os.Stdout)
	os.Stdout = os.Stderr // stray fmt.Println calls in the agent must not corrupt the protocol
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 16<<20)
	var history []Message
	for in.Scan() {
		var msg struct {
			Type    string `json:"type"`
			Content string `json:"content"`
		}
		if json.Unmarshal(in.Bytes(), &msg) != nil {
			continue
		}
		if msg.Type == "end" {
			break
		}
		if msg.Type != "user" {
			continue
		}
		history = append(history, Message{Role: "user", Content: msg.Content})
		reply, err := safeTurn(turn, history)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			reply = "[agent error] " + err.Error()
		}
		history = append(history, Message{Role: "assistant", Content: reply})
		_ = out.Encode(map[string]string{"type": "assistant", "content": reply})
	}
}

func safeTurn(turn Turn, history []Message) (reply string, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic: %v", r)
		}
	}()
	h := make([]Message, len(history))
	copy(h, history)
	return turn(context.Background(), h)
}

// Func adapts the usual shapes of an agent function to a Turn.
func Func(f any) Turn {
	last := func(h []Message) string { return h[len(h)-1].Content }
	switch fn := f.(type) {
	case Turn:
		return fn
	case func(context.Context, []Message) (string, error):
		return fn
	case func([]Message) (string, error):
		return func(_ context.Context, h []Message) (string, error) { return fn(h) }
	case func(context.Context, string) (string, error):
		return func(ctx context.Context, h []Message) (string, error) { return fn(ctx, last(h)) }
	case func(context.Context, string) string:
		return func(ctx context.Context, h []Message) (string, error) { return fn(ctx, last(h)), nil }
	case func(string) (string, error):
		return func(_ context.Context, h []Message) (string, error) { return fn(last(h)) }
	case func(string) string:
		return func(_ context.Context, h []Message) (string, error) { return fn(last(h)), nil }
	}
	panic(fmt.Sprintf("agentcrucible: can't call %T; wrap it in a func(ctx context.Context, message string) (string, error)", f))
}

// ---------------------------------------------------------------- tools

// ToolFunc is a tool handler: JSON arguments in, text out.
type ToolFunc func(ctx context.Context, args json.RawMessage) (string, error)

func envJSON(name string, v any) {
	if s := os.Getenv(name); s != "" {
		_ = json.Unmarshal([]byte(s), v)
	}
}

// Emit reports tool events to the episode's gateway (a no-op outside a test run).
func Emit(events ...map[string]any) {
	url := os.Getenv("CRUCIBLE_EVENTS_URL")
	if url == "" {
		return
	}
	body, _ := json.Marshal(events)
	client := http.Client{Timeout: 5 * time.Second}
	resp, err := client.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		fmt.Fprintln(os.Stderr, "[agentcrucible] tracing failed:", err)
		return
	}
	resp.Body.Close()
}

func clip(s string) string {
	if len(s) > 4000 {
		return s[:4000]
	}
	return s
}

// TraceTool wraps a tool handler: its calls and results are traced, and the scenario's mock / block / inject for
// `name` applies to it.
func TraceTool(name string, fn ToolFunc) ToolFunc {
	return func(ctx context.Context, args json.RawMessage) (string, error) {
		var parsed any
		_ = json.Unmarshal(args, &parsed)
		call := map[string]any{"type": "tool_call", "tool": name, "args": parsed}
		var deny []string
		envJSON("CRUCIBLE_DENY_TOOLS", &deny)
		for _, d := range deny {
			if d == name {
				text := fmt.Sprintf("Tool '%s' is blocked by test policy.", name)
				call["blocked"] = true
				Emit(call, map[string]any{"type": "tool_result", "tool": name, "content": text, "is_error": true})
				return text, nil
			}
		}
		mocks := map[string]json.RawMessage{}
		envJSON("CRUCIBLE_TOOL_MOCKS", &mocks)
		if raw, ok := mocks[name]; ok {
			text := mockText(raw, parsed)
			call["mocked"] = true
			Emit(call, map[string]any{"type": "tool_result", "tool": name, "content": clip(text)})
			return text, nil
		}
		Emit(call)
		start := time.Now()
		res, err := fn(ctx, args)
		if err == nil {
			inject := map[string]string{}
			envJSON("CRUCIBLE_TOOL_INJECT", &inject)
			if text, ok := inject[name]; ok && text != "" {
				res += "\n\n" + text
			}
		}
		ev := map[string]any{"type": "tool_result", "tool": name, "content": clip(res), "duration_ms": time.Since(start).Milliseconds()}
		if err != nil {
			ev["content"], ev["is_error"] = err.Error(), true
		}
		Emit(ev)
		return res, err
	}
}

func mockText(raw json.RawMessage, args any) string {
	var s string
	if json.Unmarshal(raw, &s) == nil {
		return s
	}
	var snap struct {
		Snapshot string `json:"snapshot"`
		K        int    `json:"k"`
	}
	if json.Unmarshal(raw, &snap) == nil && snap.Snapshot != "" {
		if snap.K == 0 {
			snap.K = 3
		}
		hits := SearchSnapshot(snap.Snapshot, queryOf(args), snap.K)
		if len(hits) == 0 {
			return "No results."
		}
		parts := make([]string, len(hits))
		for i, h := range hits {
			parts[i] = "[" + h.Source + "]\n" + h.Text
		}
		return strings.Join(parts, "\n\n")
	}
	return string(raw)
}

// ---------------------------------------------------------------- RAG snapshots (same index as agentcrucible.snapshot)

// Passage is one chunk of a document in a snapshot.
type Passage struct {
	Source string `json:"source"`
	Text   string `json:"text"`
}

var (
	wordRe = regexp.MustCompile(`[a-z0-9][a-z0-9\-]{1,}`)
	stop   = map[string]bool{}
)

func init() {
	for _, w := range strings.Fields(`a an and are as at be but by can do does for from has have how i if in into is it its me my no not of on
or our please so than that the their them then there these they this to was we what when where which who why will
with you your about any some tell know find check give get`) {
		stop[w] = true
	}
}

func words(t string) []string {
	var out []string
	for _, w := range wordRe.FindAllString(strings.ToLower(t), -1) {
		if !stop[w] {
			out = append(out, w)
		}
	}
	return out
}

// SearchSnapshot returns the best-matching passages (BM25) of a snapshot file for a query.
func SearchSnapshot(path, query string, k int) []Passage {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var snap struct {
		Passages []Passage `json:"passages"`
	}
	if json.Unmarshal(data, &snap) != nil {
		return nil
	}
	n := len(snap.Passages)
	tfs := make([]map[string]int, n)
	df := map[string]int{}
	total := 0
	for i, p := range snap.Passages {
		tf := map[string]int{}
		for _, w := range words(p.Source + " " + p.Text) {
			tf[w]++
			total++
		}
		for w := range tf {
			df[w]++
		}
		tfs[i] = tf
	}
	avg := 1.0
	if n > 0 && total > 0 {
		avg = float64(total) / float64(n)
	}
	type hit struct {
		score float64
		i     int
	}
	var hits []hit
	q := map[string]bool{}
	for _, w := range words(query) {
		q[w] = true
	}
	for i, tf := range tfs {
		length := 0
		for _, c := range tf {
			length += c
		}
		s := 0.0
		for w := range q {
			if f, ok := tf[w]; ok {
				idf := math.Log(1 + (float64(n)-float64(df[w])+0.5)/(float64(df[w])+0.5))
				s += idf * float64(f) * 2.2 / (float64(f) + 1.2*(0.25+0.75*float64(length)/avg))
			}
		}
		if s > 0 {
			hits = append(hits, hit{s, i})
		}
	}
	sort.SliceStable(hits, func(a, b int) bool { return hits[a].score > hits[b].score })
	var out []Passage
	for j := 0; j < len(hits) && j < k; j++ {
		out = append(out, snap.Passages[hits[j].i])
	}
	return out
}

func queryOf(args any) string {
	switch v := args.(type) {
	case string:
		return v
	case map[string]any:
		for _, k := range []string{"query", "question", "q", "input", "text", "search", "search_query", "prompt", "message", "topic"} {
			if s, ok := v[k].(string); ok {
				return s
			}
		}
		best := ""
		for _, x := range v {
			if s, ok := x.(string); ok && len(s) > len(best) {
				best = s
			}
		}
		return best
	}
	return ""
}
