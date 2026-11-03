package worker

import "net/http"

func init() { http.HandleFunc("/test-only", nil) }
