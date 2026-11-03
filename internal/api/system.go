package api

// The running build and self-update (docs/DESIGN.md §6, §8): GET
// /v1/system/version and POST /v1/system/update, backed by
// internal/selfupdate.

import (
	"errors"
	"net"
	"net/http"
	"strings"

	"github.com/xleelz/mosaic/internal/selfupdate"
)

func (s *Server) systemRoutes(m *http.ServeMux) {
	m.HandleFunc("GET /v1/system/version", s.systemVersion)
	m.HandleFunc("POST /v1/system/update", s.systemUpdate)
}

func (s *Server) systemVersion(w http.ResponseWriter, r *http.Request) {
	refresh := r.URL.Query().Get("refresh")
	writeJSON(w, http.StatusOK, s.updater.Status(r.Context(), refresh == "1" || refresh == "true"))
}

func (s *Server) systemUpdate(w http.ResponseWriter, r *http.Request) {
	// The bearer token, when configured, was checked by s.auth.
	if !isLoopback(r.RemoteAddr) {
		writeError(w, http.StatusForbidden, "forbidden", "updates are only accepted from a loopback address", nil)
		return
	}
	// A browser page on another site could post to the UI's proxy, which
	// reaches mosaicd from loopback: only the allowed origins may update.
	if o := strings.TrimRight(r.Header.Get("Origin"), "/"); o != "" && !s.anyOrig && !s.origins[o] {
		writeError(w, http.StatusForbidden, "forbidden", "updates are not accepted from origin "+o+" (add it with mosaicd --cors-origin)", nil)
		return
	}
	res, err := s.updater.Update(r.Context())
	if err != nil {
		var refused *selfupdate.Refused
		if errors.As(err, &refused) {
			writeError(w, http.StatusConflict, "conflict", refused.Reason, nil)
			return
		}
		s.cfg.Logger.Printf("self-update failed: %v", err)
		writeError(w, http.StatusInternalServerError, "internal", err.Error(), nil)
		return
	}
	s.cfg.Logger.Printf("self-update: %s -> %s (restarting: %v)", res.From, res.UpdatedTo, res.Restarting)
	writeJSON(w, http.StatusOK, res)
	if res.Restarting && s.cfg.OnRestart != nil {
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		s.cfg.OnRestart()
	}
}

func isLoopback(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
