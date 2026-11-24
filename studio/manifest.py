# SPDX-License-Identifier: EUPL-1.2
"""The effect list of a built image: id, name and metadata per effect, as /json/eff and
/json/fxdata will report them on the device. wled-studio checks a look library against it
before the image is flashed.

Built-in effects: WLED's FX.cpp is run through the preprocessor with the build's own compile
command (from PlatformIO's compile database), so the build's flags and #ifdefs are resolved.
Then setupEffectData() is replayed under WS2812FX::addEffect()'s rules:
  - the list starts as Solid followed by MODE_COUNT - 1 "RSVD" placeholders;
  - id 255 takes the first placeholder;
  - an id inside the list replaces a placeholder, and never an added effect;
  - an id at or past the end is appended at the end, whatever id was asked for.

Our own effects (usermods) register at runtime, so they are read by convention, the shape
wled-studio's templates use: a `constexpr uint8_t k...Id = N;`, a `const char k...Data[] PROGMEM
= "...";` and `addEffect(k...Id, &fn, k...Data)`. The usermod pads the list with "RSVD" up to N
first, so the effect lands at N.

  manifest.py <wled checkout> --env <env> [--usermod <dir>] [--out effects.json]
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

RESERVED = "RSVD"

_STRING = r'"(?:[^"\\]|\\.)*"'
_DATA_RE = re.compile(r"\b(_data_\w+)\s*\[\s*\][^=;{]*=\s*((?:" + _STRING + r"\s*)+);")
_CALL_RE = re.compile(r"\baddEffect\s*\(\s*(\w+)\s*,\s*&?\s*[\w:]+\s*,\s*(\w+)\s*\)")
_COUNT_RE = re.compile(r"\b_modeCount\s*\(\s*(\d+)\s*\)")


def c_string(literals: str) -> str:
    """The value of one or more adjacent C string literals."""
    out = []
    for lit in re.findall(_STRING, literals):
        body, i = lit[1:-1], 0
        while i < len(body):
            ch = body[i]
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            nxt = body[i + 1]
            if nxt == "x":
                m = re.match(r"[0-9a-fA-F]{1,2}", body[i + 2:])
                out.append(chr(int(m.group(0), 16)))
                i += 2 + len(m.group(0))
            elif nxt in "01234567":
                m = re.match(r"[0-7]{1,3}", body[i + 1:])
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
            else:
                out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt))
                i += 2
    return "".join(out)


def strip_comments(text: str) -> str:
    """C and C++ comments removed, string literals kept (the preprocessor's output has none,
    but a raw source can)."""
    return re.sub(_STRING + r"|//[^\n]*|/\*.*?\*/",
                  lambda m: m.group(0) if m.group(0).startswith('"') else " ", text, flags=re.S)


def data_strings(text: str) -> dict[str, str]:
    """`_data_X[] = "..."` definitions: name -> value."""
    return {m.group(1): c_string(m.group(2)) for m in _DATA_RE.finditer(text)}


def function_body(text: str, signature: str) -> str:
    """The body of the first function whose definition contains `signature`."""
    i = text.index(signature)
    i = text.index("{", i)
    depth, j = 0, i
    while True:
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1


def add_effect(effects: list[str], id_: int, data: str) -> int:
    """WS2812FX::addEffect(): where an effect lands (255 if it isn't added)."""
    if id_ == 255:
        id_ = next((i for i in range(1, len(effects)) if effects[i] == RESERVED), 255)
    if id_ < len(effects):
        if effects[id_] != RESERVED:
            return 255
        effects[id_] = data
        return id_
    if len(effects) < 255:
        effects.append(data)
        return len(effects) - 1
    return 255


def builtin_effects(preprocessed_fx: str) -> list[str]:
    """The effect list after setupEffectData(), from the preprocessed FX.cpp."""
    preprocessed_fx = strip_comments(preprocessed_fx)
    data = data_strings(preprocessed_fx)
    count = int(_COUNT_RE.search(preprocessed_fx).group(1))
    effects = [data["_data_FX_MODE_STATIC"]] + [RESERVED] * (count - 1)
    body = function_body(preprocessed_fx, "WS2812FX::setupEffectData()")
    for id_expr, name in _CALL_RE.findall(body):
        if not id_expr.isdigit():
            raise ValueError(f"setupEffectData: id {id_expr!r} isn't a number after preprocessing")
        add_effect(effects, int(id_expr), data[name])
    return effects


def usermod_effects(source: str) -> list[tuple[int, str]]:
    """(id, data) for each effect a usermod registers in the templates' fixed-id shape."""
    source = strip_comments(source)
    ids = {m.group(1): int(m.group(2)) for m in re.finditer(r"\bconstexpr\s+uint8_t\s+(\w+)\s*=\s*(\d+)\s*;", source)}
    datas = {m.group(1): c_string(m.group(2))
             for m in re.finditer(r"\bconst\s+char\s+(\w+)\s*\[\s*\][^=;{]*=\s*((?:" + _STRING + r"\s*)+);", source)}
    out = []
    # addEffect(kId, &fn, kData), or a helper called the same way (add_fixed(kId, &fn, kData))
    for id_expr, data_name in re.findall(r"\b\w+\s*\(\s*(\w+)\s*,\s*&\s*[\w:]+\s*,\s*(\w+)\s*\)", source):
        if id_expr in ids and data_name in datas:
            out.append((ids[id_expr], datas[data_name]))
    return out


def place_usermod(effects: list[str], id_: int, data: str) -> int:
    """The templates' registration: pad with RSVD up to the id, then add (255 if it can't)."""
    if len(effects) > id_:
        return 255
    while len(effects) < id_:
        effects.append(RESERVED)
    return add_effect(effects, id_, data)


def manifest(effects: list[str], source: dict) -> dict:
    out = []
    for i, d in enumerate(effects):
        name, _, meta = d.partition("@")
        out.append({"id": i, "name": name, "meta": meta})
    return {"schema": 1, "source": source, "effects": out}


# --- from a build ------------------------------------------------------------------

def compile_entry(db: list[dict], suffix: str) -> dict:
    for e in db:
        if Path(e["file"]).as_posix().endswith(suffix):
            return e
    raise KeyError(f"{suffix} isn't in the compile database")


def preprocess(entry: dict) -> str:
    """Run one compile command with -E instead of -c, and no -o."""
    args = entry.get("arguments") or shlex.split(entry["command"], posix=os.name != "nt")
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "-o":
            skip = True
            continue
        out.append("-E" if a == "-c" else a)
    r = subprocess.run(out, cwd=entry["directory"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"preprocessing failed: {r.stderr[-2000:]}")
    return r.stdout


def defines(entry: dict) -> list[str]:
    """The -D flags of one compile command, as "-DNAME" or "-DNAME=VALUE" (both of the forms
    compilers take, "-DX" and "-D X", normalised)."""
    args = entry.get("arguments") or shlex.split(entry["command"], posix=os.name != "nt")
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "-D" and i + 1 < len(args):
            out.append("-D" + args[i + 1])
            i += 2
            continue
        if a.startswith("-D") and len(a) > 2:
            out.append(a)
        i += 1
    return out


def fx_defines(wled: Path) -> list[str]:
    """FX.cpp's -D flags from the compile database from_build() wrote: what shapes the effect
    engine (the board, PSRAM, sound, the particle-system choices), for the virtual WLED."""
    db = json.loads((wled / "compile_commands.json").read_text(encoding="utf-8"))
    return defines(compile_entry(db, "wled00/FX.cpp"))


def from_build(wled: Path, env: str, usermods: list[Path], proc_env: dict | None = None) -> dict:
    """The manifest of the image just built in `wled` for `env` (PlatformIO's compile database
    is written for it; nothing is rebuilt)."""
    db_path = wled / "compile_commands.json"
    subprocess.run([sys.executable, "-m", "platformio", "run", "-e", env, "-d", str(wled), "-t", "compiledb"],
                   check=True, capture_output=True, env=proc_env)
    db = json.loads(db_path.read_text(encoding="utf-8"))
    effects = builtin_effects(preprocess(compile_entry(db, "wled00/FX.cpp")))
    placed = []
    for um in usermods:
        for src in sorted(um.glob("*.cpp")):
            for id_, data in usermod_effects(src.read_text(encoding="utf-8")):
                placed.append({"usermod": um.name, "id": id_, "landed": place_usermod(effects, id_, data)})
    return manifest(effects, {"env": env, "usermods": placed})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("wled", type=Path)
    ap.add_argument("--env", required=True)
    ap.add_argument("--usermod", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    m = from_build(a.wled, a.env, a.usermod)
    text = json.dumps(m, indent=1, ensure_ascii=False) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
