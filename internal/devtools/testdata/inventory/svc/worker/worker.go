package worker

import (
	"context"
	"time"

	"go.temporal.io/sdk/workflow"
)

type Activities struct{}

func (a *Activities) Provision(ctx context.Context, id string) error { return nil }
func (a *Activities) Teardown(ctx context.Context, id string) error  { return nil }
func (a *Activities) helper(ctx context.Context) error               { return nil }

func NewActivities() *Activities { return &Activities{} }

func ProvisionWorkflow(ctx workflow.Context, id string) error {
	var a *Activities
	_ = workflow.ExecuteActivity(ctx, a.Provision, id).Get(ctx, nil)
	return runStep(ctx)
}

// runStep takes a workflow.Context but is a helper, not a workflow.
func runStep(ctx workflow.Context) error { return nil }

func Register(w interface {
	RegisterWorkflow(any)
	RegisterActivity(any)
}) {
	w.RegisterWorkflow(ProvisionWorkflow)
	acts := NewActivities()
	w.RegisterActivity(acts)
}

func Start() {
	go sweep()
}

func sweep() {
	t := time.NewTicker(time.Minute)
	for range t.C {
	}
}

// waitReady polls in a retry loop; it is not background work.
func waitReady() {
	for {
		time.Sleep(time.Second)
		break
	}
}
