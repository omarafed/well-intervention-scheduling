package app

import (
	"math"
	"testing"
)

func TestDatasetValidation(t *testing.T) {
	w := Well{Name: " W-1 ", Category: "Logging", DurationDays: 5, GainBOPD: 500, Lat: 4, Lon: 112}
	if err := w.Validate(); err != nil || w.Name != "W-1" {
		t.Fatalf("valid well rejected: %v", err)
	}
	for _, lat := range []float64{91, math.NaN(), math.Inf(1)} {
		invalid := w
		invalid.Lat = lat
		if invalid.Validate() == nil {
			t.Fatalf("accepted latitude %v", lat)
		}
	}
	p := Platform{Name: "Platform-1", Categories: []string{"Logging"}, MobDemobDays: 2, DailyCostKUSD: .001, ContractEndDate: "2027-09-10"}
	if err := p.Validate(); err != nil {
		t.Fatal(err)
	}
	p.ContractEndDate = "2027-02-30"
	if p.Validate() == nil {
		t.Fatal("accepted invalid contract date")
	}
	p.ContractEndDate = ""
	p.Categories = []string{" "}
	if p.Validate() == nil {
		t.Fatal("accepted empty category")
	}
}
