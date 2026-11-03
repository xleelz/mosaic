// Package api is mosaicd's HTTP server (docs/DESIGN.md §6). Wire types live
// in pkg/api.
package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/selfupdate"
	"github.com/xleelz/mosaic/internal/store"
	wire "github.com/xleelz/mosaic/pkg/api"
)

// DefaultOrigins are the CORS origins allowed when none are configured: the
// web UI's dev server.
var DefaultOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

// maxBody bounds request bodies.
const maxBody = 32 << 20

// Config configures a Server.
type Config struct {
	Store   *store.Store
	Version string
	// Token, when set, is required as "Authorization: Bearer <token>".
	Token string
	// Origins are the allowed CORS origins ("*" allows any); nil means DefaultOrigins.
	Origins []string
	// DoltVersion reports the Dolt server version for /v1/health.
	DoltVersion func(context.Context) (string, error)
	// Logger receives one line per request (default: the standard logger).
	Logger *log.Logger
	// Now overrides the clock (tests).
	Now func() time.Time
	// Workdir is the repo root whose local stores are served read-only
	// (.mosaic/compose/runs and .mosaic/replay, local.go); default ".".
	Workdir string
	// Updater serves /v1/system/version and /v1/system/update; nil reports
	// updates as unavailable (no source directory).
	Updater *selfupdate.Updater
	// OnRestart is called, without blocking, after a supervised update's
	// response is written: mosaicd then shuts down and exits with
	// selfupdate.ExitRestart.
	OnRestart func()
}

// Server serves the API.
type Server struct {
	cfg     Config
	store   *store.Store
	origins map[string]bool
	anyOrig bool
	updater *selfupdate.Updater
	handler http.Handler
}

// New builds a server.
func New(cfg Config) *Server {
	if cfg.Origins == nil {
		cfg.Origins = DefaultOrigins
	}
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	s := &Server{cfg: cfg, store: cfg.Store, origins: map[string]bool{}, updater: cfg.Updater}
	if s.updater == nil {
		s.updater = selfupdate.New(selfupdate.Options{Version: cfg.Version})
	}
	for _, o := range cfg.Origins {
		o = strings.TrimRight(strings.TrimSpace(o), "/")
		if o == "*" {
			s.anyOrig = true
		} else if o != "" {
			s.origins[o] = true
		}
	}
	mux := http.NewServeMux()
	s.routes(mux)
	s.handler = s.logRequests(s.cors(s.auth(mux)))
	return s
}

// ServeHTTP implements http.Handler.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) { s.handler.ServeHTTP(w, r) }

func (s *Server) routes(m *http.ServeMux) {
	m.HandleFunc("GET /v1/health", s.health)
	m.HandleFunc("GET /v1/ontologies", s.listOntologies)
	m.HandleFunc("POST /v1/ontologies", s.createOntology)
	m.HandleFunc("GET /v1/ontologies/{id}", s.getOntology)
	m.HandleFunc("PATCH /v1/ontologies/{id}", s.updateOntology)
	m.HandleFunc("DELETE /v1/ontologies/{id}", s.deleteOntology)
	m.HandleFunc("GET /v1/ontologies/{id}/document", s.getDocument)
	m.HandleFunc("PUT /v1/ontologies/{id}/document", s.putDocument)
	m.HandleFunc("GET /v1/ontologies/{id}/revisions", s.listRevisions)
	m.HandleFunc("POST /v1/ontologies/{id}/revisions", s.createRevision)
	m.HandleFunc("GET /v1/ontologies/{id}/revisions/{n}", s.getRevision)
	m.HandleFunc("GET /v1/ontologies/{id}/diff", s.diff)
	m.HandleFunc("GET /v1/ontologies/{id}/impact", s.impact)
	m.HandleFunc("GET /v1/ontologies/{id}/commits", s.listCommits)
	m.HandleFunc("POST /v1/ontologies/{id}/commits", s.importCommits)
	m.HandleFunc("GET /v1/ontologies/{id}/commits/{sha}", s.getCommit)
	m.HandleFunc("POST /v1/ontologies/{id}/validate", s.validate)
	m.HandleFunc("GET /v1/ontologies/{id}/graph", s.graph)
	m.HandleFunc("GET /v1/ontologies/{id}/flows/{flow}/plan", s.plan)
	m.HandleFunc("GET /v1/ontologies/{id}/simulations", s.listRuns)
	m.HandleFunc("POST /v1/ontologies/{id}/simulations", s.simulate)
	m.HandleFunc("GET /v1/simulations/{run}", s.getRun)
	m.HandleFunc("POST /v1/ontologies/{id}/test", s.test)
	m.HandleFunc("GET /v1/ontologies/{id}/{kind}", s.listEntities)
	m.HandleFunc("POST /v1/ontologies/{id}/{kind}", s.createEntity)
	m.HandleFunc("PUT /v1/ontologies/{id}/{kind}", s.upsertEntities)
	m.HandleFunc("GET /v1/ontologies/{id}/{kind}/{eid}", s.getEntity)
	m.HandleFunc("PUT /v1/ontologies/{id}/{kind}/{eid}", s.putEntity)
	m.HandleFunc("PATCH /v1/ontologies/{id}/{kind}/{eid}", s.patchEntity)
	m.HandleFunc("DELETE /v1/ontologies/{id}/{kind}/{eid}", s.deleteEntity)
	s.localRoutes(m)
	s.systemRoutes(m)
	m.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "not_found", "no route for "+r.Method+" "+r.URL.Path, nil)
	})
}

