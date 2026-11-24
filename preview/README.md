# Effect preview (WebAssembly)

Run effect usermods written for WLED in the browser, without flashing anything.

- `shim/wled.h` and `shim/shim.cpp`: a stand-in for the part of WLED's usermod and effect API that
  effect code uses (`Usermod`, `REGISTER_USERMOD`, `strip.addEffect`, `SEGMENT`, `SEGENV`, colours,
  a few integer helpers). An effect usermod compiles **unchanged** against it. It's our own
  implementation of that interface, not WLED's code.
- `build.sh OUT USERMOD_DIR…`: compiles the shim and the usermods with Emscripten into
  `preview.mjs` and `preview.wasm`.
- The C API: `preview_setup(len)`, `preview_effect_count/name/metadata(id)`, `preview_select(id)`,
  `preview_set(key, value)`, `preview_frame(now_ms)` (returns the pixels, `0xWWRRGGBB` per LED),
  `preview_audio(level)`: the preview's "mic", a volume 0–255, or below 0 for none.
- **Sound:** a sound effect in a usermod reads AudioReactive's data as WLED's own effects do,
  `UsermodManager::getUMData(&um, USERMOD_ID_AUDIOREACTIVE)`, and falls back to
  `simulateSound(SEGMENT.soundSim)`. The shim offers both: the level set with `preview_audio`, or
  its own simulation (`preview_set` key 12 picks it, as WLED's sound simulation setting does).
  Effects keep their ids as on the device; a usermod that registers at a fixed id behind `RSVD`
  placeholders gets the same id here.
- **As strict as WLED where it bit us:** `mode_ptr` is nested (`WS2812FX::mode_ptr`) and
  `Usermod::setup()`/`loop()` are pure virtual, as in WLED. A usermod that named `mode_ptr` bare or
  had no `loop()` passed the preview and failed the real build (2026-11-23), so the shim now rejects
  both. Anything else the shim allows may still fail in WLED: the gate's build is the check.

- **Exact colours** (`WLED_SRC=<WLED checkout> preview/build.sh …`): WLED's own colour and
  palette code compiles in instead of our stand-ins. `wled_colors.py` takes it from the checkout
  at build time: `colors.h`, `palettes.cpp` and fastled_slim whole; the pure colour functions from
  `colors.cpp` and the Segment methods effects call (`loadPalette`, `color_from_palette`,
  `color_wheel`, `fill`, the fades, `blur`) from `FX_fcn.cpp`, by name; and the palette names. The
  shim's Segment has the members those bodies use, so they compile unchanged. All of WLED's
  palettes then render as on the device, with WLED's blending; `preview_palette_names()` returns
  their names (`""` without a checkout). Nothing of WLED's is stored in this repository. The job
  service builds previews this way from the WLED commit of a pins file
  (`WLED_STUDIO_PREVIEW_PINS`, else the newest).

```bash
source ~/emsdk/emsdk_env.sh
preview/build.sh /tmp/preview examples/usermods/studio_example_fx
PREVIEW_DIR=/tmp/preview node --test preview/test/preview.test.mjs
```

The job service (`studio/service.py`) compiles previews on request (`POST /previews`); it installs
Emscripten into the work volume the first time, at the version in `EMSDK_VERSION`.

## Limits (spike, 2026-11-23)

- **Without a checkout, approximate where WLED's exact maths matter:** fades, palettes (palette 0
  uses the colour slot). With one (exact colours, above), palettes, blends and fades are WLED's.
  Still not in the preview either way: gamma and RGBW auto-white, which WLED applies on the way
  to the LEDs (the bus layer), and the brightness limiter.
- **WLED's built-in effects aren't previewed:** they live in WLED's `FX.cpp`, which pulls in all of
  WLED. Your own effects are what this is for; for built-ins, the device's live view is the preview.
- **Compiling happens where Emscripten is:** in CI, for developers, and in the builder's job service
  (installed on first use into the work volume, so the image stays small).
