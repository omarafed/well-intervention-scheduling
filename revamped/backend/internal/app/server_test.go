package app

import (
	"net/http/httptest"
	"testing"

	"github.com/labstack/echo/v4"
)

func TestHistoryOptions(t *testing.T) {
	for _, query := range []string{"page=0", "page=-1", "page=abc", "page_size=101", "page_size=0", "kind=unknown", "status=unknown"} {
		c := echo.New().NewContext(httptest.NewRequest("GET", "/jobs?"+query, nil), httptest.NewRecorder())
		if _, err := parseHistoryOptions(c); err == nil {
			t.Errorf("accepted %s", query)
		}
	}
	c := echo.New().NewContext(httptest.NewRequest("GET", "/jobs?page=12&page_size=25&search=%20Test%20&kind=import:wells&status=completed", nil), httptest.NewRecorder())
	options, err := parseHistoryOptions(c)
	if err != nil || options.Page != 12 || options.Size != 25 || options.Search != "Test" || options.Kind != "import:wells" || options.Status != "completed" {
		t.Fatalf("invalid options: %+v, %v", options, err)
	}
}

func TestValidateLocks(t *testing.T) {
	wells := []Well{{Name: "W1", Category: "Logging", DurationDays: 5}}
	rigs := []Platform{{Name: "R1", Categories: []string{"Logging"}, MobDemobDays: 2}, {Name: "R2", Categories: []string{"Other"}}}
	valid := WellLock{WellID: "W1", Platform: "R1", StartDate: "2026-11-01"}
	if err := validateLocks([]WellLock{valid}, nil, "2026-10-30", wells, rigs); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []WellLock{
		{WellID: "missing", Platform: "R1", StartDate: valid.StartDate},
		{WellID: "W1", Platform: "missing", StartDate: valid.StartDate},
		{WellID: "W1", Platform: "R2", StartDate: valid.StartDate},
		{WellID: "W1", Platform: "R1", StartDate: "bad"},
		{WellID: "W1", Platform: "R1", StartDate: "2026-10-29"},
		{WellID: "W1", Platform: "R1", StartDate: "2027-10-29"},
	} {
		if validateLocks([]WellLock{invalid}, nil, "2026-10-30", wells, rigs) == nil {
			t.Errorf("accepted %+v", invalid)
		}
	}
	if validateLocks([]WellLock{valid, valid}, nil, "2026-10-30", wells, rigs) == nil {
		t.Fatal("accepted duplicate locks")
	}
	if validateLocks([]WellLock{valid}, []string{"W1"}, "2026-10-30", wells, rigs) == nil {
		t.Fatal("accepted excluded lock")
	}
}
