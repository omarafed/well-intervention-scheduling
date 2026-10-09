package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/hibiken/asynq"
)

func TestOptimizationStream(t *testing.T) {
	for _, tc := range []struct {
		name, body           string
		wantError, skipRetry bool
		wantTicks            int
	}{
		{"success", `{"type":"progress","progress":{"phase":"searching","solutions":1},"preview":{"schedule":[{"Well_ID":"W1"}]}}
{"type":"result","progress":{"phase":"completed"},"result":{"status":"OPTIMAL"}}`, false, false, 2},
		{"incomplete", `{"type":"progress","progress":{"phase":"searching"}}`, true, false, 1},
		{"invalid input", `{"type":"error","message":"No feasible schedule","retryable":false}`, true, true, 0},
		{"temporary failure", `{"type":"error","message":"Service failure","retryable":true}`, true, false, 0},
		{"malformed", `not json`, true, false, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("SERVICE_TOKEN", "test-service-token")
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/optimize/stream" || r.Header.Get("X-Service-Token") != "test-service-token" {
					t.Error("incorrect streaming request")
				}
				w.Header().Set("Content-Type", "application/x-ndjson")
				fmt.Fprintln(w, tc.body)
			}))
			defer server.Close()
			t.Setenv("OPTIMIZER_URL", server.URL)
			ticks := 0
			result, err := streamOptimization(context.Background(), []byte(`{}`), func(progress, preview json.RawMessage) error {
				ticks++
				if !json.Valid(progress) {
					t.Error("invalid persisted progress")
				}
				if ticks == 1 && tc.name == "success" && !strings.Contains(string(preview), "W1") {
					t.Error("preview was lost")
				}
				return nil
			})
			if (err != nil) != tc.wantError || errors.Is(err, asynq.SkipRetry) != tc.skipRetry || ticks != tc.wantTicks {
				t.Fatalf("result=%s err=%v ticks=%d", result, err, ticks)
			}
			if !tc.wantError && !strings.Contains(string(result), "OPTIMAL") {
				t.Fatal("missing final result")
			}
		})
	}
}
