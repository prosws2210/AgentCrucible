# AgentCrucible adapters for Go

```bash
go get github.com/prosws2210/AgentCrucible/packages/adapters-go
```

```go
import agentcrucible "github.com/prosws2210/AgentCrucible/packages/adapters-go"

func main() { agentcrucible.Serve(agentcrucible.Func(agent.RunOpsAgent)) }
```

`Func` accepts `func(string) string`, `func(string) (string, error)`, `func(context.Context, string) (string, error)`
and the history-taking forms. Wrap tool handlers with `TraceTool(name, handler)` so their calls are traced and
scenarios can mock or block them (including document-snapshot mocks for RAG tests).

`crucible discover` generates this for you (`agent-tests/adapters/<agent>/main.go`, with a copy of the runtime as
package main), started with `go run ./agent-tests/adapters/<agent>`.
