#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""The gate before a self-built image may be flashed (docs/chain-of-trust.md).

  1. Build the vendor's stock image and check it against the target's verified
     results for this toolchain host (build.py --check). On the vendor's host
     OS that means: identical to the vendor image apart from the ELF hash.
  2. Build the same target with your usermods added, in the same work tree.
     Both builds start clean, so every object is compiled anew.
  3. Compare the linker inputs (objects.json): every stock object must be
     byte-identical in the custom build; the only new objects must come from
     your usermods.
  4. The custom image must fit the app slot (app_slot_bytes in the pins file)
     with a margin.

Writes gate-report.json and exits 0 only if all four pass. The image to flash
is custom/firmware.bin next to the report.

Usage:
  python studio/gate.py PINS --target ENV --usermod DIR [--usermod DIR ...] [--work W] [--out OUT]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_FREE_BYTES = 64 * 1024  # keep this much of the app slot free


def compare_objects(stock: dict, custom: dict, allowed: list[str]) -> dict:
    """Linker inputs: identical, changed, removed, added; unexpected = outside the usermods."""
    def ok(k: str) -> bool:
        return any(part in allowed for part in k.split("/"))
    changed = sorted(k for k in stock if k in custom and stock[k] != custom[k])
    removed = sorted(set(stock) - set(custom))
    added = sorted(set(custom) - set(stock))
    unexpected = [k for k in changed + removed + added if not ok(k)]
    return {"identical": sum(1 for k in stock if custom.get(k) == stock[k]), "changed": changed,
            "removed": removed, "added": added, "unexpected": unexpected,
            "added_from_usermods": [k for k in added if ok(k)]}


def evaluate(stock_report: dict, custom_report: dict, objects: dict, slot: int | None) -> dict:
    checks = {
        "stock_matches_verified": not stock_report.get("check"),
        "only_usermod_objects_changed": not objects["unexpected"] and bool(objects["added_from_usermods"]),
        "fits_app_slot": slot is None or custom_report["firmware_size"] <= slot - MIN_FREE_BYTES,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_build(pins: Path, target: str, work: Path, out: Path, usermods: list[Path], check: bool) -> int:
    cmd = [sys.executable, str(HERE / "build.py"), str(pins), "--target", target, "--clean",
           "--work", str(work), "--out", str(out)]
    for u in usermods:
        cmd += ["--usermod", str(u)]
    if check:
        cmd.append("--check")
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main(argv: list[str] | None = None, builder=run_build) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pins", type=Path)
    ap.add_argument("--target", required=True)
    ap.add_argument("--usermod", type=Path, action="append", required=True)
    ap.add_argument("--work", type=Path, default=Path("work/gate"))
    ap.add_argument("--out", type=Path, default=Path("out/gate"))
    a = ap.parse_args(argv)

    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pins = json.loads(a.pins.read_text(encoding="utf-8"))
    slot = pins.get("targets", {}).get(a.target, {}).get("app_slot_bytes", pins.get("app_slot_bytes"))
    report: dict = {"pins": pins.get("name"), "target": a.target, "usermods": [u.name for u in a.usermod],
                    "app_slot_bytes": slot}

    rc = builder(a.pins, a.target, a.work, out / "stock", [], True)
    stock_path = out / "stock" / "build-report.json"
    if not stock_path.exists():
        report.update(passed=False, error=f"stock build failed (exit {rc})")
        return finish(out, report)
    stock = json.loads(stock_path.read_text())
    report["stock"] = {k: stock.get(k) for k in ("toolchain_host", "normalized_sha256", "firmware_size", "check",
                                                 "identical_except_elf_sha256")}

    rc = builder(a.pins, a.target, a.work, out / "custom", a.usermod, False)
    custom_path = out / "custom" / "build-report.json"
    if not custom_path.exists():
        report.update(passed=False, error=f"custom build failed (exit {rc})")
        return finish(out, report)
    custom = json.loads(custom_path.read_text())
    report["custom"] = {k: custom.get(k) for k in ("firmware_sha256", "normalized_sha256", "firmware_size")}

    objects = compare_objects(json.loads((out / "stock" / "objects.json").read_text()),
                              json.loads((out / "custom" / "objects.json").read_text()),
                              [u.name for u in a.usermod])
    report["objects"] = objects
    report.update(evaluate(stock, custom, objects, slot))
    if report["passed"]:
        report["firmware"] = "custom/firmware.bin"
    return finish(out, report)


def finish(out: Path, report: dict) -> int:
    (out / "gate-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report.get(k) for k in ("passed", "checks", "error")}, indent=2))
    print("GATE PASSED" if report.get("passed") else "GATE FAILED", flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
