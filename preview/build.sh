#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Compile effect usermods with the preview shim to WebAssembly.
#   preview/build.sh OUT_DIR USERMOD_DIR [USERMOD_DIR ...]
#   WLED_SRC=<WLED checkout> preview/build.sh ...   exact colours: WLED's own colour and palette
#                                                   code from that checkout (see wled_colors.py)
# Needs Emscripten (em++) on the path, and python3 for exact colours.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$1; shift
mkdir -p "$out"
srcs=()
for d in "$@"; do srcs+=("$d"/*.cpp); done
flags=(-I"$here/shim")
if [ -n "${WLED_SRC:-}" ]; then
  gen="$out/wled-colors"
  rm -rf "$gen"
  python3 "$here/wled_colors.py" "$WLED_SRC" "$gen"
  flags=(-DPREVIEW_WLED_COLORS -Wno-unknown-attributes -I"$here/shim" -I"$gen")   # fastled_slim uses GCC's optimize attribute
  srcs+=("$gen/wled_colors.cpp" "$gen/palettes.cpp" "$gen/src/dependencies/fastled_slim/fastled_slim.cpp")
fi
em++ -std=c++17 -O2 "${flags[@]}" "$here/shim/shim.cpp" "${srcs[@]}" \
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sENVIRONMENT=web,node -sALLOW_MEMORY_GROWTH=1 \
  -sEXPORTED_FUNCTIONS=_preview_setup,_preview_effect_count,_preview_effect_name,_preview_effect_metadata,_preview_select,_preview_set,_preview_length,_preview_frame,_preview_audio,_preview_palette_names \
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,HEAPU32 \
  -o "$out/preview.mjs"
echo "built $out/preview.mjs and preview.wasm${WLED_SRC:+ (exact colours from $WLED_SRC)}"
