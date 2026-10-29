package main

import (
	"context"
	"encoding/json"
	"flag"
	"log"
	"net/http"

	"github.com/acme/opsbot/internal/agent"
	"github.com/acme/opsbot/internal/mcpserver"
)

func main() {
	mcpMode := flag.Bool("mcp", false, "serve the deploy-tools MCP server on stdio instead of HTTP")
	addr := flag.String("addr", ":8088", "HTTP listen address")
	flag.Parse()

	if *mcpMode {
		if err := mcpserver.ServeStdio(); err != nil {
			log.Fatal(err)
		}
		return
	}

	http.HandleFunc("/ask", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Question string `json:"question"` }
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		answer, err := agent.RunOpsAgent(context.Background(), body.Question)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"answer": answer})
	})
	log.Fatal(http.ListenAndServe(*addr, nil))
}
