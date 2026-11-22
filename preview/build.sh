#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Compile effect usermods with the preview shim to WebAssembly.
#   preview/build.sh OUT_DIR USERMOD_DIR [USERMOD_DIR ...]
# Needs Emscripten (em++) on the path.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$1; shift
mkdir -p "$out"
srcs=()
for d in "$@"; do srcs+=("$d"/*.cpp); done
em++ -std=c++17 -O2 -I"$here/shim" "$here/shim/shim.cpp" "${srcs[@]}" \
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sENVIRONMENT=web,node -sALLOW_MEMORY_GROWTH=1 \
  -sEXPORTED_FUNCTIONS=_preview_setup,_preview_effect_count,_preview_effect_name,_preview_effect_metadata,_preview_select,_preview_set,_preview_length,_preview_frame \
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,HEAPU32 \
  -o "$out/preview.mjs"
echo "built $out/preview.mjs and preview.wasm"
