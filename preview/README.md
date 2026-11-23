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

```bash
source ~/emsdk/emsdk_env.sh
preview/build.sh /tmp/preview examples/usermods/studio_example_fx
PREVIEW_DIR=/tmp/preview node --test preview/test/preview.test.mjs
```

The job service (`studio/service.py`) compiles previews on request (`POST /previews`); it installs
Emscripten into the work volume the first time, at the version in `EMSDK_VERSION`.

## Limits (spike, 2026-11-23)

- **Approximate where WLED's exact maths matter:** fades, palettes (palette 0 uses the colour slot),
  gamma, RGBW auto-white. The frames match the effect's logic, not the strip's exact colours. Exact
  output would mean compiling WLED's own helpers from the user's checkout, the next step.
- **WLED's built-in effects aren't previewed:** they live in WLED's `FX.cpp`, which pulls in all of
  WLED. Your own effects are what this is for; for built-ins, the device's live view is the preview.
- **Compiling happens where Emscripten is:** in CI, for developers, and in the builder's job service
  (installed on first use into the work volume, so the image stays small).
