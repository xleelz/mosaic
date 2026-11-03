package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeTree writes a synthetic fixture, path -> contents, under a temporary
// root.
func writeTree(t *testing.T, files map[string]string) string {
	t.Helper()
	root := t.TempDir()
	for rel, src := range files {
		p := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(strings.TrimLeft(src, "\n")), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestRouteHelpersAndTables(t *testing.T) {
	root := writeTree(t, map[string]string{
		"go.mod": "module example.com/app\n",
		"store/model/family.go": `
package model

type Family struct{ Name, Path string }

func (f Family) PublicPath() string { return "/v1" + f.Path }

var Families = []Family{
	{Name: "chat", Path: "/chat"},
	{Name: "embed", Path: "/embed"},
}

const DiscoveryPath = "/.well-known/openid-configuration"
`,
		"api/routes.go": `
package api

import (
	"net/http"

	"example.com/app/store/model"
)

type Server struct{}

type invokeRoute struct{ path string }

var batchInvoke = invokeRoute{path: "/internal/invoke"}

const issuerPath = "/oidc"

// gate is a route helper: its pattern parameter reaches HandleFunc.
func (s *Server) gate(mux *http.ServeMux, pattern, name string, h http.HandlerFunc) {
	mux.HandleFunc(pattern, h)
}

// spec forwards to gate.
func (s *Server) spec(mux *http.ServeMux, pattern, op string, h http.HandlerFunc) {
	s.gate(mux, pattern, op, h)
}

func register(mux *http.ServeMux, s *Server, h http.HandlerFunc) {
	admin := func(pattern string, h http.HandlerFunc) {
		s.gate(mux, pattern, "", h)
	}
	admin("GET /v1/admin/nodes/{id}", h)
	admin("POST /v1/admin/reconcile", h)
	s.spec(mux, "POST /v1/requests", "CreateRequest", h)
	for _, f := range model.Families {
		mux.Handle("POST "+f.PublicPath(), h)
	}
	mux.Handle("GET "+issuerPath+model.DiscoveryPath, h)
	mux.Handle("POST "+batchInvoke.path, h)
	for _, r := range dynamicRoutes() {
		mux.Handle(r.method+" "+r.path, h)
	}
	logOnly("GET /not/a/route")
}

type route struct{ method, path string }

func dynamicRoutes() []route { return nil }

func logOnly(s string) {}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"go"}})
	want := []string{
		"http-route GET /v1/admin/nodes/{id}",
		"http-route POST /v1/admin/reconcile",
		"http-route POST /v1/requests",
		"http-route POST /v1/chat",
		"http-route POST /v1/embed",
		"http-route GET /oidc/.well-known/openid-configuration",
		"http-route POST /internal/invoke",
	}
	// The helpers' own HandleFunc(pattern) and the unexpandable table loop
	// are not routes; a string that only looks like a pattern is not either.
	bad := []string{"{pattern}", "{r.", "/not/a/route"}
	checks := []check{
		{"http-route GET /v1/admin/nodes/{id}", "api/routes.go", 31, 0, "route-helper", "registered through admin"},
		{"http-route POST /v1/requests", "api/routes.go", 33, 0, "route-helper", "registered through Server.spec"},
		{"http-route POST /v1/embed", "api/routes.go", 35, 0, "route-table", "one per row of model.Families"},
	}
	expect(t, have, keys, want, bad, checks)
}

func TestLoopHelpers(t *testing.T) {
	root := writeTree(t, map[string]string{
		"cp/lease.go": `
package cp

import (
	"context"
	"time"
)

type Server struct{}

func (s *Server) leads() bool { return true }

// runPassLoop is the shared ticker: its passes are the entry points.
func runPassLoop(ctx context.Context, name string, every time.Duration, gate func() bool, fn func(context.Context)) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if gate() {
				fn(ctx)
			}
		}
	}
}

func (s *Server) leaderLoop(ctx context.Context, name string, every time.Duration, fn func(context.Context)) {
	runPassLoop(ctx, name, every, s.leads, fn)
}

// retry is not a loop helper: the callback's result ends the loop.
func retry(ctx context.Context, name string, fn func() error) error {
	for {
		if err := fn(); err == nil {
			return nil
		}
		time.Sleep(time.Second)
	}
}

func (s *Server) settle(ctx context.Context) {}

func (s *Server) start(ctx context.Context) {
	go s.leaderLoop(ctx, "settlement", time.Hour, s.settle)
	go runPassLoop(ctx, "janitor-full", time.Hour, s.leads, func(ctx context.Context) {})
	_ = retry(ctx, "dial", func() error { return nil })
}
`,
		"agent/supervise.go": `
package agent

import "time"

func supervisePod() {
	t := time.NewTicker(time.Second)
	for {
		<-t.C
	}
}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"go"}})
	want := []string{"cron settlement", "cron janitor-full", "cron supervisePod"}
	bad := []string{"runPassLoop", "dial", "retry"}
	checks := []check{
		{"cron settlement", "cp/lease.go", 45, 0, "loop-helper", "Server.leaderLoop runs s.settle"},
		{"cron janitor-full", "cp/lease.go", 46, 0, "loop-helper", "runPassLoop runs func literal"},
	}
	expect(t, have, keys, want, bad, checks)
}

