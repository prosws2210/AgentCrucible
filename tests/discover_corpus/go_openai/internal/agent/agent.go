package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/sashabaranov/go-openai"
)

const systemPrompt = `You are OpsBot, the on-call assistant. Diagnose with health checks and metrics first.
Restart a service only if it is unhealthy AND the user asked you to remediate.`

// RunOpsAgent runs a tool-calling loop until the model produces a final answer.
func RunOpsAgent(ctx context.Context, userMsg string) (string, error) {
	client := openai.NewClient(os.Getenv("OPENAI_API_KEY"))
	messages := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: systemPrompt},
		{Role: openai.ChatMessageRoleUser, Content: userMsg},
	}

	for step := 0; step < 8; step++ {
		resp, err := client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
			Model:    openai.GPT4o,
			Messages: messages,
			Tools:    opsTools,
		})
		if err != nil {
			return "", fmt.Errorf("chat completion: %w", err)
		}
		msg := resp.Choices[0].Message
		messages = append(messages, msg)
		if len(msg.ToolCalls) == 0 {
			return msg.Content, nil
		}
		for _, call := range msg.ToolCalls {
			handler, ok := toolHandlers[call.Function.Name]
			var result string
			if !ok {
				result = "unknown tool " + call.Function.Name
			} else if out, err := handler(ctx, json.RawMessage(call.Function.Arguments)); err != nil {
				result = "error: " + err.Error()
			} else {
				result = out
			}
			messages = append(messages, openai.ChatCompletionMessage{
				Role:       openai.ChatMessageRoleTool,
				Content:    result,
				ToolCallID: call.ID,
			})
		}
	}
	return "", fmt.Errorf("agent exceeded step budget")
}
