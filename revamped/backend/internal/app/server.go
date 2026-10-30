package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"github.com/minio/minio-go/v7"
	"gorm.io/gorm"
)

func RunServer() {
	a := connect()
	a.initialize()
	defer a.Queue.Close()
	e := echo.New()
	e.HideBanner = true
	e.Use(middleware.Recover(), middleware.RequestID(), middleware.Logger(), middleware.BodyLimit("11M"))
	e.Use(middleware.CORSWithConfig(middleware.CORSConfig{AllowOrigins: strings.Split(env("CORS_ORIGINS", "http://localhost:3000"), ","), AllowHeaders: []string{"Content-Type"}}))
	e.Use(middleware.Secure())
	e.GET("/health", func(c echo.Context) error {
		ctx, cancel := context.WithTimeout(c.Request().Context(), time.Second)
		defer cancel()
		db, err := a.DB.DB()
		if err != nil || db.PingContext(ctx) != nil {
			return echo.NewHTTPError(503, "Database unavailable")
		}
		return c.JSON(200, map[string]string{"status": "ok"})
	})
	api := e.Group("/api")
	api.GET("/wells", a.listWells)
	api.POST("/wells", a.saveWell)
	api.PUT("/wells/:id", a.saveWell)
	api.DELETE("/wells/:id", a.deleteWell)
	api.GET("/platforms", a.listPlatforms)
	api.POST("/platforms", a.savePlatform)
	api.PUT("/platforms/:id", a.savePlatform)
	api.DELETE("/platforms/:id", a.deletePlatform)
	api.POST("/imports/:kind", a.importFile)
	api.POST("/optimizations", a.optimize)
	api.GET("/jobs", a.listJobs)
	api.GET("/jobs/:id", a.getJob)
	api.POST("/demo", a.seedDemo)
	server := &http.Server{Addr: ":8080", ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	e.Server = server
	if err := e.StartServer(server); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

// Keep the original first workspace's data without rewriting or deleting stored records.
const sharedWorkspaceID uint = 1

func ownedID(c echo.Context) (uint, error) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil || id == 0 {
		return 0, echo.NewHTTPError(400, "Invalid ID")
	}
	return uint(id), nil
}
func (a *App) listWells(c echo.Context) error {
	rows := []Well{}
	if err := a.DB.Where("user_id = ?", sharedWorkspaceID).Order("name").Find(&rows).Error; err != nil {
		return err
	}
	return c.JSON(200, rows)
}
func (a *App) listPlatforms(c echo.Context) error {
	rows := []Platform{}
	if err := a.DB.Where("user_id = ?", sharedWorkspaceID).Order("name").Find(&rows).Error; err != nil {
		return err
	}
	return c.JSON(200, rows)
}
func saveError(err error) error {
	if errors.Is(err, gorm.ErrDuplicatedKey) {
		return echo.NewHTTPError(409, "Name already exists")
	}
	return err
}
func (a *App) saveWell(c echo.Context) error {
	var row Well
	if c.Bind(&row) != nil {
		return echo.NewHTTPError(400, "Invalid well")
	}
	row.ID = 0
	row.UserID = sharedWorkspaceID
	if err := row.Validate(); err != nil {
		return echo.NewHTTPError(422, err.Error())
	}
	if c.Param("id") != "" {
		id, err := ownedID(c)
		if err != nil {
			return err
		}
		var existing Well
		if a.DB.Where("id = ? AND user_id = ?", id, sharedWorkspaceID).First(&existing).Error != nil {
			return echo.NewHTTPError(404)
		}
		row.ID = id
	}
	if err := a.DB.Save(&row).Error; err != nil {
		return saveError(err)
	}
	return c.JSON(200, row)
}
func (a *App) savePlatform(c echo.Context) error {
	var row Platform
	if c.Bind(&row) != nil {
		return echo.NewHTTPError(400, "Invalid rig")
	}
	row.ID = 0
	row.UserID = sharedWorkspaceID
	if err := row.Validate(); err != nil {
		return echo.NewHTTPError(422, err.Error())
	}
	if c.Param("id") != "" {
		id, err := ownedID(c)
		if err != nil {
			return err
		}
		var existing Platform
		if a.DB.Where("id = ? AND user_id = ?", id, sharedWorkspaceID).First(&existing).Error != nil {
			return echo.NewHTTPError(404)
		}
		row.ID = id
	}
	if err := a.DB.Save(&row).Error; err != nil {
		return saveError(err)
	}
	return c.JSON(200, row)
}
func (a *App) deleteWell(c echo.Context) error {
	id, err := ownedID(c)
	if err != nil {
		return err
	}
	r := a.DB.Where("id = ? AND user_id = ?", id, sharedWorkspaceID).Delete(&Well{})
	if r.Error != nil {
		return r.Error
	}
	if r.RowsAffected == 0 {
		return echo.NewHTTPError(404)
	}
	return c.NoContent(204)
}
func (a *App) deletePlatform(c echo.Context) error {
	id, err := ownedID(c)
	if err != nil {
		return err
	}
	r := a.DB.Where("id = ? AND user_id = ?", id, sharedWorkspaceID).Delete(&Platform{})
	if r.Error != nil {
		return r.Error
	}
	if r.RowsAffected == 0 {
		return echo.NewHTTPError(404)
	}
	return c.NoContent(204)
}

func (a *App) importFile(c echo.Context) error {
	kind := c.Param("kind")
	if kind != "wells" && kind != "platforms" {
		return echo.NewHTTPError(400, "Choose wells or rigs")
	}
	file, err := c.FormFile("file")
	if err != nil {
		return echo.NewHTTPError(400, "Attach a file")
	}
	ext := strings.ToLower(filepath.Ext(file.Filename))
	if (ext != ".csv" && ext != ".xlsx") || file.Size > 10*1024*1024 {
		return echo.NewHTTPError(400, "Upload CSV or XLSX up to 10 MiB")
	}
	src, err := file.Open()
	if err != nil {
		return err
	}
	defer src.Close()
	id := newID()
	key := fmt.Sprintf("%d/%s%s", sharedWorkspaceID, id, ext)
	_, err = a.Objects.PutObject(c.Request().Context(), a.Bucket, key, io.LimitReader(src, 10*1024*1024+1), file.Size, minio.PutObjectOptions{ContentType: "application/octet-stream"})
	if err != nil {
		return err
	}
	job := Job{ID: id, UserID: sharedWorkspaceID, Kind: "import:" + kind, Name: filepath.Base(file.Filename), Status: "queued", ObjectKey: key, Input: "{}", Result: "null"}
	if err := a.enqueue(&job); err != nil {
		return echo.NewHTTPError(503, "Could not queue import")
	}
	return c.JSON(202, job)
}

func (a *App) optimize(c echo.Context) error {
	var in struct {
		Name         string     `json:"name"`
		StartDate    string     `json:"start_date"`
		DroppedWells []string   `json:"dropped_wells"`
		LockedWells  []WellLock `json:"locked_wells"`
	}
	if c.Bind(&in) != nil {
		return echo.NewHTTPError(400, "Invalid request")
	}
	if _, err := time.Parse("2006-01-02", in.StartDate); err != nil {
		return echo.NewHTTPError(422, "Choose a start date")
	}
	in.Name = strings.TrimSpace(in.Name)
	if in.Name == "" || len(in.Name) > 100 {
		return echo.NewHTTPError(422, "Scenario name must be 1–100 characters")
	}
	wells := []Well{}
	platforms := []Platform{}
	if err := a.DB.Where("user_id = ?", sharedWorkspaceID).Order("id").Find(&wells).Error; err != nil {
		return err
	}
	if err := a.DB.Where("user_id = ?", sharedWorkspaceID).Order("id").Find(&platforms).Error; err != nil {
		return err
	}
	if len(wells) == 0 || len(wells) > 200 || len(platforms) == 0 || len(platforms) > 20 {
		return echo.NewHTTPError(422, "Optimization requires 1–200 wells and 1–20 rigs")
	}
	ws := []map[string]any{}
	ps := map[string]any{}
	names := map[string]bool{}
	for _, w := range wells {
		names[w.Name] = true
		ws = append(ws, map[string]any{"Well_ID": w.Name, "Job Category": w.Category, "Duration_Days": w.DurationDays, "BOPD": w.GainBOPD, "Lat": w.Lat, "Lon": w.Lon})
	}
	for _, name := range in.DroppedWells {
		if !names[name] {
			return echo.NewHTTPError(422, "Unknown excluded well")
		}
	}
	for _, p := range platforms {
		ps[p.Name] = map[string]any{"Supported_Job_Categories": p.Categories, "Mob_Demob_Days": p.MobDemobDays, "Daily_Cost_kUSD": p.DailyCostKUSD, "Contract_End_Date": p.ContractEndDate}
	}
	if err := validateLocks(in.LockedWells, in.DroppedWells, in.StartDate, wells, platforms); err != nil {
		return echo.NewHTTPError(422, err.Error())
	}
	job := Job{ID: newID(), UserID: sharedWorkspaceID, Kind: "optimization", Name: in.Name, Status: "queued", Input: encode(map[string]any{"start_date": in.StartDate, "dropped_wells": in.DroppedWells, "locked_wells": in.LockedWells, "wells": ws, "platforms": ps}), Result: "null"}
	if err := a.enqueue(&job); err != nil {
		return echo.NewHTTPError(503, "Could not queue optimization")
	}
	return c.JSON(202, job)
}
func (a *App) listJobs(c echo.Context) error {
	// Preserve the original array response for existing API consumers.
	if c.QueryParam("page") == "" {
		rows := []Job{}
		if err := a.DB.Omit("input", "result", "progress", "object_key").Where("user_id = ?", sharedWorkspaceID).Order("created_at desc, id desc").Limit(100).Find(&rows).Error; err != nil {
			return err
		}
		return c.JSON(200, rows)
	}
	options, err := parseHistoryOptions(c)
	if err != nil {
		return err
	}
	query := a.DB.Model(&Job{}).Where("user_id = ?", sharedWorkspaceID)
	if options.Search != "" {
		// Treat wildcard characters as literal text in name searches.
		pattern := strings.NewReplacer("!", "!!", "%", "!%", "_", "!_").Replace(strings.ToLower(options.Search))
		query = query.Where("LOWER(name) LIKE ? ESCAPE '!'", "%"+pattern+"%")
	}
	if options.Kind != "" {
		query = query.Where("kind = ?", options.Kind)
	}
	if options.Status != "" {
		query = query.Where("status = ?", options.Status)
	}
	var total, active int64
	if err := query.Count(&total).Error; err != nil {
		return err
	}
	if err := a.DB.Model(&Job{}).Where("user_id = ? AND status IN ?", sharedWorkspaceID, []string{"queued", "running", "retrying"}).Count(&active).Error; err != nil {
		return err
	}
	pages := max(1, (int(total)+options.Size-1)/options.Size)
	page := min(options.Page, pages)
	rows := []Job{}
	if err := query.Omit("input", "result", "progress", "object_key").Order("created_at desc, id desc").Offset((page - 1) * options.Size).Limit(options.Size).Find(&rows).Error; err != nil {
		return err
	}
	return c.JSON(200, map[string]any{"items": rows, "total": total, "page": page, "page_size": options.Size, "pages": pages, "active": active})
}

type historyOptions struct {
	Page, Size           int
	Search, Kind, Status string
}

func parseHistoryOptions(c echo.Context) (historyOptions, error) {
	options := historyOptions{Page: 1, Size: 10, Search: strings.TrimSpace(c.QueryParam("search")), Kind: c.QueryParam("kind"), Status: c.QueryParam("status")}
	for _, field := range []struct {
		name    string
		value   *int
		maximum int
	}{{"page", &options.Page, 100000000}, {"page_size", &options.Size, 100}} {
		if raw := c.QueryParam(field.name); raw != "" {
			value, err := strconv.Atoi(raw)
			if err != nil || value < 1 || value > field.maximum {
				return options, echo.NewHTTPError(400, "Invalid "+field.name)
			}
			*field.value = value
		}
	}
	if len(options.Search) > 100 {
		return options, echo.NewHTTPError(400, "Search must be at most 100 characters")
	}
	if options.Kind != "" && options.Kind != "optimization" && options.Kind != "import:wells" && options.Kind != "import:platforms" {
		return options, echo.NewHTTPError(400, "Invalid job type")
	}
	switch options.Status {
	case "", "queued", "running", "retrying", "completed", "failed":
	default:
		return options, echo.NewHTTPError(400, "Invalid job status")
	}
	return options, nil
}
func (a *App) getJob(c echo.Context) error {
	var job Job
	if a.DB.Omit("result").Where("id = ? AND user_id = ?", c.Param("id"), sharedWorkspaceID).First(&job).Error != nil {
		return echo.NewHTTPError(404)
	}
	job.Result = "null"
	if job.Progress == "" {
		job.Progress = "{}"
	}
	if job.Status == "completed" {
		ctx, cancel := context.WithTimeout(c.Request().Context(), time.Second)
		defer cancel()
		key := fmt.Sprintf("job-result:%d:%s", sharedWorkspaceID, job.ID)
		cached, err := a.Cache.Get(ctx, key).Result()
		if err == nil && json.Valid([]byte(cached)) {
			job.Result = cached
		} else {
			var stored Job
			if err := a.DB.Select("result").Where("id = ? AND user_id = ?", job.ID, sharedWorkspaceID).First(&stored).Error; err != nil {
				return err
			}
			job.Result = stored.Result
			a.Cache.Set(ctx, key, job.Result, 15*time.Minute)
		}
	} else if job.Kind == "optimization" {
		var stored Job
		if err := a.DB.Select("result", "progress").Where("id = ? AND user_id = ?", job.ID, sharedWorkspaceID).First(&stored).Error; err != nil {
			return err
		}
		job.Result = stored.Result
		job.Progress = stored.Progress
	}
	return c.JSON(200, map[string]any{"job": job, "input": json.RawMessage(job.Input), "result": json.RawMessage(job.Result), "progress": json.RawMessage(job.Progress)})
}

func (a *App) seedDemo(c echo.Context) error {
	err := a.DB.Transaction(func(tx *gorm.DB) error {
		var count int64
		if err := tx.Model(&Well{}).Where("user_id = ?", sharedWorkspaceID).Count(&count).Error; err != nil {
			return err
		}
		if count > 0 {
			return echo.NewHTTPError(409, "Demo requires an empty well dataset")
		}
		if err := tx.Model(&Platform{}).Where("user_id = ?", sharedWorkspaceID).Count(&count).Error; err != nil {
			return err
		}
		if count > 0 {
			return echo.NewHTTPError(409, "Demo requires an empty rig dataset")
		}
		for i, cat := range []string{"Wellhead Maintenance", "Slickline Services", "Perforation", "Well Stimulation", "CTU Services", "Well Repair & Maintenance"} {
			w := Well{UserID: sharedWorkspaceID, Name: fmt.Sprintf("WELL-%02d", i+1), Category: cat, DurationDays: 7 + i*2, GainBOPD: 400 + i*180, Lat: 4 + float64(i)*.08, Lon: 111.8 + float64(i)*.12}
			if err := tx.Create(&w).Error; err != nil {
				return err
			}
		}
		for i, cats := range [][]string{{"Wellhead Maintenance", "Slickline Services", "Perforation"}, {"Well Stimulation", "CTU Services", "Well Repair & Maintenance"}} {
			p := Platform{UserID: sharedWorkspaceID, Name: fmt.Sprintf("Rig-%d", i+1), Type: "Intervention", Categories: cats, MobDemobDays: 2, DailyCostKUSD: 12 + float64(i)*18}
			if err := tx.Create(&p).Error; err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	return c.JSON(201, map[string]string{"message": "Demo dataset loaded"})
}