func TestListenersConsumersServices(t *testing.T) {
	root := writeTree(t, map[string]string{
		"gw/main.go": `
package main

import (
	"context"
	"net"
	"net/http"
	"os/signal"
	"syscall"
	"time"
)

type proxy struct{}

func (proxy) ServeHTTP(http.ResponseWriter, *http.Request) {}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM)
	defer stop()
	srv := &http.Server{Handler: &proxy{}}
	mux := http.NewServeMux()
	api := &http.Server{Handler: mux}
	ln, _ := net.Listen("tcp", ":22")
	go serve(ctx, ln)
	_ = api
	_ = srv.ListenAndServe()
}

func serve(ctx context.Context, ln net.Listener) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			time.Sleep(100 * time.Millisecond)
			continue
		}
		_ = conn
	}
}
`,
		"gw/pubsub.go": `
package main

import "context"

type sub interface{ Channel() <-chan string }
type rdb interface{ Subscribe(ctx context.Context, ch string) sub }
type events interface {
	StreamEvents(ctx context.Context, fn func(ev string)) error
}

func consumeInvalidations(ctx context.Context, r rdb) {
	s := r.Subscribe(ctx, "keys")
	for msg := range s.Channel() {
		_ = msg
	}
}

func consumeEvents(ctx context.Context, e events) {
	_ = e.StreamEvents(ctx, func(ev string) {})
}
`,
		"tool/main.go": `
package main

import (
	"flag"
	"net/http"
)

func main() {
	flag.Parse()
	_ = http.ListenAndServe(":8080", nil)
}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"go"}})
	want := []string{
		"listener http.Server proxy",
		"listener serve",
		"queue-consumer consumeInvalidations",
		"queue-consumer consumeEvents StreamEvents",
		"service-main gw",
		"cli-command tool",
	}
	// The accept loop sleeps, but it is a listener, not a cron; a server
	// whose handler is a mux is covered by its routes; a main with flags is a
	// CLI.
	bad := []string{"cron", "http.Server mux", "service-main tool"}
	checks := []check{
		{"listener http.Server proxy", "gw/main.go", 19, 0, "http-server", "in main"},
		{"listener serve", "gw/main.go", 29, 37, "accept-loop", ""},
		{"queue-consumer consumeInvalidations", "gw/pubsub.go", 11, 16, "subscribe-loop", "Subscribe"},
		{"queue-consumer consumeEvents StreamEvents", "gw/pubsub.go", 19, 0, "subscribe-callback", ""},
		{"service-main gw", "gw/main.go", 16, 26, "service-main", ""},
	}
	expect(t, have, keys, want, bad, checks)
}

func TestCommandTablesAndModes(t *testing.T) {
	root := writeTree(t, map[string]string{
		"cli/capability.go": `
package cli

import "github.com/spf13/cobra"

type capability struct {
	CmdPath []string
	Aliases []string
	Summary string
}

func (c capability) command() *cobra.Command {
	use := c.CmdPath[len(c.CmdPath)-1]
	return &cobra.Command{Use: use, Aliases: c.Aliases, Short: c.Summary}
}

func NewRoot() *cobra.Command {
	root := &cobra.Command{Use: "gw"}
	return root
}

var chat = capability{
	CmdPath: []string{"chat"},
	Aliases: []string{"talk"},
}
`,
		"cli/commands.gen.go": `
// Code generated. DO NOT EDIT.

package cli

type operation struct {
	ID      string
	CmdPath []string
}

var operations = []operation{
	{
		ID:      "listVms",
		CmdPath: []string{"vms", "list"},
	},
	{
		ID:      "createVm",
		CmdPath: []string{"vms", "create"},
	},
}

func fromOp(op operation) capability { return capability{CmdPath: op.CmdPath} }
`,
		"agent/main.go": `
package main

import (
	"context"
	"os"
)

type mode int

const (
	modeNone mode = iota
	modeControl
	modeTunnel
)

func modeFromArgs() mode {
	if len(os.Args) > 1 && os.Args[1] == "tunnel" {
		return modeTunnel
	}
	return modeControl
}

func main() {
	m := modeFromArgs()
	switch m {
	case modeTunnel:
		runTunnel(context.Background())
	case modeControl:
		runControl(context.Background())
	}
}
`,
		"agent/control.go": `
package main

import "context"

func runControl(ctx context.Context) {}

func runTunnel(ctx context.Context) {}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"go"}})
	want := []string{
		"cli-command gw",
		"cli-command gw chat",
		"cli-command gw vms list",
		"cli-command gw vms create",
		"cli-command agent tunnel",
		"cli-command agent control",
	}
	bad := []string{"talk"}
	checks := []check{
		{"cli-command gw chat", "cli/capability.go", 22, 0, "command-table", "capability.CmdPath"},
		{"cli-command gw vms create", "cli/commands.gen.go", 17, 0, "command-table", "operation.CmdPath"},
		{"cli-command agent tunnel", "agent/control.go", 7, 7, "argv-mode", ""},
	}
	expect(t, have, keys, want, bad, checks)
}

