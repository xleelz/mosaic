package api

import (
	"net/http"

	wire "github.com/xleelz/mosaic/pkg/api"
)

// ---- evidence and recorded test reports ----

func (s *Server) getEvidence(w http.ResponseWriter, r *http.Request) {
	ev, err := s.store.Evidence(r.Context(), r.PathValue("id"), r.URL.Query().Get("rev"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, ev)
}

func (s *Server) putEvidence(w http.ResponseWriter, r *http.Request) {
	var in wire.Evidence
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	ev, err := s.store.PutEvidence(r.Context(), r.PathValue("id"), r.URL.Query().Get("rev"), in)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, ev)
}

func (s *Server) getTestResults(w http.ResponseWriter, r *http.Request) {
	id, rv, err := s.rev(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	rep, err := s.store.TestResults(r.Context(), id, rv)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, rep)
}
