package app

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log"
	"os"
	"time"

	"github.com/hibiken/asynq"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/redis/go-redis/v9"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

type App struct {
	Cache   *redis.Client
	DB      *gorm.DB
	Queue   *asynq.Client
	Objects *minio.Client
	Bucket  string
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
func mustEnv(key string) string {
	v := os.Getenv(key)
	if v == "" {
		log.Fatalf("%s is required", key)
	}
	return v
}
func redisOptions() asynq.RedisClientOpt {
	return asynq.RedisClientOpt{Addr: env("REDIS_ADDR", "redis:6379")}
}

func connect() *App {
	_ = mustEnv("SERVICE_TOKEN")
	db, err := gorm.Open(postgres.Open(mustEnv("DATABASE_URL")), &gorm.Config{TranslateError: true})
	if err != nil {
		log.Fatal(err)
	}
	sql, err := db.DB()
	if err != nil {
		log.Fatal(err)
	}
	sql.SetMaxOpenConns(10)
	sql.SetMaxIdleConns(5)
	sql.SetConnMaxLifetime(time.Hour)
	objects, err := minio.New(env("S3_ENDPOINT", "minio:9000"), &minio.Options{Creds: credentials.NewStaticV4(mustEnv("S3_ACCESS_KEY"), mustEnv("S3_SECRET_KEY"), ""), Secure: env("S3_SECURE", "false") == "true"})
	if err != nil {
		log.Fatal(err)
	}
	return &App{Cache: redis.NewClient(&redis.Options{Addr: redisOptions().Addr}), DB: db, Queue: asynq.NewClient(redisOptions()), Objects: objects, Bucket: env("S3_BUCKET", "imports")}
}

func (a *App) initialize() {
	if err := a.DB.AutoMigrate(&Well{}, &Platform{}, &Job{}); err != nil {
		log.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	exists, err := a.Objects.BucketExists(ctx, a.Bucket)
	if err != nil {
		log.Fatal(err)
	}
	if !exists {
		if err := a.Objects.MakeBucket(ctx, a.Bucket, minio.MakeBucketOptions{}); err != nil {
			log.Fatal(err)
		}
	}
}

func newID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

func (a *App) enqueue(job *Job) error {
	if err := a.DB.Create(job).Error; err != nil {
		return err
	}
	_, err := a.Queue.Enqueue(asynq.NewTask("job:run", []byte(job.ID)), asynq.TaskID(job.ID), asynq.MaxRetry(2), asynq.Timeout(3*time.Minute))
	if err != nil {
		a.DB.Model(job).Updates(map[string]any{"status": "failed", "error": "Could not enqueue job; submit again."})
	}
	return err
}
