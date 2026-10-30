package app

import (
	"encoding/json"
	"errors"
	"math"
	"strings"
	"time"
)

// UserID is the legacy storage column for the shared workspace; no user accounts are required.
type Well struct {
	ID           uint    `json:"id" gorm:"primaryKey"`
	UserID       uint    `json:"-" gorm:"uniqueIndex:well_owner_name"`
	Name         string  `json:"name" gorm:"uniqueIndex:well_owner_name;size:100"`
	Category     string  `json:"category"`
	DurationDays int     `json:"duration_days"`
	GainBOPD     int     `json:"gain_bopd"`
	Lat          float64 `json:"lat"`
	Lon          float64 `json:"lon"`
}

type Platform struct {
	ID              uint     `json:"id" gorm:"primaryKey"`
	UserID          uint     `json:"-" gorm:"uniqueIndex:platform_owner_name"`
	Name            string   `json:"name" gorm:"uniqueIndex:platform_owner_name;size:100"`
	Type            string   `json:"type"`
	Categories      []string `json:"categories" gorm:"serializer:json;type:jsonb"`
	MobDemobDays    int      `json:"mob_demob_days"`
	DailyCostKUSD   float64  `json:"daily_cost_kusd"`
	ContractEndDate string   `json:"contract_end_date"`
}

type Job struct {
	ID        string    `json:"id" gorm:"primaryKey;size:36"`
	UserID    uint      `json:"-" gorm:"index"`
	Kind      string    `json:"kind"`
	Name      string    `json:"name"`
	Status    string    `json:"status"`
	Error     string    `json:"error"`
	Input     string    `json:"-" gorm:"type:jsonb"`
	Result    string    `json:"-" gorm:"type:jsonb"`
	Progress  string    `json:"-" gorm:"type:jsonb;default:'{}'"`
	ObjectKey string    `json:"-"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

func (w *Well) Validate() error {
	w.Name, w.Category = strings.TrimSpace(w.Name), strings.TrimSpace(w.Category)
	if w.Name == "" || len(w.Name) > 100 || w.Category == "" || len(w.Category) > 200 || w.DurationDays < 0 || w.DurationDays > 365 || w.GainBOPD < 0 || w.GainBOPD > 10000000 || !finite(w.Lat) || !finite(w.Lon) || math.Abs(w.Lat) > 90 || math.Abs(w.Lon) > 180 {
		return errors.New("invalid well: supply a name, category, duration 0–365, gain 0–10000000, and valid coordinates")
	}
	return nil
}

func (p *Platform) Validate() error {
	p.Name = strings.TrimSpace(p.Name)
	if p.Name == "" || len(p.Name) > 100 || len(p.Categories) == 0 || len(p.Categories) > 30 || p.MobDemobDays < 0 || p.MobDemobDays > 365 || !finite(p.DailyCostKUSD) || p.DailyCostKUSD < .001 || p.DailyCostKUSD > 1000000 {
		return errors.New("invalid rig: supply a name, categories, mobilization days 0–365, and daily cost 0.001–1000000 kUSD")
	}
	for i, category := range p.Categories {
		p.Categories[i] = strings.TrimSpace(category)
		if p.Categories[i] == "" || len(p.Categories[i]) > 200 {
			return errors.New("invalid rig category")
		}
	}
	if p.ContractEndDate != "" {
		if _, err := time.Parse("2006-01-02", p.ContractEndDate); err != nil {
			return errors.New("contract end date must be YYYY-MM-DD")
		}
	}
	return nil
}

func finite(v float64) bool { return !math.IsNaN(v) && !math.IsInf(v, 0) }
func encode(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return string(b)
}

// WellLock pins a well to a rig and an absolute calendar date in a scenario snapshot.
type WellLock struct {
	WellID    string `json:"well_id"`
	Platform  string `json:"platform"`
	StartDate string `json:"start_date"`
}

func validateLocks(locks []WellLock, dropped []string, startDate string, wells []Well, platforms []Platform) error {
	start, err := time.Parse("2006-01-02", startDate)
	if err != nil {
		return errors.New("choose a valid planning start date")
	}
	ws := map[string]Well{}
	ps := map[string]Platform{}
	excluded, seen := map[string]bool{}, map[string]bool{}
	for _, w := range wells {
		ws[w.Name] = w
	}
	for _, p := range platforms {
		ps[p.Name] = p
	}
	for _, name := range dropped {
		excluded[name] = true
	}
	for _, lock := range locks {
		w, exists := ws[lock.WellID]
		if !exists || seen[lock.WellID] {
			return errors.New("locked wells must exist and be unique")
		}
		seen[lock.WellID] = true
		if excluded[lock.WellID] {
			return errors.New("a locked well cannot also be excluded")
		}
		p, exists := ps[lock.Platform]
		supported := false
		for _, category := range p.Categories {
			if category == w.Category {
				supported = true
			}
		}
		if !exists || !supported {
			return errors.New("locked rig must exist and support the well category")
		}
		date, err := time.Parse("2006-01-02", lock.StartDate)
		if err != nil || date.Before(start) || date.AddDate(0, 0, w.DurationDays+p.MobDemobDays).After(start.AddDate(0, 0, 365)) {
			return errors.New("locked intervention must fit within the 365-day planning horizon")
		}
	}
	return nil
}
