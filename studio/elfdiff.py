#!/usr/bin/env python3
"""Compare two firmware ELF files symbol by symbol.

Lists every symbol whose size differs, or that exists in only one of the two.

Uses the toolchain's nm and objdump (xtensa-esp32-elf-*), found under the
PlatformIO core directory or given with --toolchain-bin.

With --code, it also disassembles both ELFs and compares every function's
instructions after normalising addresses (absolute addresses, branch targets and
literal-pool references), so a function that only moved compares equal, and a
function the compiler generated differently shows up.

Usage:
  python studio/elfdiff.py A.elf B.elf [--toolchain-bin DIR] [--code] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


FUNC_RE = re.compile(r"^([0-9a-f]{8}) <(.+)>:$")
INSN_RE = re.compile(r"^\s*[0-9a-f]+:\s+(.*)$")
ADDR_RE = re.compile(r"\b[0-9a-f]{8}\b( <[^>]*>)?|0x[0-9a-f]+|<[^>]*>")


def functions(objdump: str, elf: Path) -> dict[str, list[str]]:
    """name -> normalised instruction list, for every function in executable sections."""
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", "-C", str(elf)], check=True,
                         stdout=subprocess.PIPE, text=True, errors="replace").stdout
    funcs: dict[str, list[str]] = {}
    cur: list[str] | None = None
    for line in out.splitlines():
        m = FUNC_RE.match(line)
        if m:
            name = m.group(2)
            key, n = name, 1
            while key in funcs:
                n += 1
                key = f"{name}#{n}"
            cur = funcs.setdefault(key, [])
            continue
        if cur is None:
            continue
        m = INSN_RE.match(line)
        if m:
            cur.append(ADDR_RE.sub("@", m.group(1)).strip())
    return funcs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--toolchain-bin", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--code", action="store_true", help="compare normalised disassembly per function")
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
    if args.code:
        objdump = find_tool("xtensa-esp32-elf-objdump", args.toolchain_bin)
        fa, fb = functions(objdump, args.a), functions(objdump, args.b)
        common = set(fa) & set(fb)
        rep["code_only_a"] = sorted(set(fa) - set(fb))
        rep["code_only_b"] = sorted(set(fb) - set(fa))
        rep["code_differs"] = sorted(k for k in common if fa[k] != fb[k])
        rep["code_functions_compared"] = len(common)
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
    if args.code:
        print(f"code: {rep['code_functions_compared']} functions compared, "
              f"{len(rep['code_differs'])} differ, {len(rep['code_only_a'])} only in A, "
              f"{len(rep['code_only_b'])} only in B")
        for k in rep["code_differs"][: args.top]:
            print(f"  code differs  {k}")
        for k in rep["code_only_a"][: args.top]:
            print(f"  code A only   {k}")
        for k in rep["code_only_b"][: args.top]:
            print(f"  code B only   {k}")
    same = not only_a and not only_b and not size_diff
    if args.code:
        same = same and not rep["code_differs"] and not rep["code_only_a"] and not rep["code_only_b"]
    print("RESULT: " + ("SAME SYMBOLS AND SIZES" if same else "DIFFERENCES"))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
