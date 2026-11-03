#!/usr/bin/env bash
# Install mosaic's prerequisites and build it.
#
#   scripts/install.sh [--go-install] [--prefix DIR] [--skip-build] [--skip-web]
#
# - Go and Node are required, but this script doesn't install them: it stops with a hint when
#   either is missing or too old.
# - Dolt (the ontology store behind mosaicd) is installed when missing: with Homebrew on macOS
#   when available, otherwise from the latest GitHub release into --prefix (default ~/.local/bin),
#   without sudo.
# - Then it builds bin/mosaic and bin/mosaicd, and installs the web UI's dependencies with pnpm
#   (enabled through corepack when pnpm itself is missing).
# - --go-install also installs mosaic and mosaicd into Go's bin folder ($GOBIN, else
#   $(go env GOPATH)/bin), so they run from anywhere when that folder is on your PATH.
set -euo pipefail

PREFIX="${HOME}/.local/bin"
GO_INSTALL=0
BUILD=1
WEB=1
while [ $# -gt 0 ]; do
  case "$1" in
    --go-install) GO_INSTALL=1; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --skip-build) BUILD=0; shift ;;
    --skip-web) WEB=0; shift ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GO_MIN="$(awk '$1 == "go" { print $2; exit }' "$ROOT/go.mod")"
NODE_MIN="20.9.0"   # Next.js 16

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# version_ge A B: true when version A >= version B (numeric, dot-separated).
version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]
}

# --- Go (required, not installed by this script) ---------------------------------------------
GO_FALLBACK="${GO_FALLBACK:-/usr/local/go/bin}"   # the official tarball's location
if ! command -v go >/dev/null 2>&1 && [ -x "$GO_FALLBACK/go" ]; then
  export PATH="$GO_FALLBACK:$PATH"
fi
command -v go >/dev/null 2>&1 || fail "Go ${GO_MIN} or newer is required: install it from https://go.dev/dl/ and re-run."
GO_VER="$(go env GOVERSION | sed 's/^go//')"
version_ge "$GO_VER" "$GO_MIN" || fail "Go ${GO_MIN} or newer is required (found ${GO_VER}): see https://go.dev/dl/."
say "go ${GO_VER}"

# --- Node (required, not installed by this script) -------------------------------------------
command -v node >/dev/null 2>&1 || fail "Node ${NODE_MIN} or newer is required: install it from https://nodejs.org/ and re-run."
NODE_VER="$(node --version | sed 's/^v//')"
version_ge "$NODE_VER" "$NODE_MIN" || fail "Node ${NODE_MIN} or newer is required (found ${NODE_VER}): see https://nodejs.org/."
say "node ${NODE_VER}"

# --- Dolt (installed when missing) -----------------------------------------------------------
install_dolt() {
  local os arch
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) fail "can't install dolt on $(uname -s): see https://docs.dolthub.com/introduction/installation" ;;
  esac
  if [ "$os" = darwin ] && command -v brew >/dev/null 2>&1; then
    say "installing dolt with Homebrew"
    brew install dolt
    return
  fi
  case "$(uname -m)" in
    x86_64|amd64) arch=amd64 ;;
    arm64|aarch64) arch=arm64 ;;
    *) fail "can't install dolt on $(uname -m): see https://docs.dolthub.com/introduction/installation" ;;
  esac
  command -v curl >/dev/null 2>&1 || fail "curl is needed to download dolt"
  local url="https://github.com/dolthub/dolt/releases/latest/download/dolt-${os}-${arch}.tar.gz"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  say "downloading dolt (${os}-${arch}) into ${PREFIX}"
  curl -fsSL "$url" -o "$tmp/dolt.tar.gz" || fail "download failed: $url"
  tar -xzf "$tmp/dolt.tar.gz" -C "$tmp"
  mkdir -p "$PREFIX"
  install -m 0755 "$tmp/dolt-${os}-${arch}/bin/dolt" "$PREFIX/dolt"
  case ":$PATH:" in
    *":$PREFIX:"*) ;;
    *) export PATH="$PREFIX:$PATH"
       printf '\033[33mnote:\033[0m %s is not on your PATH; add it to your shell profile:\n  export PATH="%s:$PATH"\n' "$PREFIX" "$PREFIX" ;;
  esac
}

if command -v dolt >/dev/null 2>&1; then
  say "$(dolt version | head -n1) (already installed)"
else
  install_dolt
  command -v dolt >/dev/null 2>&1 || fail "dolt was installed but isn't on PATH"
  say "$(dolt version | head -n1) installed"
fi

# --- Build -----------------------------------------------------------------------------------
if [ "$BUILD" = 1 ]; then
  say "building bin/mosaic and bin/mosaicd"
  mkdir -p "$ROOT/bin"
  (cd "$ROOT" && GOFLAGS=-mod=readonly go build -o bin/mosaic ./cmd/mosaic && GOFLAGS=-mod=readonly go build -o bin/mosaicd ./cmd/mosaicd)
fi

if [ "$GO_INSTALL" = 1 ]; then
  GO_BIN="$(go env GOBIN)"
  [ -n "$GO_BIN" ] || GO_BIN="$(go env GOPATH)/bin"
  say "installing mosaic and mosaicd into ${GO_BIN}"
  (cd "$ROOT" && GOFLAGS=-mod=readonly go install ./cmd/mosaic ./cmd/mosaicd)
  case ":$PATH:" in
    *":$GO_BIN:"*) ;;
    *) printf '\033[33mnote:\033[0m %s is not on your PATH; add it to your shell profile:\n  export PATH="%s:$PATH"\n' "$GO_BIN" "$GO_BIN" ;;
  esac
fi

if [ "$WEB" = 1 ]; then
  if ! command -v pnpm >/dev/null 2>&1; then
    command -v corepack >/dev/null 2>&1 || fail "pnpm is missing and corepack isn't available: install pnpm (https://pnpm.io/installation)"
    say "enabling pnpm through corepack"
    corepack enable pnpm 2>/dev/null || corepack enable --install-directory "$PREFIX" pnpm
  fi
  say "installing the web UI's dependencies"
  (cd "$ROOT/web" && pnpm install --frozen-lockfile)
fi

say "done. Start the daemon with ./bin/mosaicd, then the UI with: cd web && pnpm dev"
