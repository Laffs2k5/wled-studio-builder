#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""The virtual check: a built image's twin runs every effect, before the image may be flashed.

    python3 studio/virtual_check.py --wled <checkout> --flags <fx_flags.json> --effects <effects.json>
        [--usermod <dir> ...] --out <dir> [--emsdk <dir>]

Builds the virtual WLED (virtual/) twice from the same checkout and the engine's own flags (the
build's fx_flags.json): stock, and with the usermods. Runs the smoke test on both and checks:
- the custom twin's effect list is the image's (its effects.json), id for id;
- no effect crashes in the custom twin that doesn't crash in the stock one (crashes WLED has on
  its own aren't the usermods' doing, and are reported, not failed).
Writes <out>/virtual-report.json and exits 0 when the check passes, 1 when it fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# the flags that shape the effect engine; the rest (the toolchain's, the IDF's, pins, names with
# spaces) would break the WebAssembly build or mean nothing there
KEEP = re.compile(r"^-D(WLED_\w+|USERMOD_\w+|BOARD_HAS_PSRAM)(=\S*)?$")


def engine_flags(defines: list[str]) -> list[str]:
    return [d for d in defines if KEEP.match(d)]


def build(out: Path, wled: Path, flags: list[str], usermods: list[Path], env: dict) -> None:
    cmd = ["bash", str(REPO / "virtual" / "build.sh"), str(out), str(wled), *map(str, usermods)]
    subprocess.run(cmd, check=True, env={**env, "VIRTUAL_FLAGS": " ".join(flags)})


def smoke(virtual: Path, env: dict, report: Path, effects: Path | None = None, known: Path | None = None) -> int:
    e = {**env, "VIRTUAL_DIR": str(virtual), "SMOKE_REPORT": str(report)}
    if effects:
        e["EFFECTS_JSON"] = str(effects)
    if known:
        e["KNOWN_CRASHES"] = str(known)
    r = subprocess.run(["node", "--test", str(REPO / "virtual" / "test" / "smoke.test.mjs")], env=e,
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout[-6000:])
    return r.returncode


def emsdk_env(emsdk: Path | None) -> dict:
    env = dict(os.environ)
    if emsdk is None:
        return env
    out = subprocess.run(["bash", "-c", f"source {shlex.quote(str(emsdk / 'emsdk_env.sh'))} >/dev/null 2>&1 && env -0"],
                         check=True, capture_output=True)
    for item in out.stdout.split(b"\0"):
        if b"=" in item:
            k, v = item.decode().split("=", 1)
            env[k] = v
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wled", type=Path, required=True)
    ap.add_argument("--flags", type=Path, required=True, help="the build's fx_flags.json")
    ap.add_argument("--effects", type=Path, required=True, help="the image's effects.json")
    ap.add_argument("--usermod", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--emsdk", type=Path, help="an Emscripten SDK to use (else em++ on the path)")
    a = ap.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    flags = engine_flags(json.loads(a.flags.read_text(encoding="utf-8")))
    env = emsdk_env(a.emsdk)
    report = {"flags": flags, "passed": False}
    try:
        build(out / "stock", a.wled, flags, [], env)
        smoke(out / "stock", env, out / "stock-smoke.json")
        stock = json.loads((out / "stock-smoke.json").read_text())
        known = out / "known-crashes.txt"
        known.write_text("\n".join(sorted({c[:c.index(":")] for c in stock["crashed"]})) + "\n")
        build(out / "custom", a.wled, flags, [u.resolve() for u in a.usermod], env)
        code = smoke(out / "custom", env, out / "custom-smoke.json", effects=a.effects.resolve(), known=known)
        custom = json.loads((out / "custom-smoke.json").read_text()) if (out / "custom-smoke.json").exists() else {}
        report.update({
            "passed": code == 0,
            "effects_run": len(custom.get("run", [])),
            "dark": custom.get("dark", []),
            "crashed_in_stock_too": stock["crashed"],
            "crashed": custom.get("crashed", []),
        })
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as e:
        report["error"] = f"{e.__class__.__name__}: {e}"[:1000]
    (out / "virtual-report.json").write_text(json.dumps(report, indent=1) + "\n")
    print("VIRTUAL CHECK", "PASSED" if report["passed"] else "FAILED", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
