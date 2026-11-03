package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/gorilla/mux"
)

func Routes(mux0 *http.ServeMux, r chi.Router, g *mux.Router) {
	mux0.HandleFunc("GET /healthz", healthz)
	mux0.Handle("/v1/raw/{path...}", nil)
	r.Route("/v1/orgs", func(r chi.Router) {
		r.Post("/{orgId}/vms", createVM)
	})
	g.HandleFunc("/v1/legacy", healthz).Methods("PUT")
	cache := map[string]string{}
	_ = cache
}

func healthz(w http.ResponseWriter, r *http.Request)  {}
func createVM(w http.ResponseWriter, r *http.Request) {}
