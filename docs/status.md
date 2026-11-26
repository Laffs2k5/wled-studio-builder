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

- **Virtual WLED** (`virtual/`, 2026-11-24): WLED's own effect engine compiled to WebAssembly from
  a checkout, with usermods; the effect preview's API, so the preview's and a usermod's tests run
  on the real engine; a smoke test over every effect (the list equal to the image's, no crashes).
  QuinLED 16.0.1 with wled-studio-effects: 242 effects id for id, 165 run, none crash. Next: the
  gate runs it (flags from the build), then a virtual device the app can use.

## Next

1. More vendor releases (QuinLED 0.15.x; stock WLED's esp32 builds), using `discover.py` and the
   matrix.
2. Hardening still open (pip `--require-hashes` done 2026-11-23): an apt snapshot and `--read-only`.
   `build.py --offline` now blocks the source/reference clients and keeps the proxy variables
   pointed at a closed local endpoint; override provenance and a dependency fingerprint must match
   the pins. Arbitrary build hooks still need the builder container's network isolation for an
   absolute socket-level guarantee. (The egress allowlist is done: wled-studio's compose runs the builder on
   an internal network behind a squid allowlist, tested end to end by its `firmware-e2e` workflow.)
3. ~~Exact colours in the preview~~ (done 2026-11-24): a preview built with a WLED checkout runs
   WLED's own colour and palette code, extracted by name at build time (`preview/wled_colors.py`);
   the job service builds previews this way from a pins file's WLED commit. Tested against the
   checkout's own palette data: every 16-entry palette entry for entry, and WLED's blending to
   the bit. Not covered: gamma, auto-white and the brightness limiter (WLED's bus layer).
4. ~~Flashing~~ (done 2026-11-26 on the spare WROVER): the full custom image went OTA through the
   mTLS-only app path, both added effects ran, config/presets stayed byte-identical, and
   `/update?revert` restored stock. The controller itself is still unchanged.

## Open design items

- **The inventory across versions:** effects that come and go between releases, so a user can
  carry an effect forward or try a new one before including it.

## Waiting on

- ~~A spare ESP32 for the first flash of a self-built image~~ (done 2026-11-26): USB recovery,
  4 MB layout, Improv Wi-Fi provisioning, gate-passed OTA, post-flash checks and revert all passed.
