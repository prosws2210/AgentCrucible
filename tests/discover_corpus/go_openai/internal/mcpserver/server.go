package mcpserver

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func New() *server.MCPServer {
	s := server.NewMCPServer(
		"deploy-tools",
		"1.0.0",
		server.WithToolCapabilities(false),
		server.WithRecovery(),
	)

	listTool := mcp.NewTool("list_deployments",
		mcp.WithDescription("List recent deployments for a service from the deploy API"),
		mcp.WithString("service", mcp.Required(), mcp.Description("Service name")),
	)
	s.AddTool(listTool, listDeployments)

	rollbackTool := mcp.NewTool("rollback_deployment",
		mcp.WithDescription("Roll a Kubernetes deployment back to its previous revision"),
		mcp.WithString("namespace", mcp.Required()),
		mcp.WithString("deployment", mcp.Required()),
	)
	s.AddTool(rollbackTool, rollbackDeployment)

	return s
}

func listDeployments(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	svc, err := request.RequireString("service")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet,
		fmt.Sprintf("%s/v1/services/%s/deployments?limit=10", os.Getenv("DEPLOY_API_URL"), svc), nil)
	req.Header.Set("Authorization", "Bearer "+os.Getenv("DEPLOY_API_TOKEN"))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return mcp.NewToolResultText(string(body)), nil
}

func rollbackDeployment(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	ns, err := request.RequireString("namespace")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	dep, err := request.RequireString("deployment")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	out, err := exec.CommandContext(ctx, "kubectl", "-n", ns, "rollout", "undo", "deployment/"+dep).CombinedOutput()
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("%v: %s", err, out)), nil
	}
	return mcp.NewToolResultText(string(out)), nil
}

// ServeStdio runs the deploy-tools MCP server over stdio.
func ServeStdio() error {
	return server.ServeStdio(New())
}
