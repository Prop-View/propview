#!/usr/bin/env bash
# Compiles csrc/resampler.c into a shared library for the current platform.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

case "$(uname -s)" in
  Darwin) out="libresampler.dylib" ;;
  *)      out="libresampler.so" ;;
esac

cc -shared -fPIC -O2 -Wall -o "$out" csrc/resampler.c
echo "Built $out"
