package model

import (
	"reflect"
	"testing"
)

// DESIGN §17 item 16: {$absent: true} in a state or config override removes
// its key at any depth, marked for a later merge with mark.
func TestMergeValueAbsent(t *testing.T) {
	base := map[string]any{"core": map[string]any{"a": map[string]any{"v": int64(1)}, "b": int64(2)}, "keep": true}
	over := map[string]any{"core": map[string]any{"a": map[string]any{"$absent": true}, "zz": map[string]any{"$absent": true}}}
	got := MergeValue(base, over, false)
	want := map[string]any{"core": map[string]any{"b": int64(2)}, "keep": true}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("unmarked: %v", got)
	}
	// Marked, over a fixture layer, then merged over the initial state.
	marked := MergeValue(nil, over, true)
	if got := MergeValue(base, marked, false); !reflect.DeepEqual(got, want) {
		t.Errorf("marked then merged: %v", got)
	}
	// {$absent: false} and maps with other keys stay values.
	for _, v := range []any{map[string]any{"$absent": false}, map[string]any{"$absent": true, "x": 1}, nil, "s"} {
		if IsAbsentMark(v) {
			t.Errorf("IsAbsentMark(%v)", v)
		}
	}
	w := &World{Config: map[string]any{"k": int64(1)}, State: map[string]map[string]any{}}
	if err := w.Apply(WorldLayer{Config: map[string]any{"k": map[string]any{"$absent": true}}}); err != nil {
		t.Fatal(err)
	}
	if _, ok := w.Config["k"]; ok {
		t.Errorf("config %v", w.Config)
	}
}
