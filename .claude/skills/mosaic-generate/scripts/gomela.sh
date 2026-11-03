#!/bin/sh
# gomela.sh runs Gomela (Go to Promela, model-checked with SPIN) on a Go
# package, as an optional, independent concurrency oracle for components
# refined to the runtime level (DESIGN §15.5; docs/PIPELINE.md, "Hierarchical
# runs"). It never fails a pipeline because the tools are missing: without
# gomela or spin it explains how to install them and exits 0, unless
# GOMELA_REQUIRED=1 is set (then it exits 2).
#
#   gomela.sh <go-package-dir> [<out-dir>] [-- <extra gomela args>]
#
# The package directory may be in a read-only checkout: Gomela runs from
# <out-dir> (default: a new directory under ${TMPDIR:-/tmp}), where it writes
# its Promela models and verification results. The exit status is gomela's.
set -eu

usage() {
	echo "usage: gomela.sh <go-package-dir> [<out-dir>] [-- <extra gomela args>]" >&2
	exit 2
}

missing() {
	cat >&2 <<'EOF'
gomela.sh: Gomela or SPIN is not installed; the Gomela oracle is skipped.
To install them (both are optional; mosaic never needs them):
  - SPIN:   apt-get install spin   (or build it from https://github.com/nimble-code/Spin)
  - Gomela: go install github.com/nicolasdilley/gomela@latest
            (it lands in $(go env GOPATH)/bin; put that on PATH)
Then rerun:  gomela.sh <go-package-dir> [<out-dir>]
EOF
	if [ "${GOMELA_REQUIRED:-0}" = 1 ]; then
		exit 2
	fi
	exit 0
}

[ $# -ge 1 ] || usage
pkg=$1
shift
out=""
if [ $# -ge 1 ] && [ "$1" != "--" ]; then
	out=$1
	shift
fi
if [ $# -ge 1 ] && [ "$1" = "--" ]; then
	shift
fi
[ -d "$pkg" ] || { echo "gomela.sh: $pkg is not a directory" >&2; exit 2; }
pkg=$(cd "$pkg" && pwd)

# Gomela may be installed under GOPATH/bin without being on PATH.
if ! command -v gomela >/dev/null 2>&1; then
	gobin=""
	if command -v go >/dev/null 2>&1; then
		gobin=$(go env GOPATH 2>/dev/null)/bin
	elif [ -x /usr/local/go/bin/go ]; then
		gobin=$(/usr/local/go/bin/go env GOPATH 2>/dev/null)/bin
	fi
	[ -n "$gobin" ] && PATH="$gobin:$PATH"
fi
command -v gomela >/dev/null 2>&1 || missing
command -v spin >/dev/null 2>&1 || missing

if [ -z "$out" ]; then
	out=$(mktemp -d "${TMPDIR:-/tmp}/gomela.XXXXXX")
fi
mkdir -p "$out"
echo "gomela.sh: modeling $pkg into $out" >&2
cd "$out"
# "fs" models every Go file under the directory and verifies each model with
# SPIN; the results (models, and a CSV of the verdicts per function) stay in
# the output directory.
exec gomela fs "$pkg" "$@"
