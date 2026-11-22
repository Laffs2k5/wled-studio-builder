# Status and roadmap

Updated 2026-11-23.

## Done

- **Reproducible vendor builds:** pins as data (one file per vendor release, a target per board,
  overridable from the command line), `build.py --check` against recorded results per toolchain
  host, a normalized image hash that doesn't depend on build paths.
- **QuinLED 16.0.1:**
  - 11 of 14 boards reproduce the vendor image byte for byte, apart from the ELF hash, on Windows
    (GitHub's runner, and a local ARM64 machine running the x86-64 toolchain);
  - the 3 V4 boards need a newer QuickESPNow, pinned per target, to verify;
  - x86-64 Linux results are recorded per board where they build. QuinLED's override names some
    usermods in the wrong case for Linux; fixed automatically.
- **The gate** (`gate.py`): stock build checked, custom build, linker inputs compared (only the
  usermods' objects may be new), size against the app slot. It passes for the example effect, on
  Windows and in the container (CI).
- **The builder image** on ghcr.io (amd64, arm64), published only after CI proves it reproduces its
  bundled target, is deterministic, and passes the gate.
- **Job service** (`service.py`) for the wled-studio app: gate builds and WebAssembly previews.
- **Effect preview** (`preview/`): effect usermods compile unchanged to WebAssembly and render the
  frames their logic says (tested in Node).
- **CI:** unit tests; a matrix over every target on Windows and Linux (weekly too, for upstream
  drift); image build, test and publish; preview compile and frame tests.

## Next

1. Record the V4 boards and the case-fixed Linux results from the matrix.
2. More vendor releases (QuinLED 16.0.0, 0.15.x; stock WLED's esp32 builds), using
   `discover.py` and the matrix.
3. Egress allowlist for the builder container (a proxy on an internal network); pip
   `--require-hashes`; an apt snapshot; an `--offline` rerun with no network.
4. Exact colours in the preview: build WLED's own colour and palette helpers from the user's
   checkout instead of the stand-ins.
5. Flashing: OTA of a gate-passed image with a backup first and `/update?revert` as the way back,
   driven from the app.

## Waiting on

- **A spare ESP32** (ordered) for the first flash of a self-built image: boot, OTA, revert,
  post-flash checks. Nothing has been flashed.
