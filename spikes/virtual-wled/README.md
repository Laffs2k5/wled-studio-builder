# Spike: a virtual WLED in WebAssembly (2026-11-24)

**A spike, not a feature:** nothing uses this folder. It answers whether WLED's own built-in
effects, segments and layers can run in the browser with no device, and what that takes. The
files here are our glue; every WLED file is taken from a checkout at build time, never stored here.

## Result: yes

Against QuinLED's 16.0.1 checkout (the Dig-Next-2's pinned commit), with Emscripten 7.0.1:

- **Compiled unchanged:** `FX.cpp` (all built-in effects, 11,224 lines), `FX_fcn.cpp` (segments,
  layers, blending, the frame loop), `FX_2Dfcn.cpp`, `FXparticleSystem.cpp`, `colors.cpp`,
  `palettes.cpp`, `wled_math.cpp`, fastled_slim and the bundled time library.
- **Against our own `wled.h`** (this folder) instead of WLED's, which pulls in the device (Wi-Fi,
  the web server, MQTT…): Arduino basics (`stub/Arduino.h`), the web server's types as names
  only, WLED's effect-side headers, and the globals the code reads, taken from WLED's `wled.h`
  by name (`globals.h`, generated).
- **The link surface is small:** 26 symbols. A virtual bus that keeps the pixels (`vbus.cpp`,
  the heart of it), stand-ins for fonts, LED maps and memory, and helpers taken from `util.cpp`
  and `led.cpp` by name or as a block (the noise functions keep their `#define` and helpers).
- **It runs:** the effect list is 220, as the builder's manifest has for the real image. Rainbow,
  Pride 2015, Fire 2012, Colortwinkles and Twinklefox render frames that move as on a device.
  About 0.02 ms a frame for 280 LEDs in Node; 201 kB of WebAssembly.

## Lessons for the build

- **Boot like WLED:** `finalizeInit()` takes buses from `busConfigs`, a bus counts only when
  `isOk()` (`_valid`), `makeAutoSegments()` makes segment 0, and the gamma tables are filled when
  WLED loads its config (`calcGammaTable`). Without them: no LEDs, no segment, or black twinkles.
  So the twin also needs the device's own settings (gamma, LED count, RGBW), from its `cfg.json`.
- **Extracting by name isn't always enough:** a section with its own `#define` and static helpers
  (the noise functions) is taken as a block, and helpers keep their source order.
- Arduino's `constrain` is a macro: a template version breaks on ArduinoJson proxies.
- Emscripten's `getenv` doesn't see the shell's environment; pass switches as arguments.

## Left for the build

- **The API:** WLED's `json.cpp` (state in and out, as the app already speaks to a device) is 158
  compile errors away, nearly all globals (presets, nightlight, sync, Wi-Fi info); its link
  surface (presets, playlists) is bigger than the effects'. Or a smaller API of our own first.
- **Sound:** our source behind `UsermodManager::getUMData`, as in the effect preview; WLED's
  `simulateSound` already runs.
- **Text effects:** WLED's font code, or text left out at first.
- **The builder:** extraction and compile as a job per firmware (the pins' commit and the board's
  flags, plus a gate job's usermods), the effect list checked against the image's
  `effects.json`.
- **The app:** a "virtual device" that Looks & effects can target, drawn on the room plan.

## To rerun

The command lines are in the session notes of 2026-11-24 (wled-studio's `docs/status.md`, item 6):
copy the effect sources from a checkout next to this `wled.h`, create empty stubs for the platform
headers the compiler names, generate `globals.h` and `util_math.cpp` from the checkout, compile with
`em++ -std=gnu++17 -O2 -Istub -I.`, link with `vbus.cpp` and `main.cpp`, and run
`node a.js <effect id> [dump]`.
