#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""Compare the object manifests (objects.json) of two builds.

build.py writes objects.json: a sha256 for every object file and archive member
the linker used. For step 3 of the chain of trust (custom vs stock, same host,
same work tree, both built with --clean), every stock object must be
byte-identical in the custom build, and every new object must come from the
added usermods.

Usage:
  python studio/objdiff.py STOCK/objects.json CUSTOM/objects.json [--allow PREFIX ...]

--allow takes path prefixes (as they appear in the manifest) where new or changed
objects are expected, e.g. the usermod's folder name. Exit 0 when everything
outside those prefixes is identical, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stock", type=Path)
    ap.add_argument("custom", type=Path)
    ap.add_argument("--allow", action="append", default=[],
                    help="substring of manifest keys where differences are expected")
    args = ap.parse_args()

    a = json.loads(args.stock.read_text())
    b = json.loads(args.custom.read_text())
    allowed = lambda k: any(p in k for p in args.allow)  # noqa: E731
    same = [k for k in a if k in b and a[k] == b[k]]
    changed = sorted(k for k in a if k in b and a[k] != b[k])
    removed = sorted(set(a) - set(b))
    added = sorted(set(b) - set(a))
    bad = [k for k in changed + removed + added if not allowed(k)]

    # firmware.elf/bin and linker outputs aren't in the manifest; it covers linker inputs only
    print(f"stock: {len(a)} objects, custom: {len(b)} objects")
    print(f"identical: {len(same)}, changed: {len(changed)}, removed: {len(removed)}, added: {len(added)}")
    for label, keys in (("changed", changed), ("removed", removed), ("added", added)):
        for k in keys:
            print(f"  {label:<8} {'ok ' if allowed(k) else 'BAD'} {k}")
    print("RESULT: " + ("ONLY EXPECTED DIFFERENCES" if not bad else f"{len(bad)} UNEXPECTED DIFFERENCES"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
