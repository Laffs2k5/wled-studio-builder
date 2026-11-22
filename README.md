# wled-studio

Tooling for building **verifiable custom WLED firmware**: reproduce a vendor's published WLED build
byte for byte, then add your own effects, and prove that nothing else changed before anything is
flashed.

**Status: early work in progress.** The first vendor image, QuinLED's Dig-Next-2 build of WLED
16.0.1, is reproduced: identical in every byte of code and data, apart from one embedded hash of
the ELF file ([docs/reproductions.md](docs/reproductions.md)).

This repository contains no WLED source code. The build fetches WLED, the vendor's build file and
the usermods from their upstream repositories at pinned commits.

## How it works

- **A pins file** (`pins/*.json`) names every input of a vendor build by commit: WLED, the vendor's
  `platformio_override.ini`, the usermods and libraries that would otherwise float, the UI build
  time, line endings. It also names the vendor's image and its sha256.
- **`studio/build.py`** fetches those inputs, builds with PlatformIO, and compares the result with
  the vendor's image.
- **`studio/imgdiff.py`** explains every byte that differs between two ESP32 app images, and
  fails on anything it can't explain.
- **`studio/elfdiff.py`** compares two builds function by function, with addresses normalised.

The gate before any flash is described in [docs/chain-of-trust.md](docs/chain-of-trust.md).

## Quick start

Needs Python 3.12+, Node.js 22 and git on the path.

```bash
python -m venv .venv && .venv/bin/pip install platformio==6.2.0
.venv/bin/python studio/build.py pins/quinled-dig-next-2-16.0.1.json
cat out/*/build-report.json      # identical_except_elf_sha256: true on a Windows host
```

On Windows, use `.venv\Scripts\python`. A container build is in `docker/Dockerfile`.

## Layout

```
pins/        pinned inputs of vendor builds
studio/      build driver and comparison tools
docker/      the builder image
docs/        how and why
tests/       unit tests (python -m unittest discover -s tests)
```
