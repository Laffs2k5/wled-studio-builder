# Status and roadmap

Updated 2026-11-23.

## Done

- **Reproducible vendor builds:** pins as data (one file per vendor release, a target per board,
  overridable from the command line), `build.py --check` against recorded results per toolchain
  host, a normalized image hash that doesn't depend on build paths.
- **QuinLED 16.0.1:**
  - **all 14 boards** reproduce the vendor image byte for byte, apart from the ELF hash, on Windows
    (GitHub's runner, and a local ARM64 machine running the x86-64 toolchain). The V4 boards took a
    newer QuickESPNow pin and `origin_remote: false`;
  - x86-64 Linux results are recorded per board where they build. QuinLED's override names some
    usermods in the wrong case for Linux; fixed automatically.
- **QuinLED 16.0.0:** **all 11 boards** reproduce the vendor image apart from the ELF hash on
  Windows, with only a new pins file found with `discover.py`; x86-64 Linux results recorded.
- **The effect manifest** (`manifest.py`, 2026-11-23): `build.py` writes `effects.json`, the
  image's effects as `/json/eff` and `/json/fxdata` will report them. Built-ins come from `FX.cpp`
  run through the preprocessor with the build's own compile command (PlatformIO's compile
  database), and `setupEffectData()` replayed under `addEffect()`'s rules (placeholders, 255 takes
  the first gap, an id past the end is appended). Usermod effects are read in the templates' fixed-id
  shape. CI checks the container's custom image against a Dig-Next-2's known 16.0.1 list. The job
  service serves it (`/jobs/<id>/effects.json`), for wled-studio's preflight.
- **The gate** (`gate.py`): stock build checked, custom build, linker inputs compared (only the
  usermods' objects may be new), size against the app slot. It passes for the example effect, on
  Windows and in the container (CI).
- **The builder image** on ghcr.io (amd64, arm64), published only after CI proves it reproduces its
  bundled target, is deterministic, and passes the gate.
- **Job service** (`service.py`) for the wled-studio app: gate builds and WebAssembly previews.
- **Effect preview** (`preview/`): effect usermods compile unchanged to WebAssembly and render the
  frames their logic says (tested in Node).
- **First real effects through the gate** (2026-11-23): wled-studio-effects (two effects at fixed
  ids 240 and 241) passed the gate into QuinLED's Dig-Next-2 16.0.1 image: stock checked, only its
  three objects added, the effect list as planned. It took two lessons, now built in: the preview
  shim is as strict as WLED about `mode_ptr` (nested) and `Usermod::setup()`/`loop()` (pure
  virtual), and a usermod's folder must not hold the gate's work folder (PlatformIO compiles every
  source file under a library). Downloads retry a 5xx or network failure (a 503 from
  raw.githubusercontent.com failed one run).
- **CI:** unit tests; a matrix over every target on Windows and Linux (weekly too, for upstream
  drift); image build, test and publish; preview compile and frame tests.

## Next

1. More vendor releases (QuinLED 0.15.x; stock WLED's esp32 builds), using `discover.py` and the
   matrix.
2. Hardening still open (pip `--require-hashes` done 2026-11-23): an apt snapshot; an `--offline` rerun with no
   network; `--read-only`. (The egress allowlist is done: wled-studio's compose runs the builder on
   an internal network behind a squid allowlist, tested end to end by its `firmware-e2e` workflow.)
3. Exact colours in the preview: build WLED's own colour and palette helpers from the user's
   checkout instead of the stand-ins. **Spiked 2026-11-24** against 16.0.1's checkout, compiled
   with Emscripten 7.0.1:
   - `src/dependencies/fastled_slim` compiles as it is; `palettes.cpp` (the 7 FastLED and 59
     gradient palettes, pure data) compiles with stand-ins for `PROGMEM`, `pgm_read_*`,
     `memcpy_P` and `byte`;
   - `colors.cpp` doesn't compile whole: it mixes the pure colour maths (`color_blend`,
     `color_fade`, `ColorFromPalette`, `hsv2rgb_spectrum`, `rgb2hsv`) with custom-palette file
     loading and the random palette. Extract the pure functions by name, as `manifest.py` reads
     `FX.cpp`;
   - `Segment::loadPalette` and `Segment::color_from_palette` (`FX_fcn.cpp`) are what effects see.
     Their bodies use `colors`, `palette`, `_default_palette`, `_randomPalette`, `_isRGB`,
     `paletteBlend`, `_currentPalette`, `getCurrentColor()`, `vLength()`, `customPalettes`,
     `usermodPalettes` and the palette id constants from `const.h`. Extract them too, and give the
     shim's `Segment` those members, so the bodies compile unchanged;
   - the catch: `colors.h` defines `RGBW32`, `R()`… itself, and `const.h` brings more. The shim
     must take WLED's definitions when building with a checkout, and keep its own without one;
   - design: `build.sh` takes an optional checkout (`WLED_SRC`); the job service passes the
     target's checkout (the gate's work folder, or a fresh one at the pins' commit); without one,
     the preview stays approximate, as today. Nothing of WLED's goes into this repo. The app then
     offers WLED's palettes by name in the preview (names from the device or the manifest);
   - test: palette entries and blends checked against values computed by the same functions in
     a native build of the extracted code.
4. Flashing: OTA of a gate-passed image with a backup first and `/update?revert` as the way back,
   driven from the app.

## Open design items

- **The inventory across versions:** effects that come and go between releases, so a user can
  carry an effect forward or try a new one before including it.

## Waiting on

- **A spare ESP32** (ordered) for the first flash of a self-built image: boot, OTA, revert,
  post-flash checks. Nothing has been flashed.
