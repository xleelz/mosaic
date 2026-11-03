package main

import "github.com/xleelz/mosaic/internal/sim"

// The engine output names of DESIGN §13.1 item 9 that the quality checks
// read, kept in one place.

// executedOf is the sorted set of behavior step paths a run executed.
func executedOf(s *sim.Summary) []string { return s.Executed }

// mockedCalls is the number of calls a run answered from a mock.
func mockedCalls(s *sim.Summary) int { return s.Mocks }
