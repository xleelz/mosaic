package mocks

import "net/http"

func init() { http.HandleFunc("/mock-only", nil) }
