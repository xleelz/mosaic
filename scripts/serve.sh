#!/usr/bin/env bash
# Run mosaicd and the web UI together from this checkout, and restart both after a self-update.
#
#   scripts/serve.sh [--data-dir DIR] [--addr HOST:PORT] [--web-port N] [--dev] [-- MOSAICD-ARGS...]
#
# - It builds bin/mosaic and bin/mosaicd, starts mosaicd with --source-dir <this checkout>, then
#   the web UI with MOSAIC_SERVER pointing at it, on 127.0.0.1:--web-port.
# - Defaults: --data-dir ~/.mosaic, --addr 127.0.0.1:7878, --web-port 3000. Production mode (the
#   default) runs pnpm build once, then pnpm start; --dev runs pnpm dev instead.
# - Arguments after -- go to mosaicd (for example --token T or --no-self-update). MOSAIC_TOKEN, when
#   set, reaches both mosaicd and the UI's proxy.
# - When mosaicd exits with code 75 after an update from the UI or `mosaic update`, it rebuilds the
#   binaries, runs pnpm install --frozen-lockfile if the lockfile changed, runs pnpm build in
#   production mode, and restarts both. Any other exit, or Ctrl-C, stops both.
set -euo pipefail

readonly EXIT_RESTART=75   # EX_TEMPFAIL: mosaicd asks to be rebuilt and restarted (selfupdate.ExitRestart)
readonly STOP_GRACE=15     # seconds to wait for a process group before SIGKILL

DATA_DIR="${HOME}/.mosaic"
ADDR="127.0.0.1:7878"
WEB_PORT=3000
DEV=0
MOSAICD_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --addr) ADDR="$2"; shift 2 ;;
    --web-port) WEB_PORT="$2"; shift 2 ;;
    --dev) DEV=1; shift ;;
    --) shift; MOSAICD_ARGS=("$@"); break ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "serve: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "$WEB_PORT" in ''|*[!0-9]*) fail "--web-port must be a number, got ${WEB_PORT}" ;; esac
case "$ADDR" in *:*) ;; *) fail "--addr must be HOST:PORT, got ${ADDR}" ;; esac

GO_FALLBACK="${GO_FALLBACK:-/usr/local/go/bin}"
if ! command -v go >/dev/null 2>&1 && [ -x "$GO_FALLBACK/go" ]; then
  export PATH="$GO_FALLBACK:$PATH"
fi
command -v go >/dev/null 2>&1 || fail "go is required (see scripts/install.sh)"
command -v pnpm >/dev/null 2>&1 || fail "pnpm is required (see scripts/install.sh)"
command -v git >/dev/null 2>&1 || fail "git is required"

# Each background job gets its own process group, so a whole tree (pnpm, next and its workers)
# stops together.
set -m

MOSAICD_PID=""
WEB_PID=""
LOCK_SUM=""

# prefix TAG: copy stdin to stdout, line by line, behind TAG. It ignores signals and ends when the
# process writing to it does, so a stopping process's last lines still show.
prefix() {
  local line
  trap '' INT TERM HUP
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s %s\n' "$1" "$line"
  done
}

lock_sum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$ROOT/web/pnpm-lock.yaml" | cut -d' ' -f1
  else
    shasum -a 256 "$ROOT/web/pnpm-lock.yaml" | cut -d' ' -f1
  fi
}

build_go() {
  say "building bin/mosaic and bin/mosaicd at $(git -C "$ROOT" rev-parse --short HEAD)"
  mkdir -p "$ROOT/bin"
  (cd "$ROOT" && GOFLAGS=-mod=readonly go build -o bin/mosaic ./cmd/mosaic && GOFLAGS=-mod=readonly go build -o bin/mosaicd ./cmd/mosaicd)
}

install_web() {
  say "installing the web UI's dependencies"
  (cd "$ROOT/web" && pnpm install --frozen-lockfile)
  LOCK_SUM="$(lock_sum)"
}

