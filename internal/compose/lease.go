package compose

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

// Role caps across processes (DESIGN §16.7). Every `mosaic compose` process
// using a run store shares its role caps through a lease file next to the
// store root, <runs>/../leases.json, guarded by an flock on
// <runs>/../leases.lock. A lease records the holder's pid and process start
// time; a lease whose process is gone (or whose pid now belongs to another
// process) is stale and is reclaimed by the next process that reads the file.

// LeaseFile is the lease file's name next to the run store root.
const LeaseFile = "leases.json"

// Lease is one role-cap slot held by a turn.
type Lease struct {
	ID       string    `json:"id"`
	Key      string    `json:"key"` // <cap_scope>/<scope id>/<role>
	Cap      int       `json:"cap"`
	PID      int       `json:"pid"`
	Start    string    `json:"start,omitempty"` // the holder's process start time (Linux: /proc start ticks)
	Task     string    `json:"task,omitempty"`
	Stage    string    `json:"stage,omitempty"`
	Acquired time.Time `json:"acquired"`
}

type leaseDoc struct {
	Leases []*Lease `json:"leases"`
}

// leasePoll bounds how often a waiting turn rereads the lease file.
var leasePoll = struct{ min, max time.Duration }{10 * time.Millisecond, 250 * time.Millisecond}

var leaseSeq atomic.Int64

// LeasePath is the lease file of the run store rooted at root.
func LeasePath(root string) string {
	return filepath.Join(filepath.Dir(filepath.Clean(root)), LeaseFile)
}

// acquireLease waits until fewer than cap live leases hold key, then records
// one for this process. It returns the release function.
func acquireLease(ctx context.Context, path, key string, cap int, task, stage string) (func(), error) {
	self := &Lease{
		ID:  fmt.Sprintf("%d-%d-%d", os.Getpid(), time.Now().UnixNano(), leaseSeq.Add(1)),
		Key: key, Cap: cap, PID: os.Getpid(), Start: processStart(os.Getpid()), Task: task, Stage: stage,
	}
	wait := leasePoll.min
	for {
		got := false
		err := withLeases(path, func(doc *leaseDoc) bool {
			n := 0
			for _, l := range doc.Leases {
				if l.Key == key {
					n++
				}
			}
			if n >= cap {
				return false
			}
			self.Acquired = time.Now().UTC()
			doc.Leases = append(doc.Leases, self)
			got = true
			return true
		})
		if err != nil {
			return nil, fmt.Errorf("lease %s: %w", key, err)
		}
		if got {
			return func() {
				_ = withLeases(path, func(doc *leaseDoc) bool {
					for i, l := range doc.Leases {
						if l.ID == self.ID {
							doc.Leases = append(doc.Leases[:i], doc.Leases[i+1:]...)
							return true
						}
					}
					return false
				})
			}, nil
		}
		t := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			t.Stop()
			return nil, ctx.Err()
		case <-t.C:
		}
		if wait *= 2; wait > leasePoll.max {
			wait = leasePoll.max
		}
	}
}

// withLeases runs fn over the lease file's live leases under an exclusive
// flock, and writes the file back when fn reports a change or stale leases
// were dropped.
func withLeases(path string, fn func(doc *leaseDoc) bool) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	lock, err := os.OpenFile(strings.TrimSuffix(path, ".json")+".lock", os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return err
	}
	defer lock.Close()
	for {
		err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX)
		if !errors.Is(err, syscall.EINTR) {
			break
		}
	}
	if err != nil {
		return err
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)

	var doc leaseDoc
	data, err := os.ReadFile(path)
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return err
	case len(strings.TrimSpace(string(data))) > 0:
		if err := json.Unmarshal(data, &doc); err != nil {
			// A corrupt file holds no lease we can honor; start over.
			doc = leaseDoc{}
		}
	}
	live := doc.Leases[:0]
	for _, l := range doc.Leases {
		if l != nil && leaseAlive(l) {
			live = append(live, l)
		}
	}
	reclaimed := len(live) != len(doc.Leases)
	doc.Leases = live
	if !fn(&doc) && !reclaimed {
		return nil
	}
	if doc.Leases == nil {
		doc.Leases = []*Lease{}
	}
	out, err := json.MarshalIndent(&doc, "", "  ")
	if err != nil {
		return err
	}
	return writeAtomic(path, append(out, '\n'))
}

// leaseAlive reports whether a lease's holder still runs: its pid exists
// and, when both are known, has the recorded start time.
func leaseAlive(l *Lease) bool {
	if l.PID <= 0 {
		return false
	}
	if err := syscall.Kill(l.PID, 0); err != nil && !errors.Is(err, syscall.EPERM) {
		return false
	}
	if l.Start != "" {
		if now := processStart(l.PID); now != "" && now != l.Start {
			return false // the pid was reused
		}
	}
	return true
}

// processStart is a process's start time as /proc reports it (clock ticks
// since boot, field 22 of /proc/<pid>/stat), or "" where /proc is absent.
func processStart(pid int) string {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return ""
	}
	// The command name (field 2) may hold spaces; fields resume after ')'.
	s := string(data)
	i := strings.LastIndexByte(s, ')')
	if i < 0 {
		return ""
	}
	f := strings.Fields(s[i+1:])
	if len(f) < 20 { // f[0] is field 3 (state); field 22 is f[19]
		return ""
	}
	return f[19]
}
