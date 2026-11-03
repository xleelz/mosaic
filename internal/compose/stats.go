package compose

import (
	"fmt"
	"io"
	"sort"
	"strings"
	"time"
)

// AgentStats sums agent sessions (DESIGN §14.13): turns, the sessions' own
// duration_ms, and cost.
type AgentStats struct {
	Sessions   int     `json:"sessions"`
	NumTurns   int     `json:"num_turns"`
	DurationMS int64   `json:"duration_ms"`
	CostUSD    float64 `json:"total_cost_usd"`
}

func (a *AgentStats) add(b AgentStats) {
	a.Sessions += b.Sessions
	a.NumTurns += b.NumTurns
	a.DurationMS += b.DurationMS
	a.CostUSD += b.CostUSD
}

// StageStats is one top-level stage of a run: its wall time from the
// events, and the agent stats of its turns. A fanout's branch stages roll
// up under it.
type StageStats struct {
	Stage    string      `json:"stage"`
	WallMS   int64       `json:"wall_ms"`
	Branches int         `json:"branches,omitempty"` // fanout branches that ran
	Agent    *AgentStats `json:"agent,omitempty"`
}

// RunStats is one task's stats.
type RunStats struct {
	WallMS int64        `json:"wall_ms"`
	Agent  AgentStats   `json:"agent"`
	Stages []StageStats `json:"stages"`
}

// TreeStats sums a tree: its wall time (first start to last finish) and the
// agent stats of every task.
type TreeStats struct {
	WallMS int64      `json:"wall_ms"`
	Agent  AgentStats `json:"agent"`
}

// AddStats fills in every node's Stats and the tree's, from each task's
// events and turns/*.meta.json. Runs from before meta files existed get
// wall times only.
func (t *Tree) AddStats(s *Store) error {
	t.Stats = &TreeStats{}
	var first, last time.Time
	var walk func(n *TreeNode) error
	walk = func(n *TreeNode) error {
		rs, lo, hi, err := runStats(s, n.ID)
		if err != nil {
			return err
		}
		n.Stats = rs
		t.Stats.Agent.add(rs.Agent)
		if !lo.IsZero() && (first.IsZero() || lo.Before(first)) {
			first = lo
		}
		if hi.After(last) {
			last = hi
		}
		for _, c := range n.Children {
			if err := walk(c); err != nil {
				return err
			}
		}
		return nil
	}
	if err := walk(t.Root); err != nil {
		return err
	}
	if !first.IsZero() {
		t.Stats.WallMS = last.Sub(first).Milliseconds()
	}
	return nil
}

