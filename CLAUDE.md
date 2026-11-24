# CLAUDE.md (wled-studio-builder)

Guidance for Claude Code in this repository. **Claude maintains this file**: when a convention,
gotcha or the status changes, update it in the same session, as its own commit.

## What this is

Tooling for **verifiable custom WLED firmware**: reproduce a vendor's published WLED build byte for
byte, then add your own effects, and prove that nothing else changed before anything is flashed.
Planned to go public. See [README.md](README.md) and [docs/](docs/). The web app that uses it is
the sibling repo `wled-studio`.

## Keep it publishable

- **No home or personal details:** no host names, IP addresses, MAC addresses, PINs, passwords,
  people's names, or anything that identifies an installation. Use placeholders (`<host>`).
- **No WLED source in this repo.** WLED and usermods are fetched at pinned commits at build time.
  The vendor build files we reuse are fetched too, not copied (QuinLED's override is MIT, but
  fetching keeps one source of truth).
- **Private effects never land here.** They live in a separate private repository and are passed to
  the build as an external usermod.

## Git

- **Push directly to `main`** (owner, 2026-11-23). Open a PR only when CI on a branch is needed
  before landing; then fast-forward `main` to it. Never squash, never merge commits.
- Atomic conventional commits; the body explains *why*.
- AI config (`CLAUDE.md`, `.claude/`) goes in its **own** commit.

## Building

- `studio/build.py <pins.json>` reproduces a pinned build and compares it with the vendor's image.
  It runs the same on Linux and Windows; a Python venv with `platformio` (version in
  `docker/Dockerfile`), Node.js and git must be on the path.
- `studio/imgdiff.py A.bin B.bin` explains differing bytes between two ESP32 app images.
- `studio/elfdiff.py A.elf B.elf` compares two ELFs symbol by symbol.
- `work/` (checkouts, PlatformIO packages) and `out/` (results) are git-ignored.

## Gotchas (learned the hard way)

- **WLED's UI build stamps the current time** (`WEB_BUILD_TIME`, `tools/cdata.js`), and WLED
  serves it in every HTTP `ETag`. Pin it (`web_build_time` in the pins file; `studio/fixtime.js`
  preloads into Node) or the image differs in 4 bytes. A vendor's value can be read from any of
  its devices' `ETag`, or found in the reference image.
- **The toolchain's host shows in the image.** Prebuilt newlib carries paths with the build host
  (`HOST-x86_64-w64-mingw32` for the Windows toolchain). QuinLED builds on Windows.
- **The host architecture picks the toolchain build.** PlatformIO resolves
  `toolchain-xtensa-esp32` per host (`linux_aarch64`, `linux_x86_64`, `windows_amd64`, …). Same
  version, different binaries. Record the host in every report (`build-report.json` does).
- **Line endings are a build input on Windows.** Git for Windows ships `core.autocrlf=true`, and the
  web UI sources end up inside the image. `build.py --autocrlf` sets it per checkout.
- **Usermods fetched by URL float** unless pinned. The pins file maps such URLs to commits, and
  `build.py` rewrites them to `url#commit`.
- **Windows needs a short work path.** The compiler command lines carry dozens of include paths;
  under a long folder they exceed Windows' limit and fail as "CreateProcess: No such file or
  directory". Use something like `--work C:\w`.
- **External usermods must be named `wled-…`** in their `library.json` (or be listed by a
  predictable URL name), or WLED's build doesn't treat them as modules and `wled.h` isn't found.
  WLED's own `mode_static()` isn't exported; an effect needs its own fallback.
- **The image's Python packages are locked with hashes** (`docker/requirements.txt`). To change
  PlatformIO's version, edit `docker/requirements.in` and regenerate:
  `uv pip compile docker/requirements.in --universal --python-version 3.11 --generate-hashes --no-header -o docker/requirements.txt`.
- PowerShell `*>` redirection writes UTF-16 logs; read them with `iconv -f utf-16`.
- **The preview shim must be no looser than WLED** where it can be checked: `mode_ptr` is nested in
  `WS2812FX`, `Usermod::setup()`/`loop()` are pure virtual, drawing methods are `const` and
  `color_wheel` is a Segment method. A usermod that passed a looser shim failed the real build
  (2026-11-23).
- **Exact colours copy WLED's code by name** (`preview/wled_colors.py`). When a WLED release
  renames or moves one of the functions, the extractor stops with "not found in the checkout":
  fix the name list, never paste WLED's code here. WLED's headers bring their own `RGBW32`, `R()`…,
  `scale8`, `qadd8`; the shim leaves its own out in exact mode (`PREVIEW_WLED_COLORS`).
- A `const` array at namespace scope is internal in C++: generated code that another file reads
  (`JSON_palette_names`) needs an `extern` declaration first, or the link fails.
- WLED's `color_from_palette(…, moving=false, …)` remaps the index so the palette doesn't wrap
  (`index * 0xF0 >> 8`): index 16 is *not* entry 1. Tests that want exact entries pass
  `moving=true`.
- The job service refuses a usermod folder that's a symlink (path confinement). Test with a copy.
- **Virtual WLED (`virtual/`) gotchas:** a `Bus` counts only with `_valid` and its capabilities
  set (`_hasRgb`/`_hasWhite`): without RGB a segment is on/off only and refuses black as its first
  colour. `makeAutoSegments()` makes segment 0; `calcGammaTable()` fills the tables Twinklefox
  needs. `service()` skips a frame within `MIN_FRAME_DELAY` of the last (0 at boot), so the clock
  starts a second ahead and `strip.timebase` takes it off again. The board's `-D` flags make the
  effect list (`WLED_PS_DONT_REPLACE_FX`, `WLED_ENABLE_GIF`): compare with the image's
  `effects.json`. Frames come from WLED's pixel buffer (`strip.getPixelColor`), not the bus.
- **The virtual device (`virtual/device.cpp`, `server/`) gotchas:** `globals.h` is included twice
  (declared by our `wled.h`, defined by `glue.cpp`), so it must not keep WLED's `WLED_H` include
  guard, and only its `Button` struct is guarded. Array globals need `_INIT_N` as WLED defines it
  (`UNPACK`). WLED pushes to websocket clients at most once a second
  (`INTERFACE_UPDATE_COOLDOWN`), and a running playlist keeps changing the state: tests wait for
  pushes and end playlists (picking an effect by hand does, as in WLED). Don't stop the local
  server with `pkill -f` on its command line: the pattern matches your own shell and kills it.
  Use the task's stop instead.
- **Stand-in templates must return by value:** `auto min(T a, U b) -> decltype(a < b ? a : b)` is
  a reference to a parameter (dangling). It made Fireworks 1D overflow and 48 effects dark in the
  virtual WLED, and lurked in the preview shim too. Use `std::common_type<T, U>::type`.
- Arduino's `constrain` is a macro; ArduinoJson needs `ARDUINOJSON_ENABLE_ARDUINO_STRING` and a
  `String` with `concat()` (and a `StringSumHelper`) for usermods that add a `String` to JSON.
