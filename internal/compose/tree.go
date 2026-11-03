package compose

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

// TreeNode is one task of a run tree (FAE-API-035).
type TreeNode struct {
	ID       string           `json:"id"`
	Workflow string           `json:"workflow"`
	Version  string           `json:"version,omitempty"`
	Parent   string           `json:"parent,omitempty"`
	State    string           `json:"state"`
	Reason   string           `json:"reason,omitempty"`
	Error    string           `json:"error,omitempty"`
	Depth    int              `json:"depth"`
	Detached bool             `json:"detached,omitempty"`
	Outputs  []string         `json:"outputs,omitempty"` // declared outputs recorded
	Requests []*ChangeRequest `json:"requests,omitempty"`
	Refusals []Refusal        `json:"refusals,omitempty"`
	Children []*TreeNode      `json:"children,omitempty"`
	Stats    *RunStats        `json:"stats,omitempty"` // set by Tree.AddStats
}

// Refusal is a stage that failed on a budget (recursion_budget or
// max_branches).
type Refusal struct {
	Stage  string `json:"stage"`
	Reason string `json:"reason"`
	Error  string `json:"error"`
}

// Tree is a run tree with its budget use.
type Tree struct {
	Root        *TreeNode  `json:"root"`
	Tasks       int        `json:"tasks"`
	Descendants int        `json:"descendants"`
	MaxDepth    int        `json:"max_depth"`
	Stats       *TreeStats `json:"stats,omitempty"` // set by AddStats
}

// ReadTree returns the run tree containing task.
func ReadTree(s *Store, task string) (*Tree, error) {
	rec, err := s.Load(task)
	if err != nil {
		return nil, err
	}
	all, err := s.List()
	if err != nil {
		return nil, err
	}
	nodes := map[string]*TreeNode{}
	var members []*RunRecord
	for _, x := range all {
		if x.TreeRoot == rec.TreeRoot {
			members = append(members, x)
		}
	}
	t := &Tree{}
	for _, x := range members {
		n := &TreeNode{ID: x.ID, Workflow: x.Workflow, Version: x.Version, Parent: x.Parent, State: x.State,
			Reason: x.Reason, Error: x.Error, Depth: x.Depth, Detached: x.Origin != nil && x.Origin.Detached}
		if tpl, err := Parse(x.Template); err == nil {
			for _, o := range sortedKeys(tpl.Outputs) {
				if _, ok := x.Artifacts[o]; ok {
					n.Outputs = append(n.Outputs, o)
				}
			}
		}
		n.Requests, _ = s.Requests(x.ID)
		n.Refusals = refusals("", x.Stages)
		nodes[x.ID] = n
		t.Tasks++
		if x.Parent != "" {
			t.Descendants++
		}
		if x.Depth > t.MaxDepth {
			t.MaxDepth = x.Depth
		}
	}
	for _, x := range members {
		n := nodes[x.ID]
		if p := nodes[x.Parent]; p != nil {
			p.Children = append(p.Children, n)
		} else if x.ID == rec.TreeRoot {
			t.Root = n
		}
	}
	for _, n := range nodes {
		sort.Slice(n.Children, func(i, j int) bool { return n.Children[i].ID < n.Children[j].ID })
	}
	if t.Root == nil {
		return nil, fmt.Errorf("tree root %s of %s is missing", rec.TreeRoot, task)
	}
	return t, nil
}

func refusals(prefix string, states map[string]*StageState) []Refusal {
	var out []Refusal
	for _, id := range sortedKeys(states) {
		ss := states[id]
		if ss.State == StateFailed && (ss.Reason == ReasonRecursionBudget || ss.Reason == ReasonMaxBranches) {
			out = append(out, Refusal{Stage: prefix + id, Reason: ss.Reason, Error: ss.Error})
		}
		for _, b := range ss.Branches {
			out = append(out, refusals(fmt.Sprintf("%s%s/%d/", prefix, id, b.Index), b.Stages)...)
		}
	}
	return out
}

// Refusals lists every budget refusal in the tree.
func (t *Tree) Refusals() []Refusal {
	var out []Refusal
	var walk func(n *TreeNode)
	walk = func(n *TreeNode) {
		for _, r := range n.Refusals {
			r.Stage = n.ID + ":" + r.Stage
			out = append(out, r)
		}
		for _, c := range n.Children {
			walk(c)
		}
	}
	walk(t.Root)
	return out
}

// WriteText prints the tree: one task per line with its state and depth,
// then its change requests and budget refusals.
func (t *Tree) WriteText(w io.Writer) {
	var walk func(n *TreeNode, indent, branch string)
	walk = func(n *TreeNode, indent, branch string) {
		line := fmt.Sprintf("%s%s%s  %s", indent, branch, n.ID, n.Workflow)
		if n.Version != "" {
			line += "@" + n.Version
		}
		line += fmt.Sprintf("  %s  depth %d", n.State, n.Depth)
		if n.Detached {
			line += "  detached"
		}
		if n.Reason != "" {
			line += "  (" + n.Reason + ")"
		}
		fmt.Fprintln(w, line)
		sub := indent
		if branch != "" {
			if strings.HasPrefix(branch, "└") {
				sub = indent + "    "
			} else {
				sub = indent + "│   "
			}
		}
		pad := sub
		if len(n.Children) > 0 {
			pad += "│ "
		} else {
			pad += "  "
		}
		for _, r := range n.Requests {
			fmt.Fprintf(w, "%s  request %s from %s (%s)", pad, r.ID, r.FromTask, r.State)
			if r.Target.Artifact != "" {
				fmt.Fprintf(w, " on %s", r.Target.Artifact)
			}
			fmt.Fprintln(w)
		}
		for _, r := range n.Refusals {
			fmt.Fprintf(w, "%s  refused %s: %s: %s\n", pad, r.Stage, r.Reason, r.Error)
		}
		if n.Stats != nil {
			n.Stats.writeText(w, pad)
		}
		for i, c := range n.Children {
			b := "├── "
			if i == len(n.Children)-1 {
				b = "└── "
			}
			walk(c, sub, b)
		}
	}
	walk(t.Root, "", "")
	fmt.Fprintf(w, "%d task(s), %d descendant(s), max depth %d\n", t.Tasks, t.Descendants, t.MaxDepth)
	if t.Stats != nil {
		line := "tree: wall " + fmtMS(t.Stats.WallMS)
		if t.Stats.Agent.Sessions > 0 {
			line += "; " + t.Stats.Agent.text()
		}
		fmt.Fprintln(w, line)
	}
}
