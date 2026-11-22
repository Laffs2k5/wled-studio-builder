#!/usr/bin/env python3
"""Reproduce a pinned WLED build and compare it with the vendor's published image.

Runs the same way on Linux and Windows. Every input comes from a pins file
(pins/*.json): the WLED commit, the vendor's platformio_override.ini at a commit,
pinned commits for any usermod the override fetches unpinned, and the UI build
time to stamp. Nothing is taken from the network unpinned, except PlatformIO's
own packages, which WLED's platformio.ini pins by version.

Usage:
  python studio/build.py pins/quinled-dig-next-2-16.0.1.json [--work DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, capture: bool = False) -> str:
    print("+ " + " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=cwd, env=env, check=True,
                         stdout=subprocess.PIPE if capture else None, text=True)
    return res.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"+ download {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "wled-studio"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def tool_version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, shell=(os.name == "nt")).stdout.strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001 - report, don't fail
        return f"unavailable ({e.__class__.__name__})"


def checkout(repo: str, commit: str, dest: Path, autocrlf: str | None = None) -> None:
    """Clone (or reuse) dest at exactly `commit`, with a clean tree.

    autocrlf: None keeps the host's git default (Git for Windows ships `true`);
    "true"/"false"/"input" sets it for this checkout. Line endings in WLED's web UI
    sources end up inside the firmware, so this is a build input.
    """
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=dest)
        run(["git", "remote", "add", "origin", repo], cwd=dest)
    if autocrlf is not None:
        run(["git", "config", "core.autocrlf", autocrlf], cwd=dest)
        # renormalise the working tree for the new setting
        run(["git", "rm", "-q", "--cached", "-r", "--ignore-unmatch", "."], cwd=dest)
    run(["git", "fetch", "-q", "--depth", "1", "origin", commit], cwd=dest)
    run(["git", "-c", "advice.detachedHead=false", "checkout", "-q", "--force", commit], cwd=dest)
    run(["git", "clean", "-q", "-fdx", "-e", ".pio", "-e", "node_modules"], cwd=dest)
    head = run(["git", "rev-parse", "HEAD"], cwd=dest, capture=True)
    if head != commit:
        raise SystemExit(f"checkout mismatch: wanted {commit}, got {head}")


def apply_pins(text: str, pins: dict[str, str]) -> tuple[str, list[str]]:
    """Pin git URLs to commits: `url` or `url#ref` becomes `url#commit`.

    Returns the new text and the URLs that were found in it.
    """
    hits = []
    for url, commit in pins.items():
        pattern = re.compile(re.escape(url) + r"(#[^\s;]+)?(?=[\s;]|$)", re.MULTILINE)
        if pattern.search(text):
            hits.append(url)
            text = pattern.sub(f"{url}#{commit}", text)
    return text, hits


def add_usermods(override: str, env_name: str, paths: list[Path]) -> str:
    """Append local usermods (symlink://) to custom_usermods in [env:<env_name>]."""
    if not paths:
        return override
    lines = override.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[env:{env_name}]"), None)
    if start is None:
        raise SystemExit(f"[env:{env_name}] not found in the override")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    key = next((i for i in range(start, end) if lines[i].split("=")[0].strip() == "custom_usermods"), None)
    if key is None:
        raise SystemExit(f"custom_usermods not found in [env:{env_name}]")
    # continuation lines of the value are indented
    j = key + 1
    while j < end and lines[j][:1] in (" ", "\t") and lines[j].strip():
        j += 1
    extra = [f"  symlink://{p.resolve().as_posix()}" for p in paths]
    return "\n".join(lines[:j] + extra + lines[j:]) + "\n"


LIB_DIR_RE = re.compile(r"^lib[0-9a-f]{3}$")


def ar_members(path: Path):
    """Yield (name, bytes) for each member of a GNU/BSD ar archive."""
    data = path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        return
    off, longnames = 8, b""
    while off + 60 <= len(data):
        hdr = data[off:off + 60]
        name = hdr[:16].decode("ascii", "replace").strip()
        size = int(hdr[48:58].decode().strip())
        body = data[off + 60: off + 60 + size]
        off += 60 + size + (size & 1)
        if name == "//":
            longnames = body
            continue
        if name in ("/", "/SYM64/"):
            continue
        if name.startswith("/") and name[1:].isdigit():
            i = int(name[1:])
            name = longnames[i:longnames.index(b"/\n", i)].decode()
        yield name.rstrip("/"), body


def object_manifest(build_dir: Path) -> dict[str, str]:
    """Hash every object file and archive member, keyed by a build-independent path.

    PlatformIO puts each library in a folder named lib<3 hex digits>, numbered in
    the order libraries are found; that folder is dropped from the key so that
    adding a library doesn't rename every other object.
    """
    out: dict[str, str] = {}
    for f in sorted(build_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = [p for p in f.relative_to(build_dir).parts if not LIB_DIR_RE.match(p)]
        key = "/".join(rel)
        if f.suffix == ".o":
            out[key] = hashlib.sha256(f.read_bytes()).hexdigest()
        elif f.suffix == ".a":
            for name, body in ar_members(f):
                out[f"{key}:{name}"] = hashlib.sha256(body).hexdigest()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pins", type=Path)
    ap.add_argument("--work", type=Path, help="work tree (default: work/<name>)")
    ap.add_argument("--out", type=Path, help="output dir (default: out/<name>-<host>)")
    ap.add_argument("--label", default=None, help="extra label for the output dir")
    ap.add_argument("--clean", action="store_true",
                    help="remove the previous build output first, so every object is compiled anew")
    ap.add_argument("--usermod", type=Path, action="append", default=[],
                    help="a local usermod folder to add to the build (repeatable)")
    ap.add_argument("--autocrlf", choices=["true", "false", "input"], default=None,
                    help="git core.autocrlf for the WLED checkout (default: the host's)")
    args = ap.parse_args()

    pins = json.loads(args.pins.read_text())
    name = pins["name"]
    host = f"{platform.system().lower()}-{platform.machine().lower()}"
    label = f"{name}-{host}" + (f"-{args.label}" if args.label else "")
    work = (args.work or REPO_ROOT / "work" / name).resolve()
    out = (args.out or REPO_ROOT / "out" / label).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # 1. WLED at the pinned commit
    wled = work / "wled"
    autocrlf = args.autocrlf or pins.get("checkout", {}).get("autocrlf")
    checkout(pins["wled"]["repo"], pins["wled"]["commit"], wled, autocrlf)

    # 2. the vendor's override at its pinned commit, with unpinned usermods pinned
    ov = pins["override"]
    raw = ov["repo"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    ov_src = out / "platformio_override.original.ini"
    download(f"{raw}/{ov['commit']}/{ov['path']}", ov_src)
    url_pins = pins.get("pins", {})
    override, hits_ov = apply_pins(ov_src.read_text(encoding="utf-8"), url_pins)
    override = add_usermods(override, ov["env"], args.usermod)
    (wled / "platformio_override.ini").write_text(override, encoding="utf-8", newline="\n")
    (out / "platformio_override.ini").write_text(override, encoding="utf-8", newline="\n")
    # WLED's own platformio.ini may fetch branches too (e.g. QuickESPNow#optional-debug)
    pio_ini = wled / "platformio.ini"
    pio_text, hits_pio = apply_pins(pio_ini.read_bytes().decode("utf-8"), url_pins)
    if hits_pio:
        pio_ini.write_bytes(pio_text.encode("utf-8"))
    missing = set(url_pins) - set(hits_ov) - set(hits_pio)
    if missing:
        raise SystemExit(f"pin targets not found: {sorted(missing)}")

    # 3. environment: a fixed UI build time, an isolated PlatformIO core
    env = os.environ.copy()
    env["WLED_STUDIO_WEB_BUILD_TIME"] = str(pins["web_build_time"])
    if "gzip_os" in pins:
        env["WLED_STUDIO_GZIP_OS"] = str(pins["gzip_os"])
    fixtime = (REPO_ROOT / "studio" / "fixtime.js").resolve()
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + f' --require "{fixtime.as_posix()}"').strip()
    env.setdefault("PLATFORMIO_CORE_DIR", str(work / "pio-core"))

    # 4. build, with libraries resolved afresh (a cached branch checkout would hide the pins)
    shutil.rmtree(wled / ".pio" / "libdeps" / ov["env"], ignore_errors=True)
    if args.clean:
        shutil.rmtree(wled / ".pio" / "build" / ov["env"], ignore_errors=True)
    run([sys.executable, "-m", "platformio", "run", "-e", ov["env"], "-d", str(wled)], env=env)

    build_dir = wled / ".pio" / "build" / ov["env"]
    for f in ("firmware.bin", "firmware.elf"):
        shutil.copy2(build_dir / f, out / f)
    (out / "objects.json").write_text(json.dumps(object_manifest(build_dir), indent=1) + "\n")

    # 5. compare with the vendor's image
    ref = pins.get("reference")
    report = {
        "pins": pins["name"],
        "host": host,
        "python": sys.version.split()[0],
        "platformio": tool_version([sys.executable, "-m", "platformio", "--version"]),
        "node": tool_version(["node", "--version"]),
        "npm": tool_version(["npm", "--version"]),
        "git": tool_version(["git", "--version"]),
        "wled_commit": pins["wled"]["commit"],
        "override_commit": ov["commit"],
        "extra_usermods": [p.name for p in args.usermod],
        "autocrlf": run(["git", "config", "--get", "core.autocrlf"], cwd=wled, capture=True)
        if subprocess.run(["git", "config", "--get", "core.autocrlf"], cwd=wled,
                          stdout=subprocess.DEVNULL).returncode == 0 else "unset",
        "firmware_sha256": sha256(out / "firmware.bin"),
        "firmware_size": (out / "firmware.bin").stat().st_size,
    }
    if ref:
        ref_bin = out / "reference.bin"
        if not ref_bin.exists() or sha256(ref_bin) != ref["sha256"]:
            download(ref["url"], ref_bin)
        if sha256(ref_bin) != ref["sha256"]:
            raise SystemExit("reference image does not match its pinned sha256")
        report["reference_sha256"] = ref["sha256"]
        report["reference_size"] = ref["size"]
        report["identical"] = report["firmware_sha256"] == ref["sha256"]
        # explain any difference (see imgdiff.py), and test the ELF-hash-only hypothesis
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import imgdiff  # noqa: E402
        a, b = imgdiff.parse(out / "firmware.bin"), imgdiff.parse(ref_bin)
        diff = imgdiff.compare(a, b, pins.get("web_build_time"))
        report["diff_summary"] = diff["summary"]
        report["diff_layout"] = diff["layout"]
        same_layout = not diff["layout"] and len(a.raw) == len(b.raw)
        report["identical_except_elf_sha256"] = bool(
            same_layout and imgdiff.transplant_elf_sha(a, b) == b.raw)
    (out / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
