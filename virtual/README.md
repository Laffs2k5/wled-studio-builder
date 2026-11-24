# Virtual WLED

WLED's own effect engine, compiled to WebAssembly from a WLED checkout: every built-in effect,
segments, layers, blend modes, palettes, with your usermods, running in Node or a browser with no
device. Ours here is only the glue; every WLED file is taken from the checkout at build time.

```bash
source ~/emsdk/emsdk_env.sh
VIRTUAL_FLAGS="-DUSERMOD_AUDIOREACTIVE -DWLED_PS_DONT_REPLACE_FX -DWLED_ENABLE_GIF -DBOARD_HAS_PSRAM" \
  virtual/build.sh /tmp/virtual <WLED checkout> [usermod folder …]
VIRTUAL_DIR=/tmp/virtual EFFECTS_JSON=<the image's effects.json> node --test virtual/test/
PREVIEW_DIR=/tmp/virtual node --test <a usermod's frame tests>     # the same API as preview/
```

## How it's made

- `virtual_wled.py` copies the engine (`FX.cpp`, `FX_fcn.cpp`, `FX_2Dfcn.cpp`,
  `FXparticleSystem.cpp`, `colors.cpp`, `palettes.cpp`, `wled_math.cpp`), its headers and bundled
  libraries (fastled_slim, ArduinoJson, TimeLib) from the checkout, and generates `globals.h` (the
  `WLED_GLOBAL`s the engine reads, from WLED's `wled.h`) and `util_extract.cpp` (helpers from
  `util.cpp` and `led.cpp` by name; the noise functions as one block).
- `wled.h` (ours) stands in for WLED's, which pulls in the whole device; `stub/` has the Arduino
  basics. Usermods register into a list (`REGISTER_USERMOD`): WLED's linker sections don't exist
  in WebAssembly.
- `glue.cpp` is the rest of the link: a **virtual bus** that keeps the pixels, the sound source,
  and stand-ins (no fonts, no files, plain memory).
- `api.cpp` is the effect preview's C API (`preview_*`), so the same tests run on the stand-in
  preview and on the real engine, plus `virtual_boot` and `virtual_output` (after brightness and
  gamma, as on the strip). Frames read WLED's own pixel buffer, as its live view does.

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

## Memory checking (not a gate yet)

`SANITIZE=1` builds with AddressSanitizer. First finding, in WLED itself: `Segment::loadPalette`
copies 72 bytes from a gradient palette shorter than that (a read past `Aurora_gp` and others;
harmless on a device, where it reads flash). Comparing against the firmware without our usermods
needs every report; recovery after a report (`-fsanitize-recover`, `halt_on_error=0`) still
stops at the second one under Emscripten. Until that works, crashes and the effect list gate.

## What a twin also needs

The device's own settings: gamma (`virtual_boot`'s third argument, filling WLED's gamma tables;
without them Twinklefox stays black), the LED count and RGBW. Not simulated: the bus timing,
power limiting, the chip's speed and memory.
