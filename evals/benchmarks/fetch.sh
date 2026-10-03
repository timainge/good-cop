#!/usr/bin/env bash
# Benchmark data and the dcg comparator, pinned, into ~/.good-cop/cache/benchmarks (not vendored).
set -euo pipefail
D="${GOOD_COP_HOME:-$HOME/.good-cop}/cache/benchmarks"
mkdir -p "$D" && cd "$D"
get() { [ -d "$1" ] || git clone -q "$2" "$1"; git -C "$1" fetch -q --depth 1 origin "$3" 2>/dev/null || true; git -C "$1" checkout -q "$3"; }
get R-Judge https://github.com/Lordog/R-Judge 83ce301da3ad50dd8b397e772863f5411c3d3dc2
get RedCode https://github.com/AI-secure/RedCode c84b6db88fd8bd258e29f12e692ccfd4287a454d
if [ ! -x dcg/dcg ] && [ "$(uname -sm)" = "Darwin arm64" ]; then
  mkdir -p dcg && cd dcg
  B=https://github.com/Dicklesworthstone/destructive_command_guard/releases/download/v0.15.2
  curl -sSLO $B/dcg-aarch64-apple-darwin.tar.xz
  echo "7935eaa6f424c1061261a53609e7e6b3e0bb59d7432f167b4d573893e4fd009f  dcg-aarch64-apple-darwin.tar.xz" | shasum -a 256 -c -
  tar xf dcg-aarch64-apple-darwin.tar.xz
fi
echo "ready: $D"
