package app

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/hibiken/asynq"
	"github.com/minio/minio-go/v7"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

func RunWorker() {
	a := connect()
	defer a.Queue.Close()
	server := asynq.NewServer(redisOptions(), asynq.Config{Concurrency: 1, ShutdownTimeout: 90 * time.Second})
	mux := asynq.NewServeMux()
	mux.HandleFunc("job:run", a.processJob)
	if err := server.Run(mux); err != nil {
		log.Fatal(err)
	}
}

func (a *App) processJob(ctx context.Context, task *asynq.Task) (resultErr error) {
	var job Job
	if err := a.DB.WithContext(ctx).First(&job, "id = ?", string(task.Payload())).Error; err != nil {
		return err
	}
	if job.Status == "completed" {
		return nil
	}
	if err := a.DB.Model(&job).Updates(map[string]any{"status": "running", "error": "", "progress": "{}", "result": "null"}).Error; err != nil {
		return err
	}
	defer func() {
		if resultErr != nil {
			status := "retrying"
			retry, _ := asynq.GetRetryCount(ctx)
			max, _ := asynq.GetMaxRetry(ctx)
			if retry >= max || errors.Is(resultErr, asynq.SkipRetry) {
				status = "failed"
			}
			message := resultErr.Error()
			a.DB.Model(&job).Updates(map[string]any{"status": status, "error": message})
		}
	}()
	var result []byte
	var err error
	if job.Kind == "optimization" {
		result, err = streamOptimization(ctx, []byte(job.Input), func(progress, preview json.RawMessage) error {
			updates := map[string]any{"progress": string(progress)}
			if len(preview) > 0 && string(preview) != "null" {
				updates["result"] = string(preview)
			}
			return a.DB.WithContext(ctx).Model(&job).Updates(updates).Error
		})
	} else if strings.HasPrefix(job.Kind, "import:") {
		object, e := a.Objects.GetObject(ctx, a.Bucket, job.ObjectKey, minio.GetObjectOptions{})
		if e != nil {
			return e
		}
		defer object.Close()
		body, e := io.ReadAll(io.LimitReader(object, 10*1024*1024+1))
		if e != nil {
			return e
		}
		if len(body) > 10*1024*1024 {
			return fmt.Errorf("file too large: %w", asynq.SkipRetry)
		}
		kind := strings.TrimPrefix(job.Kind, "import:")
		result, err = callOptimizer(ctx, "/parse/"+kind+"?filename="+url.QueryEscape(job.ObjectKey), body, "application/octet-stream")
		if err == nil {
			err = a.applyImport(ctx, job, kind, result)
		}
		if err == nil {
			var rows []any
			if e := json.Unmarshal(result, &rows); e != nil {
				return e
			}
			result = []byte(encode(map[string]any{"imported": len(rows), "kind": kind}))
		}
	} else {
		return fmt.Errorf("unknown job type: %w", asynq.SkipRetry)
	}
	if err != nil {
		return err
	}
	return a.DB.WithContext(ctx).Model(&job).Updates(map[string]any{"status": "completed", "result": string(result), "error": ""}).Error
}

func streamOptimization(ctx context.Context, input []byte, onProgress func(json.RawMessage, json.RawMessage) error) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, "POST", env("OPTIMIZER_URL", "http://optimizer:8000")+"/optimize/stream", bytes.NewReader(input))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Service-Token", mustEnv("SERVICE_TOKEN"))
	response, err := (&http.Client{Timeout: 100 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(response.Body, 1000))
		if response.StatusCode < 500 {
			return nil, fmt.Errorf("optimizer: %s: %w", body, asynq.SkipRetry)
		}
		return nil, fmt.Errorf("optimizer unavailable (%d)", response.StatusCode)
	}
	scanner := bufio.NewScanner(response.Body)
	scanner.Buffer(make([]byte, 64*1024), 20*1024*1024)
	for scanner.Scan() {
		var event struct {
			Type      string          `json:"type"`
			Progress  json.RawMessage `json:"progress"`
			Preview   json.RawMessage `json:"preview"`
			Result    json.RawMessage `json:"result"`
			Message   string          `json:"message"`
			Retryable bool            `json:"retryable"`
		}
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			return nil, fmt.Errorf("invalid optimizer event: %w", err)
		}
		switch event.Type {
		case "progress", "result":
			if len(event.Progress) == 0 || string(event.Progress) == "null" {
				return nil, errors.New("missing optimizer progress")
			}
			if err := onProgress(event.Progress, event.Preview); err != nil {
				return nil, err
			}
			if event.Type == "result" {
				if len(event.Result) == 0 || string(event.Result) == "null" {
					return nil, errors.New("missing optimizer result")
				}
				return event.Result, nil
			}
		case "error":
			if !event.Retryable {
				return nil, fmt.Errorf("optimizer: %s: %w", event.Message, asynq.SkipRetry)
			}
			return nil, fmt.Errorf("optimizer: %s", event.Message)
		default:
			return nil, fmt.Errorf("unknown optimizer event: %s", event.Type)
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return nil, errors.New("optimizer stream ended before a final result")
}

func callOptimizer(ctx context.Context, path string, body []byte, contentType string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, "POST", env("OPTIMIZER_URL", "http://optimizer:8000")+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	req.Header.Set("X-Service-Token", mustEnv("SERVICE_TOKEN"))
	response, err := (&http.Client{Timeout: 100 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 20*1024*1024))
	if err != nil {
		return nil, err
	}
	if response.StatusCode >= 400 {
		message := string(data)
		if len(message) > 1000 {
			message = message[:1000]
		}
		if response.StatusCode < 500 {
			return nil, fmt.Errorf("optimizer: %s: %w", message, asynq.SkipRetry)
		}
		return nil, fmt.Errorf("optimizer unavailable (%d)", response.StatusCode)
	}
	if !json.Valid(data) {
		return nil, errors.New("optimizer returned invalid JSON")
	}
	return data, nil
}

func (a *App) applyImport(ctx context.Context, job Job, kind string, data []byte) error {
	return a.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		conflict := clause.OnConflict{Columns: []clause.Column{{Name: "user_id"}, {Name: "name"}}, DoUpdates: clause.AssignmentColumns([]string{})}
		if kind == "wells" {
			var rows []Well
			if err := json.Unmarshal(data, &rows); err != nil {
				return fmt.Errorf("invalid rows: %w", asynq.SkipRetry)
			}
			conflict.DoUpdates = clause.AssignmentColumns([]string{"category", "duration_days", "gain_bopd", "lat", "lon"})
			for _, row := range rows {
				row.ID = 0
				row.UserID = job.UserID
				if err := row.Validate(); err != nil {
					return fmt.Errorf("%v: %w", err, asynq.SkipRetry)
				}
				if err := tx.Clauses(conflict).Create(&row).Error; err != nil {
					return err
				}
			}
		} else {
			var rows []Platform
			if err := json.Unmarshal(data, &rows); err != nil {
				return fmt.Errorf("invalid rows: %w", asynq.SkipRetry)
			}
			conflict.DoUpdates = clause.AssignmentColumns([]string{"type", "categories", "mob_demob_days", "daily_cost_kusd", "contract_end_date"})
			for _, row := range rows {
				row.ID = 0
				row.UserID = job.UserID
				if err := row.Validate(); err != nil {
					return fmt.Errorf("%v: %w", err, asynq.SkipRetry)
				}
				if err := tx.Clauses(conflict).Create(&row).Error; err != nil {
					return err
				}
			}
		}
		return nil
	})
}
