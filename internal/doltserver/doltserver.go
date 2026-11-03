// Package doltserver supervises a `dolt sql-server` child process, or
// connects to an existing server, and hands out a *sql.DB for it.
package doltserver

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"time"

	_ "github.com/go-sql-driver/mysql" // registers the "mysql" driver
)

// Options configures Start.
type Options struct {
	// Bin is the dolt binary (default "dolt").
	Bin string
	// DataDir is the parent directory; the server stores data in DataDir/dolt.
	DataDir string
	// Port is the loopback port; 0 picks a free one.
	Port int
	// DSN connects to an existing server instead of starting a child.
	DSN string
	// Log receives the child's output (default: discarded).
	Log io.Writer
	// ReadyTimeout bounds the readiness wait (default 30s).
	ReadyTimeout time.Duration
}

// Server is a running (or connected) Dolt SQL server.
type Server struct {
	DB   *sql.DB
	DSN  string
	Port int

	cmd      *exec.Cmd
	exited   chan struct{}
	waitErr  error
	stopOnce sync.Once
}

// Start launches and waits for a dolt sql-server, or connects to opts.DSN.
func Start(ctx context.Context, opts Options) (*Server, error) {
	timeout := opts.ReadyTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	if opts.DSN != "" {
		db, err := sql.Open("mysql", opts.DSN)
		if err != nil {
			return nil, fmt.Errorf("dolt dsn: %w", err)
		}
		if err := waitReady(ctx, db, timeout, nil); err != nil {
			db.Close()
			return nil, err
		}
		return &Server{DB: db, DSN: opts.DSN}, nil
	}

	bin := opts.Bin
	if bin == "" {
		bin = "dolt"
	}
	if opts.DataDir == "" {
		return nil, errors.New("doltserver: a data dir is required")
	}
	dir := filepath.Join(opts.DataDir, "dolt")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create dolt data dir: %w", err)
	}
	port := opts.Port
	if port == 0 {
		p, err := FreePort()
		if err != nil {
			return nil, err
		}
		port = p
	}
	cmd := exec.Command(bin, "sql-server", "-H", "127.0.0.1", "-P", strconv.Itoa(port), "--data-dir", dir)
	cmd.Dir = dir
	out := opts.Log
	if out == nil {
		out = io.Discard
	}
	cmd.Stdout, cmd.Stderr = out, out
	// Own process group, so a terminal's Ctrl-C reaches mosaicd first and
	// mosaicd decides when the child stops.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start dolt sql-server: %w", err)
	}
	s := &Server{Port: port, cmd: cmd, exited: make(chan struct{})}
	go func() {
		s.waitErr = cmd.Wait()
		close(s.exited)
	}()
	s.DSN = fmt.Sprintf("root@tcp(127.0.0.1:%d)/?parseTime=true&multiStatements=false", port)
	db, err := sql.Open("mysql", s.DSN)
	if err != nil {
		s.Stop()
		return nil, err
	}
	s.DB = db
	if err := waitReady(ctx, db, timeout, s.exited); err != nil {
		s.Stop()
		return nil, err
	}
	return s, nil
}

func waitReady(ctx context.Context, db *sql.DB, timeout time.Duration, exited <-chan struct{}) error {
	deadline := time.Now().Add(timeout)
	var last error
	for {
		pctx, cancel := context.WithTimeout(ctx, 2*time.Second)
		last = db.PingContext(pctx)
		cancel()
		if last == nil {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("dolt sql-server not ready after %s: %w", timeout, last)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-exited:
			return errors.New("dolt sql-server exited before it was ready")
		case <-time.After(150 * time.Millisecond):
		}
	}
}

// Version reports the server's version() string.
func (s *Server) Version(ctx context.Context) string {
	var v string
	if err := s.DB.QueryRowContext(ctx, "SELECT dolt_version()").Scan(&v); err != nil {
		if err := s.DB.QueryRowContext(ctx, "SELECT version()").Scan(&v); err != nil {
			return "unknown"
		}
	}
	return v
}

// Stop closes the pool and stops the child: SIGTERM, then SIGKILL after 10s.
func (s *Server) Stop() error {
	var err error
	s.stopOnce.Do(func() {
		if s.DB != nil {
			s.DB.Close()
		}
		if s.cmd == nil || s.cmd.Process == nil {
			return
		}
		select {
		case <-s.exited:
			return
		default:
		}
		_ = s.cmd.Process.Signal(syscall.SIGTERM)
		select {
		case <-s.exited:
		case <-time.After(10 * time.Second):
			_ = s.cmd.Process.Kill()
			<-s.exited
			err = errors.New("dolt sql-server did not stop after SIGTERM; killed")
		}
	})
	return err
}

// Exited is closed when a supervised child exits (nil for a DSN connection).
func (s *Server) Exited() <-chan struct{} { return s.exited }

// Pid is the child's process id (0 for a DSN connection).
func (s *Server) Pid() int {
	if s.cmd == nil || s.cmd.Process == nil {
		return 0
	}
	return s.cmd.Process.Pid
}

// FreePort returns a free loopback TCP port.
func FreePort() (int, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, fmt.Errorf("find a free port: %w", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port, nil
}
