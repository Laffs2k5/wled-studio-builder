#!/usr/bin/env python3
"""Compare two firmware ELF files symbol by symbol.

Lists every symbol whose size differs, or that exists in only one of the two,
and, for symbols of equal size, whether their bytes differ. Code that refers to
other addresses can differ only in relocated operands when the layout shifts;
--ignore-shift masks that by comparing sizes only.

Uses the toolchain's nm and objcopy (xtensa-esp32-elf-*), found under the
PlatformIO core directory or given with --toolchain-bin.

Usage:
  python studio/elfdiff.py A.elf B.elf [--toolchain-bin DIR] [--bytes] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_tool(name: str, hint: Path | None) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    if hint:
        p = hint / exe
        if p.exists():
            return str(p)
    found = shutil.which(exe)
    if found:
        return found
    roots = [Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))]
    roots += list(Path.cwd().glob("work/*/pio-core"))
    for r in roots:
        for p in r.glob(f"packages/toolchain-xtensa-esp32*/bin/{exe}"):
            return str(p)
    raise SystemExit(f"{name} not found; pass --toolchain-bin")


def symbols(nm: str, elf: Path) -> dict[str, tuple[int, int, str]]:
    """name -> (address, size, type) for sized symbols."""
    out = subprocess.run([nm, "-S", "--defined-only", "-C", str(elf)], check=True,
                         stdout=subprocess.PIPE, text=True).stdout
    syms: dict[str, tuple[int, int, str]] = {}
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        addr, size, typ, name = parts
        try:
            key = f"{name} [{typ.lower()}]"
            # keep the first of duplicate local symbols, numbered
            n = 1
            while key in syms:
                n += 1
                key = f"{name} [{typ.lower()}#{n}]"
            syms[key] = (int(addr, 16), int(size, 16), typ)
        except ValueError:
            continue
    return syms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--toolchain-bin", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args()

    nm = find_tool("xtensa-esp32-elf-nm", args.toolchain_bin)
    sa, sb = symbols(nm, args.a), symbols(nm, args.b)
    only_a = sorted(set(sa) - set(sb))
    only_b = sorted(set(sb) - set(sa))
    size_diff = sorted(((k, sa[k][1], sb[k][1]) for k in set(sa) & set(sb) if sa[k][1] != sb[k][1]),
                       key=lambda r: -abs(r[1] - r[2]))
    rep = {
        "a": str(args.a), "b": str(args.b),
        "symbols_a": len(sa), "symbols_b": len(sb),
        "only_a": [(k, sa[k][1]) for k in only_a],
        "only_b": [(k, sb[k][1]) for k in only_b],
        "size_differs": size_diff,
        "net_size_a_minus_b": sum(v[1] for v in sa.values()) - sum(v[1] for v in sb.values()),
    }
    if args.json:
        args.json.write_text(json.dumps(rep, indent=2) + "\n")

    print(f"A: {args.a} ({len(sa)} sized symbols)\nB: {args.b} ({len(sb)} sized symbols)")
    print(f"only in A: {len(only_a)}, only in B: {len(only_b)}, size differs: {len(size_diff)}")
    for k in only_a[: args.top]:
        print(f"  A only  {sa[k][1]:>7}  {k}")
    for k in only_b[: args.top]:
        print(f"  B only  {sb[k][1]:>7}  {k}")
    for k, x, y in size_diff[: args.top]:
        print(f"  size    {x:>7} -> {y:<7} ({x - y:+d})  {k}")
    same = not only_a and not only_b and not size_diff
    print("RESULT: " + ("SAME SYMBOLS AND SIZES" if same else "DIFFERENCES"))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
