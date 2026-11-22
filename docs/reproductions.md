# Reproductions

Vendor images reproduced with `studio/build.py`, and what it took.

## QuinLED, WLED 16.0.1 (pins/quinled-16.0.1.json)

14 boards, one release. The verified results per board and toolchain host are in the pins file;
the `matrix` workflow rebuilds all of them on Windows and x86-64 Linux.

| Board (target) | Windows (vendor's host OS) | x86-64 Linux |
|---|---|---|
| dig-next-2, dig-Uno-V3, dig-Uno-V3-AEplus, dig-Quad-V3, dig-Quad-V3-AEplus, dig-Octa_32-8L, dig-Octa_32-8L-Temp, dig2go, an_penta_deca, an_penta_plus, an_penta_mini (11) | **matches the vendor image** (GitHub's Windows runner, two matrix runs; same pins for all) | recorded for all 11 |
| dig-Uno-V4 | **matches** (2026-11-23, locally; with the V4 QuickESPNow pin and `origin_remote: false`) | to record |
| dig-Octa-V4, dig-Quad-V4 | same fix as dig-Uno-V4; to verify by the matrix | to record |

**The V4 boards took two more findings:**
- their envs were added on 2026-10-27, so the vendor's cached QuickESPNow is the newer commit
  (pinned per target);
- they don't set `WLED_REPO`, so WLED's build stamps it from the checkout's `origin` remote. The
  vendor's tree had no GitHub origin, so its images say `unknown`; ours said `wled/WLED`, 2 bytes
  longer, shifting everything after it. `checkout.origin_remote: false` names the remote
  `upstream` instead.

**Case-sensitivity:** QuinLED's override names some usermods in lowercase (`temperature`,
`internal_temperature_v2`) where WLED's folders are `Temperature` and `Internal_Temperature_v2`.
Windows finds them; Linux doesn't, so those 5 targets failed on Linux. `build.py` now picks the
folder case-insensitively (the folder Windows picks) and lists each fix in the report
(`usermod_case_fixes`).

### Dig-Next-2

**Result (2026-11-22): identical apart from the ELF hash.** Built on Windows (ARM64, running the
x86-64 toolchain under emulation), the image matches QuinLED's release image
(`WLED_16.0.1_Dig-Next-2.bin`, sha256 `f6a2b275…a610`) in every byte of code and data. The only
differences:
- `esp_app_desc_t.app_elf_sha256` (32 bytes at offset 0xb0): a hash of the ELF file, whose debug
  info contains the build directory;
- the image checksum and the appended image hash, which follow from it.

**Independently confirmed** on GitHub's native x86-64 Windows runner (`reproduce` workflow):
`identical_except_elf_sha256: true`.

Proof: copying QuinLED's ELF hash into our image and recomputing the checksum and hash gives
exactly QuinLED's sha256 (`imgdiff.py --transplant-elf-sha`; `build.py` reports it as
`identical_except_elf_sha256`).

**The inputs that had to be found** (all recorded in the pins file):

| Input | Found how | Effect when wrong |
|---|---|---|
| WLED `v16.0.1` | the device's `vid` 2605010 = `VERSION` in `wled.h` | — |
| QuinLED's override at `b015443` | the last commit touching it before the image was replaced (2026-10-27) | — |
| PowerManager `v1.3.0` | newest tag before the image; unpinned in the override | — |
| QuickESPNow `193e991` | WLED fetches the `optional-debug` **branch**; the branch moved on 2026-09-27. The vendor's build tree still had the March 2025 commit cached | +152 bytes of code |
| UI build time 1783528886 (2026-07-08 16:41:26 UTC) | the device's HTTP `ETag`; appears once in the image. The vendor reuses a build tree, so the UI was last regenerated at the original 16.0.1 release | 4 bytes |
| LF line endings | Git for Windows defaults to `autocrlf=true`, which grows `iro.js` inside the image | +4 bytes, everything after it shifts |
| Windows host toolchain | newlib strings carry `HOST-x86_64-w64-mingw32` | strings shift, one function's code differs (see below) |

**Other hosts:** a Linux ARM64 build (toolchain `linux_aarch64`) differs from the Windows build in
three ways:
- the toolchain's newlib path strings (`HOST-aarch64-linux-gnu` instead of
  `HOST-x86_64-w64-mingw32`), which shift everything after them;
- the gzip header's OS byte in the web UI (Node writes 3 on Unix, 10 on Windows); the compressed
  data is identical;
- **register allocation in one function** (`dmx_receive`, 2 bytes longer on Windows). GCC 8.4
  built for another host makes a different, equally valid choice. So the compiler binary isn't
  perfectly host-independent.

So only a build on the vendor's host OS can be byte-exact (step 1 of the chain of trust). A Linux
container build is compared per function instead (step 2).

Per function (`elfdiff.py --code`, addresses normalised): of 7,423 functions, **3 differ** between
the Windows and the Linux ARM64 build: `dmx_receive` (register allocation) and two `std::string`
internals from the toolchain's prebuilt libstdc++, which is compiled separately for each host
package. Every other function is identical instruction for instruction.

**x86-64 Linux** (the builder container on a docker host, and GitHub's Ubuntu runner): the same 3
functions differ from the Windows build. The image is 80 bytes shorter: the linux-amd64 toolchain
was built natively, so its newlib paths have no `HOST-<triple>/` part at all (4 strings, 24 bytes
each, before alignment). The container build is **deterministic** (two runs, identical `.bin` and
`.elf`), and it equals the Ubuntu runner's image apart from the ELF hash.

## Step 3: custom vs stock (example usermod)

Both built on Windows with `--clean` in the same work tree; the custom build adds
`examples/usermods/studio_example_fx` (one effect, fixed id 254):
- **objects:** 502 of 502 stock objects byte-identical; 1 added (`studio_example_fx.cpp.o`);
- **image:** 1,336,096 bytes (+1,312);
- the clean stock rebuild still matches QuinLED's image apart from the ELF hash.

