#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""Reproduce a pinned WLED build and compare it with the vendor's published image.

Runs the same way on Linux and Windows. Every input comes from a pins file
(pins/*.json): the WLED commit, the vendor's platformio_override.ini at a commit,
pinned commits for any usermod the override fetches unpinned, and the UI build
time to stamp. Nothing is taken from the network unpinned, except PlatformIO's
own packages, which WLED's platformio.ini pins by version.

A pins file describes one vendor release: release-wide inputs, and one target
per board (the PlatformIO env), each with the vendor's image and the results
verified so far. Target keys override release keys. Any input can also be
overridden on the command line (--pin, --set), so a new vendor release can be
tried without a new pins file or a new builder image.

Usage:
  python studio/build.py pins/quinled-16.0.1.json --target dig-next-2 [--check]
  python studio/build.py PINS --target ENV --set web_build_time=1783528886 \
      --pin https://github.com/OWNER/REPO.git=COMMIT
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
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, capture: bool = False) -> str:
    print("+ " + " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=cwd, env=env, check=True,
                         stdout=subprocess.PIPE if capture else None, text=True,
                         encoding="utf-8" if capture else None, errors="replace" if capture else None)
    return res.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def dep_fingerprint(pins: dict, override: str, pio_ini: str) -> str:
    """Inputs that decide PlatformIO's resolved dependency tree."""
    payload = {
        "wled_commit": pins["wled"]["commit"],
        "override_commit": pins["override"]["commit"],
        "override": override,
        "pio_ini": pio_ini,
        "pins": pins.get("pins", {}),
        "usermods": pins.get("extra_usermods", []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def download(url: str, dest: Path, attempts: int = 3, sleep=time.sleep, offline: bool = False) -> None:
    """Fetch url to dest. A server error (5xx) or a network failure is retried with backoff:
    raw.githubusercontent.com answers 503 "Backend.max_conn reached" now and then, and one
    failed fetch shouldn't fail a firmware build. A 4xx fails at once."""
    if offline:
        raise SystemExit(f"offline build needs {url}, but {dest} is not cached")
    print(f"+ download {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "wled-studio"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == attempts:
                raise
            print(f"  {e.code} {e.reason}; retrying ({attempt}/{attempts})", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == attempts:
                raise
            print(f"  {e}; retrying ({attempt}/{attempts})", flush=True)
        sleep(5 * 2 ** (attempt - 1))


def tool_version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, shell=(os.name == "nt")).stdout.strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001 - report, don't fail
        return f"unavailable ({e.__class__.__name__})"


def checkout(repo: str, commit: str, dest: Path, autocrlf: str | None = None, origin_remote: bool = True,
             offline: bool = False) -> None:
    """Clone (or reuse) dest at exactly `commit`, with a clean tree.

    autocrlf: None keeps the host's git default (Git for Windows ships `true`);
    "true"/"false"/"input" sets it for this checkout. Line endings in WLED's web UI
    sources end up inside the firmware, so this is a build input.

    origin_remote: WLED's build stamps WLED_REPO from the checkout's "origin" remote
    (pio-scripts/set_metadata.py) unless the env defines it. A vendor tree without a
    GitHub origin gets "unknown"; with origin_remote=False the remote is named
    "upstream", so the stamp is "unknown" here too.
    """
    remote = "origin" if origin_remote else "upstream"
    if not (dest / ".git").exists():
        if offline:
            raise SystemExit(f"offline build needs a cached checkout at {dest}")
        dest.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=dest)
        run(["git", "remote", "add", remote, repo], cwd=dest)
    remotes = run(["git", "remote"], cwd=dest, capture=True).split()
    if remote not in remotes:
        old = "upstream" if remote == "origin" else "origin"
        run(["git", "remote", "rename", old, remote], cwd=dest)
    if autocrlf is not None:
        run(["git", "config", "core.autocrlf", autocrlf], cwd=dest)
        # renormalise the working tree for the new setting
        run(["git", "rm", "-q", "--cached", "-r", "--ignore-unmatch", "."], cwd=dest)
    if not offline:
        run(["git", "fetch", "-q", "--depth", "1", remote, commit], cwd=dest)
    elif subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=dest,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        raise SystemExit(f"offline checkout {dest} does not contain pinned commit {commit}")
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


def fix_usermod_case(override: str, env_name: str, usermod_dir: Path) -> tuple[str, list[str]]:
    """Match plain usermod names in [env:<env_name>] to WLED's folders case-insensitively.

    Vendors that build on Windows can write `temperature` for WLED's `Temperature`
    folder: Windows finds it, a case-sensitive file system doesn't. This picks
    the folder Windows would pick, so the build is the same; returns the fixes.
    """
    if not usermod_dir.is_dir():
        return override, []
    folders = {p.name.lower(): p.name for p in usermod_dir.iterdir() if p.is_dir()}
    lines = override.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[env:{env_name}]"), None)
    if start is None:
        return override, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    fixes: list[str] = []
    in_value = False
    for i in range(start + 1, end):
        line = lines[i]
        if line.split("=")[0].strip() == "custom_usermods" and "=" in line:
            key, _, value = line.partition("=")
            in_value = True
            prefix, tokens = key + "=", value
        elif in_value and line[:1] in (" ", "\t") and line.strip():
            prefix, tokens = "", line
        else:
            in_value = False
            continue
        new_tokens = []
        for tok in re.split(r"(\s+)", tokens):
            name = tok.strip()
            plain = name and "://" not in name and "@" not in name and "/" not in name and "=" not in name
            if plain and not (usermod_dir / name).is_dir():
                for cand in (name, f"{name}_v2", f"usermod_v2_{name}"):
                    real = folders.get(cand.lower())
                    if real and real != cand:
                        fixes.append(f"{name} -> {real}")
                        tok = tok.replace(name, real)
                        break
            new_tokens.append(tok)
        lines[i] = prefix + "".join(new_tokens)
    return "\n".join(lines) + "\n", fixes


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


SETTABLE = {"web_build_time": int, "gzip_os": int, "autocrlf": str}


def load_target(pins_path: Path, target: str | None, pin_args: list[str], set_args: list[str]) -> dict:
    """Merge release-wide keys with the target's, then the command-line overrides."""
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    targets = pins.get("targets", {})
    if not targets:
        raise SystemExit(f"{pins_path}: no targets")
    if target is None:
        if len(targets) != 1:
            raise SystemExit(f"{pins_path} has {len(targets)} targets; choose one with --target: "
                             + ", ".join(targets))
        target = next(iter(targets))
    if target not in targets:
        raise SystemExit(f"target {target!r} not in {pins_path}: " + ", ".join(targets))
    t = targets[target]
    merged = {k: v for k, v in pins.items() if k != "targets"}
    for k, v in t.items():
        if k == "pins":
            merged["pins"] = {**merged.get("pins", {}), **v}
        elif k == "checkout":
            merged["checkout"] = {**merged.get("checkout", {}), **v}
        else:
            merged[k] = v
    merged["target"] = target
    merged["env"] = t.get("env", target)
    overrides = {}
    for p in pin_args:
        url, _, commit = p.rpartition("=")
        if not url or not commit:
            raise SystemExit(f"--pin wants URL=COMMIT, got {p!r}")
        merged.setdefault("pins", {})[url] = commit
        overrides[f"pin:{url}"] = commit
    for kv in set_args:
        k, _, v = kv.partition("=")
        if k not in SETTABLE:
            raise SystemExit(f"--set accepts {', '.join(SETTABLE)}; got {k!r}")
        val = SETTABLE[k](v)
        if k == "autocrlf":
            merged.setdefault("checkout", {})["autocrlf"] = val
        else:
            merged[k] = val
        overrides[k] = val
    merged["overrides"] = overrides
    return merged


def toolchain_host() -> str:
    """The toolchain build PlatformIO picks: windows (x86-64 on any Windows), linux-<arch>."""
    if platform.system() == "Windows":
        return "windows"
    arch = platform.machine().lower()
    return f"linux-{ {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(arch, arch) }".replace(" ", "")


def check_expectations(report: dict, verified: dict) -> list[str]:
    """Compare a report with the target's verified results for this toolchain host."""
    exp = verified.get(report["toolchain_host"])
    if not exp:
        return [f"no verified result for toolchain host {report['toolchain_host']!r} yet"]
    problems = []
    if exp.get("matches_reference") and report.get("normalized_sha256") != report.get("reference_normalized_sha256"):
        problems.append("expected to match the vendor image (normalized), but it doesn't")
    want = exp.get("normalized_sha256")
    if want and report.get("normalized_sha256") != want:
        problems.append(f"normalized sha256 {report.get('normalized_sha256')} != expected {want}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pins", type=Path)
    ap.add_argument("--target", help="the board's PlatformIO env (required if the pins file has several)")
    ap.add_argument("--pin", action="append", default=[], metavar="URL=COMMIT",
                    help="pin a git dependency (overrides the pins file; repeatable)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override web_build_time, gzip_os or autocrlf")
    ap.add_argument("--check", action="store_true",
                    help="fail (exit 3) unless the result matches the target's verified results")
    ap.add_argument("--work", type=Path, help="work tree (default: work/<name>)")
    ap.add_argument("--out", type=Path, help="output dir (default: out/<name>-<host>)")
    ap.add_argument("--label", default=None, help="extra label for the output dir")
    ap.add_argument("--clean", action="store_true",
                    help="remove the previous build output first, so every object is compiled anew")
    ap.add_argument("--offline", action="store_true",
                    help="prove a rebuild from cached git/package inputs; fail instead of fetching")
    ap.add_argument("--usermod", type=Path, action="append", default=[],
                    help="a local usermod folder to add to the build (repeatable)")
    ap.add_argument("--autocrlf", choices=["true", "false", "input"], default=None,
                    help="git core.autocrlf for the WLED checkout (default: the host's)")
    args = ap.parse_args()

    pins = load_target(args.pins, args.target, args.pin, args.set)
    name = pins["name"]
    host = f"{platform.system().lower()}-{platform.machine().lower()}"
    label = f"{name}-{pins['target']}-{host}" + (f"-{args.label}" if args.label else "")
    work = (args.work or REPO_ROOT / "work" / name).resolve()
    out = (args.out or REPO_ROOT / "out" / label).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # 1. WLED at the pinned commit
    wled = work / "wled"
    autocrlf = args.autocrlf or pins.get("checkout", {}).get("autocrlf")
    checkout(pins["wled"]["repo"], pins["wled"]["commit"], wled, autocrlf,
             pins.get("checkout", {}).get("origin_remote", True), args.offline)

    # 2. the vendor's override at its pinned commit, with unpinned usermods pinned
    ov = pins["override"]
    raw = ov["repo"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    ov_src = out / "platformio_override.original.ini"
    ov_url = f"{raw}/{ov['commit']}/{ov['path']}"
    ov_source = out / "platformio_override.original.source.json"
    if args.offline:
        if not ov_src.exists() or not ov_source.exists():
            raise SystemExit(f"offline build needs cached override {ov_src} and its provenance")
        source = json.loads(ov_source.read_text(encoding="utf-8"))
        if source.get("url") != ov_url or source.get("sha256") != sha256(ov_src):
            raise SystemExit("offline override cache does not match the pinned source")
    else:
        download(ov_url, ov_src)
        ov_source.write_text(json.dumps({"url": ov_url, "sha256": sha256(ov_src)}, indent=1) + "\n")
    url_pins = pins.get("pins", {})
    override, hits_ov = apply_pins(ov_src.read_text(encoding="utf-8"), url_pins)
    override = add_usermods(override, pins["env"], args.usermod)
    override, case_fixes = fix_usermod_case(override, pins["env"], wled / "usermods")
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
    # WLED's UI build needs no npm install scripts (66 packages would run theirs)
    env.setdefault("NPM_CONFIG_IGNORE_SCRIPTS", "true")
    if args.offline:
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = env["http_proxy"] = env["https_proxy"] = "http://127.0.0.1:9"
        env["ALL_PROXY"] = env["all_proxy"] = "socks5://127.0.0.1:9"
        env["NO_PROXY"] = env["no_proxy"] = ""
        env["NPM_CONFIG_OFFLINE"] = "true"
        env["GIT_ALLOW_PROTOCOL"] = "file"

    # 4. build, with libraries resolved afresh (a cached branch checkout would hide the pins)
    pins_for_deps = {**pins, "extra_usermods": [p.resolve().as_posix() for p in args.usermod]}
    deps_hash = dep_fingerprint(pins_for_deps, override, pio_text)
    deps_marker = wled / ".pio" / "libdeps" / pins["env"] / ".wled-studio-deps.json"
    if args.offline:
        try:
            cached_deps = json.loads(deps_marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SystemExit("offline build has no verified PlatformIO dependency cache") from None
        if cached_deps.get("fingerprint") != deps_hash:
            raise SystemExit("offline PlatformIO dependency cache does not match the pinned inputs")
    if not args.offline:
        # Fresh online builds must resolve libraries from their pinned URLs. An offline proof
        # deliberately uses the last resolved, pinned tree instead of erasing the only cache.
        shutil.rmtree(wled / ".pio" / "libdeps" / pins["env"], ignore_errors=True)
    if args.clean or args.offline:
        shutil.rmtree(wled / ".pio" / "build" / pins["env"], ignore_errors=True)
    try:
        run([sys.executable, "-m", "platformio", "run", "-e", pins["env"], "-d", str(wled)], env=env)
    except subprocess.CalledProcessError:
        if args.offline:
            raise SystemExit(
                "offline build failed: the cached PlatformIO checkout is incomplete; "
                "run this target once online to populate every package and framework library"
            ) from None
        raise
    if not args.offline:
        deps_marker.parent.mkdir(parents=True, exist_ok=True)
        deps_marker.write_text(json.dumps({"fingerprint": deps_hash, "built": True}, indent=1) + "\n")

    build_dir = wled / ".pio" / "build" / pins["env"]
    for f in ("firmware.bin", "firmware.elf"):
        shutil.copy2(build_dir / f, out / f)
    (out / "objects.json").write_text(json.dumps(object_manifest(build_dir), indent=1) + "\n")
    # the versions PlatformIO resolved, including ranges that can still float
    # (UTF-8: the listing draws a tree, which Windows' default console encoding can't encode)
    try:
        pkgs = run([sys.executable, "-m", "platformio", "pkg", "list", "-e", pins["env"], "-d", str(wled)],
                   env={**env, "PYTHONIOENCODING": "utf-8"}, capture=True)
        (out / "packages.txt").write_text(pkgs + "\n", encoding="utf-8")
    except subprocess.CalledProcessError as e:
        print(f"warning: could not list packages ({e})", flush=True)

    # the effect list the image will report, for wled-studio's preflight (best effort: a missing
    # manifest is recorded, and the build still counts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import manifest as fxmanifest  # noqa: E402
    try:
        m = fxmanifest.from_build(wled, pins["env"], [p.resolve() for p in args.usermod], env)
        (out / "effects.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest_status = f"ok, {len(m['effects'])} effects"
        # the engine's flags, for building its virtual twin (virtual/, studio/virtual_check.py)
        (out / "fx_flags.json").write_text(json.dumps(fxmanifest.fx_defines(wled), indent=1) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - recorded in the report
        manifest_status = f"failed: {e.__class__.__name__}: {e}"[:500]
        print(f"warning: no effect manifest ({manifest_status})", flush=True)

    # 5. compare with the vendor's image
    ref = pins.get("reference")
    import imgdiff  # noqa: E402
    ours = imgdiff.parse(out / "firmware.bin")
    report = {
        "pins": pins["name"],
        "target": pins["target"],
        "overrides": pins["overrides"],
        "host": host,
        "toolchain_host": toolchain_host(),
        "in_container": bool(os.environ.get("WLED_STUDIO_CONTAINER")),
        "offline": args.offline,
        "python": sys.version.split()[0],
        "platformio": tool_version([sys.executable, "-m", "platformio", "--version"]),
        "node": tool_version(["node", "--version"]),
        "npm": tool_version(["npm", "--version"]),
        "git": tool_version(["git", "--version"]),
        "wled_commit": pins["wled"]["commit"],
        "override_commit": ov["commit"],
        "env": pins["env"],
        "extra_usermods": [p.name for p in args.usermod],
        "effects_manifest": manifest_status,
        "usermod_case_fixes": case_fixes,
        "autocrlf": run(["git", "config", "--get", "core.autocrlf"], cwd=wled, capture=True)
        if subprocess.run(["git", "config", "--get", "core.autocrlf"], cwd=wled,
                          stdout=subprocess.DEVNULL).returncode == 0 else "unset",
        "firmware_sha256": sha256(out / "firmware.bin"),
        "firmware_size": (out / "firmware.bin").stat().st_size,
        "normalized_sha256": imgdiff.normalized_sha256(ours),
    }
    if ref:
        ref_bin = out / "reference.bin"
        if not ref_bin.exists() or sha256(ref_bin) != ref["sha256"]:
            download(ref["url"], ref_bin, offline=args.offline)
        if sha256(ref_bin) != ref["sha256"]:
            raise SystemExit("reference image does not match its pinned sha256")
        report["reference_sha256"] = ref["sha256"]
        report["reference_size"] = ref["size"]
        report["identical"] = report["firmware_sha256"] == ref["sha256"]
        # explain any difference (see imgdiff.py), and test the ELF-hash-only hypothesis
        a, b = ours, imgdiff.parse(ref_bin)
        report["reference_normalized_sha256"] = imgdiff.normalized_sha256(b)
        diff = imgdiff.compare(a, b, pins.get("web_build_time"))
        report["diff_summary"] = diff["summary"]
        report["diff_layout"] = diff["layout"]
        same_layout = not diff["layout"] and len(a.raw) == len(b.raw)
        report["identical_except_elf_sha256"] = bool(
            same_layout and imgdiff.transplant_elf_sha(a, b) == b.raw)
    report["check"] = check_expectations(report, pins.get("verified", {}))
    (out / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if args.check and report["check"]:
        print("CHECK FAILED: " + "; ".join(report["check"]), flush=True)
        return 3
    if args.check:
        print("CHECK PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
