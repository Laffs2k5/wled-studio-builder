# The builder image

```bash
docker build -f docker/Dockerfile -t wled-studio-builder .
mkdir -p work out && sudo chown 10001:10001 work out      # the image runs as uid 10001
docker run --rm \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 4096 --cpus 2 \
  -v "$PWD/work:/work" -v "$PWD/out:/out" wled-studio-builder
```

The default command reproduces `pins/quinled-dig-next-2-16.0.1.json` into `/out`:
- `firmware.bin` and `firmware.elf`;
- `build-report.json` with the comparison against the vendor image;
- `objects.json`, the linker inputs;
- `packages.txt`, the package versions PlatformIO resolved.

Keep `/work` between runs: it holds the WLED checkout and about 1 GB of toolchain packages.

**Network:** outbound HTTPS to GitHub, the PlatformIO registry and npm. Nothing else is needed.
Enforcing that (an `--internal` network with an allowlist proxy) is on the to-do list.

**Expected result** on x86-64 Linux: not byte-identical to QuinLED's Windows-built image (the
toolchain's paths and three functions differ, see [../docs/reproductions.md](../docs/reproductions.md)).
Two runs must give the same sha256.
