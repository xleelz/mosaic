// Command mosaicd serves the mosaic HTTP API over a Dolt store (docs/DESIGN.md §8).
//
//	mosaicd [--addr 127.0.0.1:7878] [--data-dir ~/.mosaic] [--dolt-bin dolt] [--dolt-port 0]
//	        [--dolt-dsn DSN] [--token T] [--cors-origin http://localhost:3000]
//	        [--source-dir DIR] [--no-self-update]
//
// After a self-update (POST /v1/system/update) under scripts/serve.sh
// (MOSAIC_SUPERVISED=1), it shuts down gracefully and exits with
// selfupdate.ExitRestart (75) so that the supervisor rebuilds and restarts it.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/go-sql-driver/mysql"

	"github.com/xleelz/mosaic/internal/api"
	"github.com/xleelz/mosaic/internal/doltserver"
	"github.com/xleelz/mosaic/internal/selfupdate"
	"github.com/xleelz/mosaic/internal/store"
)

// Version is mosaicd's version.
const Version = "0.1.0"

// origins collects --cors-origin values, repeatable or comma-separated.
type origins []string

func (o *origins) String() string { return strings.Join(*o, ",") }
func (o *origins) Set(v string) error {
	for _, s := range strings.Split(v, ",") {
		if s = strings.TrimSpace(s); s != "" {
			*o = append(*o, s)
		}
	}
	return nil
}

// errRestart ends run after a supervised self-update: exit with
// selfupdate.ExitRestart.
var errRestart = errors.New("restart requested")

func main() {
	if err := run(os.Args[1:]); err != nil {
		if errors.Is(err, errRestart) {
			log.Printf("exiting with code %d for the supervisor to rebuild and restart mosaicd", selfupdate.ExitRestart)
			os.Exit(selfupdate.ExitRestart)
		}
		log.Printf("mosaicd: %v", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("mosaicd", flag.ContinueOnError)
	addr := fs.String("addr", "127.0.0.1:7878", "HTTP listen address (loopback)")
	dataDir := fs.String("data-dir", "~/.mosaic", "data directory; Dolt data lives in <data-dir>/dolt")
	doltBin := fs.String("dolt-bin", "dolt", "dolt binary")
	doltPort := fs.Int("dolt-port", 0, "port for the supervised dolt sql-server (0 picks a free one)")
	doltDSN := fs.String("dolt-dsn", "", "connect to this existing Dolt server instead of starting one")
	token := fs.String("token", os.Getenv("MOSAIC_TOKEN"), "bearer token required on every request (default $MOSAIC_TOKEN)")
	var cors origins
	fs.Var(&cors, "cors-origin", "allowed CORS origin, repeatable or comma-separated (default http://localhost:3000,http://127.0.0.1:3000)")
	sourceDir := fs.String("source-dir", "", "the mosaic checkout mosaicd was built from, for GET /v1/system/version and self-update (none: updates unavailable)")
	noSelfUpdate := fs.Bool("no-self-update", false, "refuse POST /v1/system/update")
	version := fs.Bool("version", false, "print the version and exit")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		os.Exit(2)
	}
	if *version {
		fmt.Println("mosaicd", Version)
		return nil
	}

	dir, err := expandHome(*dataDir)
	if err != nil {
		return err
	}
	if host, _, err := net.SplitHostPort(*addr); err == nil {
		if ip := net.ParseIP(host); host != "localhost" && (ip == nil || !ip.IsLoopback()) {
			log.Printf("warning: %s is not a loopback address; anyone who can reach it can use the API", *addr)
		}
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	opts := doltserver.Options{Bin: *doltBin, DataDir: dir, Port: *doltPort}
	if *doltDSN != "" {
		dsn, err := normalizeDSN(*doltDSN)
		if err != nil {
			return err
		}
		opts.DSN = dsn
	} else {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
		f, err := os.OpenFile(filepath.Join(dir, "dolt-server.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		defer f.Close()
		opts.Log = f
	}
	dolt, err := doltserver.Start(ctx, opts)
	if err != nil {
		return err
	}
	defer func() {
		if err := dolt.Stop(); err != nil {
			log.Printf("stop dolt: %v", err)
		} else if *doltDSN == "" {
			log.Printf("dolt sql-server stopped")
		}
	}()
	if *doltDSN == "" {
		log.Printf("dolt sql-server on 127.0.0.1:%d (data %s)", dolt.Port, filepath.Join(dir, "dolt"))
	} else {
		log.Printf("connected to dolt at %s", redactDSN(opts.DSN))
	}

	st, err := store.Open(ctx, dolt.DB)
	if err != nil {
		return err
	}
	src := *sourceDir
	if src != "" {
		if src, err = expandHome(src); err != nil {
			return err
		}
	}
	supervised := os.Getenv("MOSAIC_SUPERVISED") == "1"
	updater := selfupdate.New(selfupdate.Options{SourceDir: src, Version: Version, Disabled: *noSelfUpdate, Supervised: supervised})
	restart := make(chan struct{}, 1)
	handler := api.New(api.Config{
		Store: st, Version: Version, Token: *token, Origins: []string(cors),
		Updater: updater,
		OnRestart: func() {
			select {
			case restart <- struct{}{}:
			default:
			}
		},
		DoltVersion: func(ctx context.Context) (string, error) {
			var v string
			err := dolt.DB.QueryRowContext(ctx, "SELECT dolt_version()").Scan(&v)
			return v, err
		},
	})
	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		return err
	}
	srv := &http.Server{Handler: handler, ReadHeaderTimeout: 10 * time.Second, ErrorLog: log.New(io.Discard, "", 0)}
	served := make(chan error, 1)
	go func() { served <- srv.Serve(ln) }()
	auth := "off"
	if *token != "" {
		auth = "bearer token"
	}
	log.Printf("mosaicd %s listening on http://%s (auth %s)", Version, ln.Addr(), auth)
	switch {
	case src == "":
		log.Printf("self-update unavailable: no --source-dir")
	case *noSelfUpdate:
		log.Printf("self-update disabled; source %s at %s", src, updater.Commit())
	default:
		log.Printf("self-update from %s at %s (supervised: %v)", src, updater.Commit(), supervised)
	}

	var exited <-chan struct{}
	if *doltDSN == "" {
		exited = dolt.Exited()
	}
	var result error
	select {
	case <-ctx.Done():
		log.Printf("shutting down")
	case <-restart:
		log.Printf("self-update applied; shutting down to restart")
		result = errRestart
	case err := <-served:
		return fmt.Errorf("http server: %w", err)
	case <-exited:
		_ = srv.Close()
		return errors.New("dolt sql-server exited unexpectedly")
	}
	sctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(sctx); err != nil {
		log.Printf("http shutdown: %v", err)
		_ = srv.Close()
	}
	return result
}

func expandHome(p string) (string, error) {
	if p == "~" || strings.HasPrefix(p, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, strings.TrimPrefix(p, "~")), nil
	}
	return filepath.Abs(p)
}

// normalizeDSN makes sure times parse and statements stay single.
func normalizeDSN(dsn string) (string, error) {
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		return "", fmt.Errorf("invalid --dolt-dsn: %w", err)
	}
	cfg.ParseTime = true
	cfg.MultiStatements = false
	return cfg.FormatDSN(), nil
}

func redactDSN(dsn string) string {
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		return "(dsn)"
	}
	if cfg.Passwd != "" {
		cfg.Passwd = "***"
	}
	return cfg.FormatDSN()
}
