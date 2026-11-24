#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Build a virtual WLED: WLED's own effect engine from a checkout, compiled to WebAssembly.
#   virtual/build.sh OUT_DIR WLED_CHECKOUT [USERMOD_DIR ...]
# Environment:
#   VIRTUAL_FLAGS   the firmware's own -D flags for the engine (from its compile command);
#                   default: -DUSERMOD_AUDIOREACTIVE
#   SANITIZE=1      build with AddressSanitizer (memory errors stop the run with a report)
# Needs Emscripten (em++) and python3. Writes OUT_DIR/virtual.mjs and virtual.wasm.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(mkdir -p "$1" && cd "$1" && pwd); shift
wled=$1; shift
gen="$out/wled-src"
rm -rf "$gen"
python3 "$here/virtual_wled.py" "$wled" "$gen"
# ours next to the engine, so every "wled.h" (the engine's and the glue's) is the same file
cp "$here/wled.h" "$here/glue.cpp" "$here/api.cpp" "$gen/"
flags=(-std=gnu++17 -O2 -w -D__time_t_defined -I"$here/stub" -I"$gen")   # the libc has time_t (TimeLib)
read -r -a extra <<< "${VIRTUAL_FLAGS:--DUSERMOD_AUDIOREACTIVE}"
flags+=("${extra[@]}")
link=()
if [ "${DEBUG:-}" = 1 ]; then flags+=(-g); link+=(-g); fi
if [ "${SANITIZE:-}" = 1 ]; then flags+=(-fsanitize=address -fsanitize-recover=address -g); link+=(-fsanitize=address -fsanitize-recover=address -g -sINITIAL_MEMORY=268435456); fi
srcs=("$gen"/FX.cpp "$gen"/FX_fcn.cpp "$gen"/FX_2Dfcn.cpp "$gen"/FXparticleSystem.cpp "$gen"/colors.cpp "$gen"/palettes.cpp
      "$gen"/wled_math.cpp "$gen"/util_extract.cpp "$gen"/src/dependencies/fastled_slim/fastled_slim.cpp
      "$gen"/src/dependencies/time/Time.cpp "$gen"/src/dependencies/time/DateStrings.cpp "$gen/glue.cpp" "$gen/api.cpp")
for d in "$@"; do srcs+=("$d"/*.cpp); done
objs=()
mkdir -p "$out/obj"
for s in "${srcs[@]}"; do
  o="$out/obj/$(echo "$s" | md5sum | cut -c1-8)-$(basename "$s" .cpp).o"
  em++ "${flags[@]}" -c "$s" -o "$o"
  objs+=("$o")
done
em++ "${objs[@]}" -O2 "${link[@]}" \
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sENVIRONMENT=web,node -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=1048576 \
  -sERROR_ON_UNDEFINED_SYMBOLS=1 \
  -sEXPORTED_FUNCTIONS=_virtual_boot,_virtual_output,_preview_setup,_preview_effect_count,_preview_effect_name,_preview_effect_metadata,_preview_select,_preview_set,_preview_length,_preview_frame,_preview_audio,_preview_palette_names \
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,HEAPU32 \
  -o "$out/virtual.mjs"
rm -rf "$out/obj"
cp "$out/virtual.mjs" "$out/preview.mjs"   # the effect preview's API too: its tests and the Effect studio can load it
echo "built $out/virtual.mjs and virtual.wasm (WLED from $wled${*:+, usermods: $*})"