// runStats computes a task's stats, and the time span its events cover.
func runStats(s *Store, id string) (*RunStats, time.Time, time.Time, error) {
	var lo, hi time.Time
	rec, err := s.Load(id)
	if err != nil {
		return nil, lo, hi, err
	}
	events, err := s.Events(id)
	if err != nil {
		return nil, lo, hi, err
	}
	metas, err := s.TurnMetas(id)
	if err != nil {
		return nil, lo, hi, err
	}
	if len(events) > 0 {
		lo, hi = events[0].Time, events[len(events)-1].Time
	}
	rs := &RunStats{}

	// Wall time: started/resumed..finished for the run, stage_started..
	// stage_finished per stage path. An interval left open (interrupted, or
	// still running) closes at the next start or the last event.
	var runOpen *time.Time
	stageOpen := map[string]time.Time{}
	stageWall := map[string]int64{}
	branches := map[string]map[string]bool{}
	for _, ev := range events {
		switch ev.Type {
		case "started", "resumed":
			if runOpen != nil {
				rs.WallMS += ev.Time.Sub(*runOpen).Milliseconds()
			}
			tm := ev.Time
			runOpen = &tm
		case "finished":
			if runOpen != nil {
				rs.WallMS += ev.Time.Sub(*runOpen).Milliseconds()
				runOpen = nil
			}
		case "stage_started":
			if st, ok := stageOpen[ev.Stage]; ok {
				stageWall[ev.Stage] += ev.Time.Sub(st).Milliseconds()
			}
			stageOpen[ev.Stage] = ev.Time
		case "stage_finished":
			if st, ok := stageOpen[ev.Stage]; ok {
				stageWall[ev.Stage] += ev.Time.Sub(st).Milliseconds()
				delete(stageOpen, ev.Stage)
			} else if _, seen := stageWall[ev.Stage]; !seen {
				stageWall[ev.Stage] = 0
			}
		}
		if top, rest, ok := strings.Cut(ev.Stage, "/"); ok {
			if b, _, ok := strings.Cut(rest, "/"); ok {
				if branches[top] == nil {
					branches[top] = map[string]bool{}
				}
				branches[top][b] = true
			}
		}
	}
	if runOpen != nil {
		rs.WallMS += hi.Sub(*runOpen).Milliseconds()
	}
	for p, st := range stageOpen {
		stageWall[p] += hi.Sub(st).Milliseconds()
	}

	byTop := map[string]*StageStats{}
	get := func(top string) *StageStats {
		ss := byTop[top]
		if ss == nil {
			ss = &StageStats{Stage: top}
			byTop[top] = ss
		}
		return ss
	}
	for p, ms := range stageWall {
		if !strings.Contains(p, "/") {
			get(p).WallMS += ms
		} else {
			get(topStage(p))
		}
	}
	for top, bs := range branches {
		get(top).Branches = len(bs)
	}
	for p, m := range metas {
		var a AgentStats
		for _, at := range m.Attempts {
			a.add(AgentStats{Sessions: 1, NumTurns: at.NumTurns, DurationMS: at.DurationMS, CostUSD: at.CostUSD})
		}
		ss := get(topStage(p))
		if ss.Agent == nil {
			ss.Agent = &AgentStats{}
		}
		ss.Agent.add(a)
		rs.Agent.add(a)
	}

	// Template order first, then anything else by name.
	var order []string
	seen := map[string]bool{}
	if tpl, err := Parse(rec.Template); err == nil {
		for _, st := range tpl.Stages {
			if byTop[st.ID] != nil {
				order = append(order, st.ID)
				seen[st.ID] = true
			}
		}
	}
	var rest []string
	for k := range byTop {
		if !seen[k] {
			rest = append(rest, k)
		}
	}
	sort.Strings(rest)
	for _, k := range append(order, rest...) {
		rs.Stages = append(rs.Stages, *byTop[k])
	}
	return rs, lo, hi, nil
}

func topStage(path string) string {
	top, _, _ := strings.Cut(path, "/")
	return top
}

func fmtMS(ms int64) string {
	return (time.Duration(ms) * time.Millisecond).Round(time.Second).String()
}

func (a AgentStats) text() string {
	return fmt.Sprintf("%d session(s), %d turn(s), agent %s, $%.2f", a.Sessions, a.NumTurns, fmtMS(a.DurationMS), a.CostUSD)
}

// writeText prints a node's stats under its line.
func (rs *RunStats) writeText(w io.Writer, pad string) {
	line := fmt.Sprintf("%s  stats: wall %s", pad, fmtMS(rs.WallMS))
	if rs.Agent.Sessions > 0 {
		line += "; " + rs.Agent.text()
	}
	fmt.Fprintln(w, line)
	width := 0
	for _, ss := range rs.Stages {
		if len(ss.Stage) > width {
			width = len(ss.Stage)
		}
	}
	for _, ss := range rs.Stages {
		line := fmt.Sprintf("%s    %-*s  wall %8s", pad, width, ss.Stage, fmtMS(ss.WallMS))
		if ss.Agent != nil {
			line += "  " + ss.Agent.text()
		}
		if ss.Branches > 0 {
			line += fmt.Sprintf("  (%d branch(es))", ss.Branches)
		}
		fmt.Fprintln(w, line)
	}
}