build_web() {
  [ "$DEV" = 1 ] && return 0
  say "building the web UI"
  (cd "$ROOT/web" && pnpm build) 2>&1 | prefix "[web]"
}

start_mosaicd() {
  say "starting mosaicd on ${ADDR} (data ${DATA_DIR})"
  MOSAIC_SUPERVISED=1 "$ROOT/bin/mosaicd" --addr "$ADDR" --data-dir "$DATA_DIR" --source-dir "$ROOT" \
    --cors-origin "http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}" ${MOSAICD_ARGS[@]+"${MOSAICD_ARGS[@]}"} \
    > >(prefix "[mosaicd]") 2>&1 < /dev/null &
  MOSAICD_PID=$!
}

start_web() {
  local cmd=start
  [ "$DEV" = 1 ] && cmd=dev
  say "starting the web UI (pnpm ${cmd}) on http://127.0.0.1:${WEB_PORT}"
  (cd "$ROOT/web" && MOSAIC_SERVER="http://${ADDR}" exec pnpm "$cmd" --hostname 127.0.0.1 --port "$WEB_PORT") \
    > >(prefix "[web]") 2>&1 < /dev/null &
  WEB_PID=$!
}

# stop NAME PID [group]: SIGTERM the job (its whole process group with "group"), wait up to
# STOP_GRACE seconds, then SIGKILL whatever is left of the group.
stop() {
  local name="$1" pid="$2" scope="${3:-}" i
  [ -n "$pid" ] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    say "stopping ${name}"
    if [ "$scope" = group ]; then
      kill -TERM -- "-$pid" 2>/dev/null || true
    else
      kill -TERM "$pid" 2>/dev/null || true
    fi
    for ((i = 0; i < STOP_GRACE * 10; i++)); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  wait "$pid" 2>/dev/null || true
  # The rest of the group (its log prefixer, stray children) gets a moment, then SIGKILL.
  for ((i = 0; i < 20; i++)); do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL -- "-$pid" 2>/dev/null || true
}

stop_all() {
  # mosaicd stops its own dolt sql-server (in a group of its own), so only mosaicd is signalled.
  stop mosaicd "$MOSAICD_PID"; MOSAICD_PID=""
  stop "the web UI" "$WEB_PID" group; WEB_PID=""
}

on_signal() {
  trap - INT TERM
  printf '\n'
  stop_all
  say "stopped"
  exit 130
}
trap on_signal INT TERM
trap stop_all EXIT

# --- First start -----------------------------------------------------------------------------
build_go
install_web
build_web || fail "pnpm build failed"

while :; do
  start_mosaicd
  start_web

  # Wait for either process to exit. (bash reaps finished jobs, so kill -0 fails once one ends.)
  while kill -0 "$MOSAICD_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
    sleep 0.5
  done

  if kill -0 "$MOSAICD_PID" 2>/dev/null; then
    status=0
    wait "$WEB_PID" || status=$?
    WEB_PID=""
    say "the web UI exited (code ${status}); stopping mosaicd"
    stop_all
    exit 1
  fi

  status=0
  wait "$MOSAICD_PID" || status=$?
  MOSAICD_PID=""
  if [ "$status" != "$EXIT_RESTART" ]; then
    say "mosaicd exited (code ${status}); stopping the web UI"
    stop_all
    exit "$status"
  fi

  say "mosaicd updated the checkout to $(git -C "$ROOT" rev-parse --short HEAD); rebuilding and restarting"
  build_go || fail "go build failed after the update; fix it and start scripts/serve.sh again"
  # The UI stops before its dependencies or build output change under it.
  stop "the web UI" "$WEB_PID" group; WEB_PID=""
  if [ "$(lock_sum)" != "$LOCK_SUM" ]; then
    install_web
  fi
  build_web || fail "pnpm build failed after the update; fix it and start scripts/serve.sh again"
done
