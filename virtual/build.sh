#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Build a virtual WLED: WLED's own effect engine from a checkout, compiled to WebAssembly.
#   virtual/build.sh OUT_DIR WLED_CHECKOUT [USERMOD_DIR ...]
# Environment:
#   VIRTUAL_FLAGS   the firmware's own -D flags for the engine (from its compile command);
#                   default: -DUSERMOD_AUDIOREACTIVE
#   SANITIZE=1      build with AddressSanitizer (memory errors stop the run with a report)
#   TWIN_NAME       what the twin is of, for the device server (e.g. quinled-dig-next-2 16.0.1)
# Needs Emscripten (em++) and python3. Writes OUT_DIR/virtual.mjs and virtual.wasm, and
# twin.json (the WLED version and commit, the flags and usermods: what the device server reports).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(mkdir -p "$1" && cd "$1" && pwd); shift
wled=$1; shift
gen="$out/wled-src"
rm -rf "$gen"
python3 "$here/virtual_wled.py" "$wled" "$gen"
# ours next to the engine, so every "wled.h" (the engine's and the glue's) is the same file
cp "$here/wled.h" "$here/glue.cpp" "$here/api.cpp" "$here/device.cpp" "$gen/"
flags=(-std=gnu++17 -O2 -w -Uunix -Ulinux -D__time_t_defined -I"$here/stub" -I"$gen")   # the libc has time_t (TimeLib)
read -r -a extra <<< "${VIRTUAL_FLAGS:--DUSERMOD_AUDIOREACTIVE}"
flags+=("${extra[@]}")
link=()
if [ "${DEBUG:-}" = 1 ]; then flags+=(-g); link+=(-g); fi
if [ "${SANITIZE:-}" = 1 ]; then flags+=(-fsanitize=address -fsanitize-recover=address -g); link+=(-fsanitize=address -fsanitize-recover=address -g -sINITIAL_MEMORY=268435456); fi
srcs=("$gen"/FX.cpp "$gen"/FX_fcn.cpp "$gen"/FX_2Dfcn.cpp "$gen"/FXparticleSystem.cpp "$gen"/colors.cpp "$gen"/palettes.cpp
      "$gen"/wled_math.cpp "$gen"/util_extract.cpp "$gen"/json_extract.cpp "$gen"/presets.cpp "$gen"/playlist.cpp
      "$gen"/led.cpp "$gen"/file_extract.cpp "$gen"/src/dependencies/fastled_slim/fastled_slim.cpp
      "$gen"/src/dependencies/time/Time.cpp "$gen"/src/dependencies/time/DateStrings.cpp "$gen/glue.cpp" "$gen/api.cpp" "$gen/device.cpp")
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
  -sERROR_ON_UNDEFINED_SYMBOLS=1 -Wl,--error-limit=0 \
  -sEXPORTED_FUNCTIONS=_virtual_boot,_virtual_output,_preview_setup,_preview_effect_count,_preview_effect_name,_preview_effect_metadata,_preview_select,_preview_set,_preview_length,_preview_frame,_preview_audio,_preview_palette_names,_virtual_device_boot,_virtual_loop,_virtual_ddp,_virtual_json,_virtual_post_state,_virtual_ws_pushes,_virtual_live,_virtual_file_write,_virtual_file_read,_virtual_file_list,_virtual_file_writes,_virtual_info,_virtual_palette_names,_virtual_set_pin,_virtual_unlocked,_virtual_lock,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,stringToNewUTF8,HEAPU8,HEAPU32,HEAP32 \
  -o "$out/virtual.mjs"
rm -rf "$out/obj"
cp "$out/virtual.mjs" "$out/preview.mjs"   # the effect preview's API too: its tests and the Effect studio can load it
python3 - "$out/twin.json" "$wled" "${TWIN_NAME:-}" "${extra[*]}" "$@" <<'PY'
import json, pathlib, subprocess, sys
out, wled, name, flags, *usermods = sys.argv[1:]
root = pathlib.Path(wled)
try:
    ver = json.loads((root / "package.json").read_text())["version"]
except (OSError, ValueError, KeyError):
    ver = ""
commit = subprocess.run(["git", "-C", wled, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
json.dump({"firmware": name, "ver": ver, "wled": commit, "flags": flags.split(),
           "usermods": [pathlib.Path(u).name for u in usermods]}, open(out, "w"), indent=1)
PY
echo "built $out/virtual.mjs and virtual.wasm (WLED from $wled${*:+, usermods: $*})"
