# Virtual WLED

WLED's own effect engine and state code, compiled to WebAssembly from a WLED checkout: every
built-in effect, segments, layers, blend modes, palettes, presets, playlists and transitions, with
your usermods, running in Node or a browser with no device. Ours here is only the glue; every WLED
file is taken from the checkout at build time. Behind `server/` it is a **virtual device** that
anything speaking WLED's API can use (below).

```bash
source ~/emsdk/emsdk_env.sh
VIRTUAL_FLAGS="-DUSERMOD_AUDIOREACTIVE -DWLED_PS_DONT_REPLACE_FX -DWLED_ENABLE_GIF -DBOARD_HAS_PSRAM" \
  virtual/build.sh /tmp/virtual <WLED checkout> [usermod folder …]
VIRTUAL_DIR=/tmp/virtual EFFECTS_JSON=<the image's effects.json> node --test virtual/test/
PREVIEW_DIR=/tmp/virtual node --test <a usermod's frame tests>     # the same API as preview/
```

## How it's made

- `virtual_wled.py` copies the engine (`FX.cpp`, `FX_fcn.cpp`, `FX_2Dfcn.cpp`,
  `FXparticleSystem.cpp`, `colors.cpp`, `palettes.cpp`, `wled_math.cpp`), the state code
  (`presets.cpp`, `playlist.cpp`, `led.cpp`), their headers and bundled libraries (fastled_slim,
  ArduinoJson, TimeLib, Toki) from the checkout, and generates `globals.h` (every plain-data
  `WLED_GLOBAL` of WLED's `wled.h`, in its own `#if` structure), `json_extract.cpp` (`json.cpp`'s
  state functions by name), `file_extract.cpp` (`file.cpp` up to its web serving) and
  `util_extract.cpp` (helpers from `util.cpp` by name; the noise functions as one block).
- `wled.h` (ours) stands in for WLED's, which pulls in the whole device; `stub/` has the Arduino
  basics. Usermods register into a list (`REGISTER_USERMOD`): WLED's linker sections don't exist
  in WebAssembly.
- `glue.cpp` is the rest of the link: a **virtual bus** per output that keeps the pixels, the
  sound source, WLED's JSON buffer lock without the ESP32 mutex, and stand-ins (no fonts, plain
  memory; no UDP sync, realtime input, NTP or HTTP-in-JSON). Files live in an in-memory file
  system (`stub/Arduino.h`, `MemFS`).
- `api.cpp` is the effect preview's C API (`preview_*`), so the same tests run on the stand-in
  preview and on the real engine, plus `virtual_boot` and `virtual_output` (after brightness and
  gamma, as on the strip). Frames read WLED's own pixel buffer, as its live view does.
- `device.cpp` is the device's C API (`virtual_device_boot`, `virtual_loop`, `virtual_json`,
  `virtual_post_state`, `virtual_live`, the files, the PIN): it calls WLED's functions the way
  WLED's setup, loop and web server do.

## The board's flags make the effect list

Build with the firmware's own `-D` flags: they decide what's compiled in. For QuinLED's
Dig-Next-2 16.0.1 `-DWLED_PS_DONT_REPLACE_FX` keeps the classic effects (without it Fire 2012,
Rolling Balls and others are particle-system replacements or gone) and `-DWLED_ENABLE_GIF` adds
the Image effect. With them the list equals the image's `effects.json`, id for id (242 with
wled-studio-effects). Checked against a real Dig-Next-2 running QuinLED's 16.0.1 (2026-11-24): the
stock virtual build's 220 effects equal the device's `/json/eff` and `/json/fxdata`, every name and
every metadata string. The gate will take the flags from the build's compile command.

## Tests

- `test/smoke.test.mjs`: the effect list is the image's (with `EFFECTS_JSON`), and every 1D effect
  runs 160 frames at 30 and 280 LEDs, with simulated sound and with a mic level. A crash fails
  it, unless the firmware without your usermods crashes there too (`KNOWN_CRASHES`). On 16.0.1:
  165 effects run, none crash; 4 stay dark for good reasons (Image without a file, Copy Segment
  without a source, Sunrise starts dark, Lightning is random).
- The effect preview's tests and a usermod's own frame tests run unchanged (`PREVIEW_DIR`).
- `test/server.test.mjs`: the device server as a client sees it (info, state, the PIN, presets
  and a playlist, the websocket, files across a restart).

## In the gate

`studio/gate.py --emsdk <sdk>` (the job service always passes it) adds a fifth check,
`virtual_twin`, run by `studio/virtual_check.py` after the other four pass: the image's own build
writes `fx_flags.json` (FX.cpp's `-D` flags from the compile database; the check keeps `WLED_*`,
`USERMOD_*` and `BOARD_HAS_PSRAM`), the twin is built stock and with the usermods, the custom
twin's effect list must be the image's `effects.json`, and no effect may crash that doesn't crash
in the stock twin. A failed check fails the gate, so the image can't be flashed. CI proves it can
fail: `test/crash_probe` (an effect dividing by zero) must fail the smoke test, by name.

## Memory checking (not a gate yet)

`SANITIZE=1` builds with AddressSanitizer. First finding, in WLED itself: `Segment::loadPalette`
copies 72 bytes from a gradient palette shorter than that (a read past `Aurora_gp` and others;
harmless on a device, where it reads flash). Comparing against the firmware without our usermods
needs every report; recovery after a report (`-fsanitize-recover`, `halt_on_error=0`) still
stops at the second one under Emscripten. Until that works, crashes and the effect list gate.

## As a device

`server/server.mjs` puts a twin behind WLED's HTTP JSON API and websocket, with Node's standard
library only:

```bash
VIRTUAL_DIR=/tmp/virtual LEDS=124,126 PIN_FILE=<file> DATA_DIR=/tmp/vdata node virtual/server/server.mjs
VIRTUAL_DIR=/tmp/virtual node --test virtual/test/server.test.mjs
```

WLED's code answers: `/json/state` in and out (`deserializeState`, `serializeState`, including
`ps`, `psave`, playlists, `~` increments, transitions), `/json/eff`, `/json/fxdata`, `/json/pal`,
`/presets.json` and any other file (not the secrets), the settings PIN (`checkSettingsPIN`, the
3 s retry cooldown, the 15-minute relock) for `/upload` and `/update`, `/settings/lock`, and `/ws`
(the state and info greeting, pushes at most once a second, commands, the binary live view at
25 frames/s for the last client to ask). `/json/info` is WLED's LED, effect, palette and file
numbers plus the server's own: `arch` is `"virtual"` (so wled-studio won't plan a flash) and
`virtual` names the firmware, the WLED commit, the flags and the outputs. Files written by WLED
or uploaded are saved to `DATA_DIR` once a second, and read back at the next start.

`LEDS` gives one bus per output (`124,126`); WLED makes one segment over all of them, as on a
fresh device. What a twin doesn't have: WLED's config code (`POST /json/cfg` answers 501;
`/cfg.json` is an uploaded one or a short description of the twin), firmware updates (`/update`
refuses: a twin runs the firmware it was built from), its web UI and settings pages (`/` is a
small live-view page), the network (sync, realtime input such as DDP, MQTT, Alexa), 2D matrices
and a real sound input (sound-reactive effects get the simulated sound).

## What a twin also needs

The device's own settings: gamma (`virtual_boot`'s third argument, filling WLED's gamma tables;
without them Twinklefox stays black), the LED count and RGBW. Not simulated: the bus timing,
power limiting, the chip's speed and memory.
