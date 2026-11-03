package main

import "testing"

func TestParseKillFault(t *testing.T) {
	f, err := parseFault("gpu-worker:kill:12.5:rank2")
	if err != nil || f.Type != "kill" || f.AtMS == nil || *f.AtMS != 12.5 || f.Instance != "rank2" || f.Target != "gpu-worker" {
		t.Fatalf("got %+v, %v", f, err)
	}
	if _, err := parseFault("gpu-worker:kill"); err == nil {
		t.Error("kill without a time accepted")
	}
	if _, err := parseFault(`{"target":"gpu-worker","type":"kill"}`); err == nil {
		t.Error("JSON kill without at_ms accepted")
	}
}