func TestNomadAndSchedules(t *testing.T) {
	root := writeTree(t, map[string]string{
		"cp/nomad/jobs.go": `
package nomad

func job(id string, group map[string]any) map[string]any {
	return map[string]any{"ID": id, "TaskGroups": []map[string]any{group}}
}

func BuildGcJob(id string) map[string]any { return job(id, nil) }

func BuildPodJob(id string) map[string]any { return job(id, nil) }

func helperJob() map[string]any { return nil }
`,
		"cp/jobapi/api.go": `
package jobapi

import "github.com/hashicorp/nomad/api"

func reaper() *api.Job { return &api.Job{} }
`,
		"cp/other/build.go": `
package other

func BuildReportJob() string { return "" }
`,
		"deploy/web.nomad.hcl": `
job "web" {
  type = "batch"
  periodic {
    crons = ["*/15 * * * *"]
  }
}
`,
		"worker/schedules.go": `
package worker

import (
	"time"

	"go.temporal.io/sdk/client"
)

type FleetSchedule struct {
	ID           string
	Interval     time.Duration
	WorkflowType string
}

func Schedules() []FleetSchedule {
	return []FleetSchedule{
		{ID: "reaper", Interval: time.Hour, WorkflowType: "Reaper"},
	}
}

func create(sc client.ScheduleClient, fs FleetSchedule) {
	_ = client.ScheduleOptions{ID: fs.ID, Action: &client.ScheduleWorkflowAction{ID: "x", Workflow: fs.WorkflowType}}
}

var _ = client.ScheduleOptions{ID: "pool-scrape", Action: &client.ScheduleWorkflowAction{Workflow: "PoolScrape"}}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"go"}})
	want := []string{
		"nomad-job BuildGcJob",
		"nomad-job BuildPodJob",
		"nomad-job reaper",
		"nomad-job job web",
		"cron nomad web */15 * * * *",
		"cron temporal-schedule reaper -> Reaper",
		"cron temporal-schedule pool-scrape -> PoolScrape",
	}
	// Builders outside a Nomad package, and schedules created from a
	// parameter (the table rows are the entries), are not listed.
	bad := []string{"BuildReportJob", "helperJob", "fs.ID"}
	checks := []check{
		{"nomad-job BuildGcJob", "cp/nomad/jobs.go", 7, 7, "nomad-jobspec", ""},
		{"nomad-job job web", "deploy/web.nomad.hcl", 1, 0, "nomad-file", ""},
		{"cron temporal-schedule reaper -> Reaper", "worker/schedules.go", 17, 0, "temporal-schedule", ""},
	}
	expect(t, have, keys, want, bad, checks)
}

func TestTSPythonInfra(t *testing.T) {
	root := writeTree(t, map[string]string{
		"apps/dash/src/server/routers/kube.ts": `
import { router, orgProcedure, adminProcedure } from "../trpc";

const read = orgProcedure.use(async ({ next }) => next());
const gated = (action: string) =>
  adminProcedure.use(async ({ next }) => next());
const write = gated("kube.write");
const id = z.string();
const action = (path: string) =>
  adminProcedure.input(z.object({ id })).mutation(() => path);

export const kubeRouter = router({
  list: read.query(() => []),
  create: write
    .input(z.object({ id }))
    .mutation(() => null),
  award: action("award"),
  helper: id,
});
`,
		"svc/app.py": `
from fastapi import FastAPI

def build_app():
    app = FastAPI()

    @app.post("/v1/decisions")
    async def decisions(body):
        return body
    return app
`,
		"svc/status.py": `
from http.server import BaseHTTPRequestHandler

STATUS_PATH = "/status"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == STATUS_PATH:
            return
        elif self.path == "/metrics":
            return

    def do_POST(self):
        if self.path != "/tokenize":
            self.send_error(404)
            return
`,
		"infra/archive/main.tf": `
data "archive_file" "lambda" {
  source_file = "${path.module}/lambda/handler.py"
}

resource "aws_lambda_function" "archive" {
  handler = "handler.handler"
}

resource "aws_lambda_event_source_mapping" "archive" {
  function_name = aws_lambda_function.archive.arn
}
`,
		"infra/archive/lambda/handler.py": `
def helper():
    pass


def handler(event, context):
    return None
`,
		"infra/alarms/main.tf": `
resource "aws_lambda_function" "reconciler" {
  handler = "index.handler"
}
`,
		"infra/alarms/index.mjs": `
export const handler = async (event) => {};
`,
		"apps/site/vercel.json": `
{
  "crons": [
    { "path": "/api/cron/sync", "schedule": "0 * * * *" }
  ]
}
`,
	})
	have, keys := scanKeys(t, root, Options{Langs: []string{"ts", "python"}})
	want := []string{
		"trpc-procedure kube.list",
		"trpc-procedure kube.create",
		"trpc-procedure kube.award",
		"http-route POST /v1/decisions",
		"http-route GET /status",
		"http-route GET /metrics",
		"http-route POST /tokenize",
		"queue-consumer lambda archive",
		"lambda-handler lambda reconciler",
		"cron vercel /api/cron/sync 0 * * * *",
	}
	bad := []string{"kube.helper", "kubeRouter"}
	checks := []check{
		{"trpc-procedure kube.create", "apps/dash/src/server/routers/kube.ts", 13, 0, "trpc-local-procedure", "built from write"},
		{"trpc-procedure kube.award", "apps/dash/src/server/routers/kube.ts", 16, 0, "trpc-local-procedure", "built from action"},
		{"http-route POST /v1/decisions", "svc/app.py", 6, 8, "fastapi", "handler build_app.decisions"},
		{"http-route GET /status", "svc/status.py", 7, 0, "http-handler-class", "Handler.do_GET"},
		{"http-route POST /tokenize", "svc/status.py", 12, 15, "http-handler-class", "Handler.do_POST"},
		{"queue-consumer lambda archive", "infra/archive/lambda/handler.py", 5, 0, "terraform-lambda", "aws_lambda_function.archive handler handler.handler"},
		{"lambda-handler lambda reconciler", "infra/alarms/index.mjs", 1, 0, "terraform-lambda", "aws_lambda_function.reconciler handler index.handler"},
		{"cron vercel /api/cron/sync 0 * * * *", "apps/site/vercel.json", 3, 0, "vercel-cron", ""},
	}
	expect(t, have, keys, want, bad, checks)
}
