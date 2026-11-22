#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""Help write a pins file for a vendor release.

Subcommands:

  targets  list the release's images and map each to its PlatformIO env, by the
           WLED_RELEASE_NAME the env sets in the vendor's override; prints a
           "targets" object for the pins file (reference URL, sha256, size).

  stamps   list candidate WEB_BUILD_TIME values in a vendor image: every
           little-endian 32-bit value in the image that falls in a date range
           (the stamp is a UNIX time written by WLED's UI build).

  stamp-at read the vendor's WEB_BUILD_TIME at the offset where our own build
           has its stamp. Needs a build of ours with the same layout up to the
           stamp (same inputs apart from the stamp); much sharper than `stamps`,
           which finds many chance matches in code.

  refs     list commits of a git branch (newest first) up to a date: candidates
           for a dependency the build fetches by branch.

Usage:
  python studio/discover.py targets --release https://github.com/OWNER/REPO/releases/tag/TAG \\
      --override https://github.com/OWNER/REPO/blob/COMMIT/platformio_override.ini
  python studio/discover.py stamps IMAGE.bin --from 2026-06-01 --to 2026-11-01
  python studio/discover.py stamp-at OURS.bin VENDOR.bin --ours 1783528886
  python studio/discover.py refs https://github.com/OWNER/REPO.git BRANCH --until 2026-10-27
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import struct
import sys
import urllib.request
from pathlib import Path

API = "https://api.github.com"


def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "wled-studio",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "wled-studio"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


# --- override parsing --------------------------------------------------------

ENV_RE = re.compile(r"^\[env:([^\]]+)\]\s*$", re.M)
RELEASE_RE = re.compile(r'WLED_RELEASE_NAME=\\?"?\\?"([^"\\]+)')


def release_names(override: str) -> dict[str, str]:
    """env name -> WLED_RELEASE_NAME, for every env that sets one."""
    parts = ENV_RE.split(override)
    out = {}
    for i in range(1, len(parts), 2):
        m = RELEASE_RE.search(parts[i + 1])
        if m:
            out[parts[i]] = m.group(1)
    return out


def match_assets(assets: list[dict], names: dict[str, str], version: str) -> dict[str, dict]:
    """Map release assets named WLED_<version>_<release name>.bin to envs."""
    by_release = {rn: env for env, rn in names.items()}
    targets = {}
    for a in assets:
        m = re.fullmatch(rf"WLED_{re.escape(version)}_(.+)\.bin", a["name"])
        if not m:
            continue
        env = by_release.get(m.group(1))
        if env is None:
            continue
        digest = (a.get("digest") or "").removeprefix("sha256:")
        targets[env] = {"reference": {"url": a["browser_download_url"], "sha256": digest,
                                      "size": a["size"]},
                        "built": a.get("updated_at")}
    return dict(sorted(targets.items()))


# --- stamps ------------------------------------------------------------------

def stamp_candidates(data: bytes, start: int, end: int) -> list[tuple[int, int]]:
    """(offset, value) for each LE uint32 in [start, end], at any byte offset."""
    out = []
    for off in range(0, len(data) - 3):
        v = struct.unpack_from("<I", data, off)[0]
        if start <= v <= end:
            out.append((off, v))
    return out


def stamp_at(ours: bytes, vendor: bytes, our_stamp: int) -> list[tuple[int, int]]:
    """(offset, vendor value) at every offset where our image holds our_stamp."""
    key = struct.pack("<I", our_stamp)
    out, i = [], ours.find(key)
    while i != -1:
        if i + 4 <= len(vendor):
            out.append((i, struct.unpack_from("<I", vendor, i)[0]))
        i = ours.find(key, i + 1)
    return out


def to_epoch(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


# --- main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("targets")
    t.add_argument("--release", required=True)
    t.add_argument("--override", required=True)
    s = sub.add_parser("stamps")
    s.add_argument("image", type=Path)
    s.add_argument("--from", dest="start", required=True)
    s.add_argument("--to", dest="end", required=True)
    sa = sub.add_parser("stamp-at")
    sa.add_argument("ours", type=Path)
    sa.add_argument("vendor", type=Path)
    sa.add_argument("--ours", dest="our_stamp", type=int, required=True)
    r = sub.add_parser("refs")
    r.add_argument("repo")
    r.add_argument("branch")
    r.add_argument("--until", required=True)
    args = ap.parse_args()

    if args.cmd == "targets":
        m = re.match(r"https://github.com/([^/]+/[^/]+)/releases/tag/(.+)$", args.release)
        if not m:
            raise SystemExit("--release must be a GitHub release URL")
        repo, tag = m.groups()
        rel = http_json(f"{API}/repos/{repo}/releases/tags/{tag}")
        raw = args.override.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
        names = release_names(http_text(raw))
        version = tag.lstrip("v")
        print(json.dumps(match_assets(rel["assets"], names, version), indent=2))
    elif args.cmd == "stamps":
        data = args.image.read_bytes()
        for off, v in stamp_candidates(data, to_epoch(args.start), to_epoch(args.end)):
            when = dt.datetime.fromtimestamp(v, dt.timezone.utc).isoformat()
            print(f"{off:#09x}  {v}  {when}")
    elif args.cmd == "stamp-at":
        for off, v in stamp_at(args.ours.read_bytes(), args.vendor.read_bytes(), args.our_stamp):
            when = dt.datetime.fromtimestamp(v, dt.timezone.utc).isoformat()
            print(f"{off:#09x}  {v}  {when}")
    elif args.cmd == "refs":
        m = re.match(r"https://github.com/([^/]+/[^/]+?)(\.git)?$", args.repo)
        if not m:
            raise SystemExit("repo must be a GitHub URL")
        commits = http_json(f"{API}/repos/{m.group(1)}/commits?sha={args.branch}&until={args.until}T23:59:59Z&per_page=30")
        for c in commits:
            print(f"{c['sha']}  {c['commit']['committer']['date']}  {c['commit']['message'].splitlines()[0]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # e.g. piped into head
        sys.exit(0)
