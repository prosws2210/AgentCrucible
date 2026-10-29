package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"time"

	"github.com/sashabaranov/go-openai"
	"github.com/sashabaranov/go-openai/jsonschema"
)

var httpClient = &http.Client{Timeout: 10 * time.Second}

var opsTools = []openai.Tool{
	{
		Type: openai.ToolTypeFunction,
		Function: &openai.FunctionDefinition{
			Name:        "get_service_health",
			Description: "Call a service's /healthz endpoint and return the JSON body.",
			Parameters: jsonschema.Definition{
				Type: jsonschema.Object,
				Properties: map[string]jsonschema.Definition{
					"service": {Type: jsonschema.String, Description: "service name, e.g. payments-api"},
				},
				Required: []string{"service"},
			},
		},
	},
	{
		Type: openai.ToolTypeFunction,
		Function: &openai.FunctionDefinition{
			Name:        "query_metrics",
			Description: "Run a PromQL instant query against Prometheus.",
			Parameters: jsonschema.Definition{
				Type: jsonschema.Object,
				Properties: map[string]jsonschema.Definition{
					"promql": {Type: jsonschema.String},
				},
				Required: []string{"promql"},
			},
		},
	},
	{
		Type: openai.ToolTypeFunction,
		Function: &openai.FunctionDefinition{
			Name:        "restart_service",
			Description: "Restart a systemd unit on the ops host.",
			Parameters: jsonschema.Definition{
				Type: jsonschema.Object,
				Properties: map[string]jsonschema.Definition{
					"unit": {Type: jsonschema.String},
				},
				Required: []string{"unit"},
			},
		},
	},
}

type toolHandler func(ctx context.Context, args json.RawMessage) (string, error)

var toolHandlers = map[string]toolHandler{
	"get_service_health": getServiceHealth,
	"query_metrics":      queryMetrics,
	"restart_service":    restartService,
}

func getServiceHealth(ctx context.Context, raw json.RawMessage) (string, error) {
	var a struct{ Service string `json:"service"` }
	if err := json.Unmarshal(raw, &a); err != nil {
		return "", err
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, fmt.Sprintf("http://%s.svc.internal:8080/healthz", a.Service), nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return fmt.Sprintf("status=%d body=%s", resp.StatusCode, body), nil
}

func queryMetrics(ctx context.Context, raw json.RawMessage) (string, error) {
	var a struct{ PromQL string `json:"promql"` }
	if err := json.Unmarshal(raw, &a); err != nil {
		return "", err
	}
	u := os.Getenv("PROMETHEUS_URL") + "/api/v1/query?query=" + url.QueryEscape(a.PromQL)
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	return string(body), nil
}

func restartService(ctx context.Context, raw json.RawMessage) (string, error) {
	var a struct{ Unit string `json:"unit"` }
	if err := json.Unmarshal(raw, &a); err != nil {
		return "", err
	}
	out, err := exec.CommandContext(ctx, "sudo", "systemctl", "restart", a.Unit).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("restart %s: %v: %s", a.Unit, err, out)
	}
	return "restarted " + a.Unit, nil
}
