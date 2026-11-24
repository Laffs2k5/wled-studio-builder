# Licensing

**This repository is licensed under the EUPL-1.2** ([LICENSE](../LICENSE)), the licence WLED itself
uses. Source files carry `SPDX-License-Identifier: EUPL-1.2`.

## What this repository contains, and what it doesn't

- **Ours:** the build driver and comparison tools (`studio/`), the pins files (facts about other
  projects' releases: URLs, commit ids, sha256s, sizes), the docs, the tests, the CI and the
  builder image definition, and an example usermod.
- **Not here, fetched at build time:**

  | What | Licence | How it's used |
  |---|---|---|
  | WLED's source (`wled/WLED`) | EUPL-1.2 | checked out at a pinned commit, built locally |
  | The vendor's `platformio_override.ini` (e.g. QuinLED's) | the vendor's (QuinLED-Firmware: MIT) | downloaded at a pinned commit |
  | Usermods and libraries (PowerManager, QuickESPNow, …) | their own | fetched by PlatformIO at pinned commits or versions |
  | The vendor's published firmware image | the vendor's | downloaded only to compare against; never redistributed |

- **The builder image** contains Debian, Node.js and PlatformIO (each under its own licence) plus
  this repository's tools. No WLED code is in the image.

## Firmware you build

A firmware image you build with this tool is WLED, a derivative of EUPL-1.2 code, plus whatever
usermods you add. **Building and flashing your own devices is private use**, with no obligations.
If you **distribute** an image, the EUPL applies to it:
- publish the corresponding source (your usermods included);
- keep the notices;
- mark your changes.

WLED's and the vendors' names and trademarks are theirs.

## Previews with exact colours

A preview built with a WLED checkout (`WLED_SRC`, see `preview/README.md`) compiles part of WLED's
code into its WebAssembly: colour and palette functions from `colors.cpp` and `FX_fcn.cpp`, the
palettes (`palettes.cpp`) and fastled_slim (MIT, derived from FastLED; its licence is copied in with
it). `preview/wled_colors.py` takes them from the checkout at build time; **none of it is stored
in this repository**. Like firmware, the result is yours to use: it runs in your browser. If you
distribute a compiled preview, the same terms as for firmware apply (WLED's source, the notices).

## Virtual devices

A virtual WLED (`virtual/`, its image `virtual/Dockerfile`) compiles much of WLED into its
WebAssembly: the effect engine, the state, preset, playlist and file code, the bundled libraries.
`virtual/virtual_wled.py` takes them from the checkout at build time; none of it is stored in this
repository. Built and run on your own machines, it is private use, like firmware. **This
repository's CI builds the image only to test it and publishes none.** If you distribute a
virtual device image, the same terms as for firmware apply: its `twin.json` names the WLED commit
and the usermods, which is where the corresponding source is.

## Example usermod

`examples/usermods/studio_example_fx` is our own code, EUPL-1.2. It compiles against WLED's
headers at build time and doesn't copy WLED code.