// ---- middleware ----

type recorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (r *recorder) WriteHeader(code int) {
	if r.status == 0 {
		r.status = code
	}
	r.ResponseWriter.WriteHeader(code)
}

func (r *recorder) Write(b []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	n, err := r.ResponseWriter.Write(b)
	r.bytes += n
	return n, err
}

func (s *Server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &recorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)
		if rec.status == 0 {
			rec.status = http.StatusOK
		}
		s.cfg.Logger.Printf("%s %s %d %dB %s", r.Method, r.URL.RequestURI(), rec.status, rec.bytes, time.Since(start).Round(time.Microsecond))
	})
}

func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		allowed := origin != "" && (s.anyOrig || s.origins[origin])
		if origin != "" {
			w.Header().Add("Vary", "Origin")
		}
		if allowed {
			w.Header().Set("Access-Control-Allow-Origin", origin)
		}
		if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
			if allowed {
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
				w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
				w.Header().Set("Access-Control-Max-Age", "600")
			}
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) auth(next http.Handler) http.Handler {
	if s.cfg.Token == "" {
		return next
	}
	want := []byte("Bearer " + s.cfg.Token)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got := []byte(r.Header.Get("Authorization"))
		if subtle.ConstantTimeCompare(got, want) != 1 {
			w.Header().Set("WWW-Authenticate", `Bearer realm="mosaicd"`)
			writeError(w, http.StatusUnauthorized, "unauthorized", "a valid bearer token is required", nil)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// ---- responses ----

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func writeError(w http.ResponseWriter, status int, code, msg string, issues []model.Issue) {
	writeJSON(w, status, wire.ErrorBody{Error: wire.ErrorDetail{Code: code, Message: msg, Issues: issues}})
}

var statusOf = map[string]int{
	store.CodeBadRequest: http.StatusBadRequest,
	store.CodeNotFound:   http.StatusNotFound,
	store.CodeConflict:   http.StatusConflict,
	store.CodeInvalid:    http.StatusUnprocessableEntity,
}

// fail writes err: store refusals keep their code, anything else is internal.
func (s *Server) fail(w http.ResponseWriter, r *http.Request, err error) {
	var se *store.Error
	if errors.As(err, &se) {
		writeError(w, statusOf[se.Code], se.Code, se.Message, se.Issues)
		return
	}
	var tooBig *http.MaxBytesError
	if errors.As(err, &tooBig) {
		writeError(w, http.StatusRequestEntityTooLarge, "bad_request", fmt.Sprintf("request body exceeds %d bytes", tooBig.Limit), nil)
		return
	}
	s.cfg.Logger.Printf("internal error: %s %s: %v", r.Method, r.URL.Path, err)
	writeError(w, http.StatusInternalServerError, "internal", err.Error(), nil)
}

func badRequest(format string, a ...any) error {
	return &store.Error{Code: store.CodeBadRequest, Message: fmt.Sprintf(format, a...)}
}

func notFound(format string, a ...any) error {
	return &store.Error{Code: store.CodeNotFound, Message: fmt.Sprintf(format, a...)}
}

// readBody reads a bounded request body.
func readBody(w http.ResponseWriter, r *http.Request) ([]byte, error) {
	b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxBody))
	if err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			return nil, err
		}
		return nil, badRequest("read body: %v", err)
	}
	return b, nil
}

// decodeBody strictly decodes a JSON body; unknown fields are refused.
func decodeBody(w http.ResponseWriter, r *http.Request, v any) error {
	b, err := readBody(w, r)
	if err != nil {
		return err
	}
	if len(strings.TrimSpace(string(b))) == 0 {
		return badRequest("a JSON body is required")
	}
	if err := model.Decode(b, v); err != nil {
		return badRequest("invalid body: %v", err)
	}
	return nil
}
