#!/usr/bin/env python3
"""Compare two ESP32 application images and explain every byte that differs.

An ESP32 app image is a 24-byte header, a list of segments (load address,
length, data), a checksum byte padded to 16 bytes, and an optional appended
SHA-256. This tool parses both images, compares them segment by segment, and
classifies each differing range:

  checksum / sha256   the image's own integrity fields (follow from any change)
  web-build-time      WLED's WEB_BUILD_TIME stamp (4 bytes)
  toolchain-path      a string carrying the toolchain's build-host path
  gzip                a gzip stream (WLED's web UI); compared after decompressing
  unexplained         anything else

Exit status: 0 if identical, 1 if every difference is explained, 2 if any byte is
unexplained or the layouts differ.

Usage:
  python studio/imgdiff.py A.bin B.bin [--web-build-time N] [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ESP_MAGIC = 0xE9


@dataclass
class Segment:
    index: int
    load_addr: int
    file_offset: int  # offset of the segment's data in the image file
    data: bytes


@dataclass
class Image:
    path: Path
    raw: bytes
    header: bytes
    ext_header: bytes
    segments: list[Segment] = field(default_factory=list)
    checksum_offset: int = 0
    sha256_offset: int | None = None


def parse(path: Path) -> Image:
    raw = path.read_bytes()
    if raw[0] != ESP_MAGIC:
        raise SystemExit(f"{path}: not an ESP image (magic {raw[0]:#x})")
    nseg = raw[1]
    img = Image(path=path, raw=raw, header=raw[:8], ext_header=raw[8:24])
    off = 24
    for i in range(nseg):
        addr, length = struct.unpack_from("<II", raw, off)
        img.segments.append(Segment(i, addr, off + 8, raw[off + 8: off + 8 + length]))
        off += 8 + length
    # checksum byte sits at the last byte of the next 16-byte boundary
    pad = 15 - (off % 16)
    img.checksum_offset = off + pad
    hash_appended = raw[23] == 1
    if hash_appended:
        img.sha256_offset = img.checksum_offset + 1
    return img


def diff_ranges(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """Maximal ranges [start, end) where a and b differ (same length assumed)."""
    out, start = [], None
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, min(len(a), len(b))))
    return out


def merge_close(ranges: list[tuple[int, int]], gap: int = 8) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for s, e in ranges:
        if merged and s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def gzip_streams(data: bytes) -> list[tuple[int, int, bytes]]:
    """(start, end, decompressed) for every gzip stream found in data."""
    found = []
    for m in re.finditer(rb"\x1f\x8b\x08", data):
        start = m.start()
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            payload = d.decompress(data[start:start + 4_000_000])
        except zlib.error:
            continue
        if not d.eof:
            continue
        end = len(data[start:start + 4_000_000]) - len(d.unused_data) + start
        found.append((start, end, payload))
    return found


TOOLCHAIN_RE = re.compile(rb"HOST-x86_64-[A-Za-z0-9_-]+|/builds/idf/crosstool-NG[^\x00]*")


def classify_range(a: bytes, b: bytes, s: int, e: int, wbt: int | None,
                   gz_a: list, gz_b: list) -> str:
    if wbt is not None:
        stamp = struct.pack("<I", wbt)
        for buf in (a, b):
            i = buf.find(stamp, max(0, s - 4), e + 4)
            if i != -1 and i <= s and e <= i + 4:
                return "web-build-time"
    for buf in (a, b):
        lo, hi = max(0, s - 160), min(len(buf), e + 160)
        for m in TOOLCHAIN_RE.finditer(buf, lo, hi):
            if m.start() <= e and s <= m.end():
                return "toolchain-path"
    for (gs, ge, pa) in gz_a:
        if gs <= s and e <= ge:
            for (hs, he, pb) in gz_b:
                if hs == gs:
                    return "gzip:same-content" if pa == pb else "gzip:content-differs"
            return "gzip:unmatched"
    return "unexplained"


def compare(a: Image, b: Image, wbt: int | None) -> dict:
    report: dict = {"a": str(a.path), "b": str(b.path),
                    "size_a": len(a.raw), "size_b": len(b.raw),
                    "identical": a.raw == b.raw, "layout": [], "ranges": [], "summary": {}}
    if report["identical"]:
        return report

    if a.header[:4] != b.header[:4] or a.ext_header != b.ext_header:
        report["layout"].append("header differs")
    if len(a.segments) != len(b.segments):
        report["layout"].append(f"segment count {len(a.segments)} vs {len(b.segments)}")
    for sa, sb in zip(a.segments, b.segments):
        row = {"segment": sa.index, "addr_a": hex(sa.load_addr), "addr_b": hex(sb.load_addr),
               "len_a": len(sa.data), "len_b": len(sb.data)}
        if sa.load_addr != sb.load_addr or len(sa.data) != len(sb.data):
            row["mismatch"] = True
            report["layout"].append(row)
            continue
        gz_a, gz_b = gzip_streams(sa.data), gzip_streams(sb.data)
        for s, e in merge_close(diff_ranges(sa.data, sb.data)):
            kind = classify_range(sa.data, sb.data, s, e, wbt, gz_a, gz_b)
            report["ranges"].append({
                "segment": sa.index, "addr": hex(sa.load_addr + s), "file_offset": hex(sa.file_offset + s),
                "length": e - s, "kind": kind,
                "a": sa.data[s:min(e, s + 24)].hex(), "b": sb.data[s:min(e, s + 24)].hex(),
            })

    if a.raw[a.checksum_offset] != b.raw[b.checksum_offset]:
        report["ranges"].append({"kind": "checksum", "file_offset": hex(a.checksum_offset), "length": 1})
    if a.sha256_offset and b.sha256_offset:
        if a.raw[a.sha256_offset:a.sha256_offset + 32] != b.raw[b.sha256_offset:b.sha256_offset + 32]:
            report["ranges"].append({"kind": "sha256", "file_offset": hex(a.sha256_offset), "length": 32})

    summary: dict[str, int] = {}
    for r in report["ranges"]:
        summary[r["kind"]] = summary.get(r["kind"], 0) + r["length"]
    report["summary"] = summary
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--web-build-time", type=int, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--max-ranges", type=int, default=40)
    args = ap.parse_args()

    a, b = parse(args.a), parse(args.b)
    rep = compare(a, b, args.web_build_time)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=2) + "\n")

    print(f"A: {rep['a']} ({rep['size_a']} B, {len(a.segments)} segments)")
    print(f"B: {rep['b']} ({rep['size_b']} B, {len(b.segments)} segments)")
    if rep["identical"]:
        print("IDENTICAL")
        return 0
    for item in rep["layout"]:
        print(f"LAYOUT: {item}")
    for r in rep["ranges"][: args.max_ranges]:
        print(f"  {r['kind']:<22} off={r.get('file_offset')} len={r['length']}"
              + (f" a={r['a']} b={r['b']}" if "a" in r else ""))
    if len(rep["ranges"]) > args.max_ranges:
        print(f"  ... {len(rep['ranges']) - args.max_ranges} more ranges")
    print("SUMMARY (bytes by kind): " + json.dumps(rep["summary"]))
    bad = rep["layout"] or any(k in ("unexplained", "gzip:content-differs", "gzip:unmatched")
                               for k in rep["summary"])
    print("RESULT: " + ("UNEXPLAINED DIFFERENCES" if bad else "ALL DIFFERENCES EXPLAINED"))
    return 2 if bad else 1


if __name__ == "__main__":
    sys.exit(main())
