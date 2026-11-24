#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2
"""A small job service around gate.py, for the wled-studio web app.

Runs inside the builder container, reachable only on the compose network. It
takes gate jobs (a pins file, a target, the usermods to add), runs them one at
a time (they share the work tree), and serves their reports, logs and, for
jobs that passed the gate, the firmware image.

  GET  /health
  GET  /targets               pins files, their targets, verified hosts
  GET  /usermods              usermod folders available to jobs
  POST /jobs                  {"pins": "x.json", "target": "env", "usermods": ["name", ...]}
  GET  /jobs                  all jobs, newest first
  GET  /jobs/<id>             one job: state (queued, running, passed, failed) and gate report
  GET  /jobs/<id>/log         the job's build log (last 200 kB)
  GET  /jobs/<id>/firmware.bin  only if the job passed the gate
  GET  /jobs/<id>/effects.json  the custom image's effect list (id, name, metadata), if it passed
  POST /previews              {"usermods": ["name", ...], "pins": "x.json"?}: compile them to
                              WebAssembly for the browser preview (preview/); Emscripten is
                              installed into the work volume on first use (EMSDK_VERSION). Exact
                              colours: WLED's colour code from the pins file's WLED commit
                              (fetched into the work volume once), see preview_pins()
  GET  /jobs/<id>/preview/preview.mjs, .../preview.wasm   a compiled preview

Settings (environment): WLED_STUDIO_PINS_DIR, WLED_STUDIO_USERMODS_DIRS (colon-
separated; default /effects and the bundled examples), WLED_STUDIO_JOBS_DIR
(/out/jobs), WLED_STUDIO_WORK (/work), WLED_STUDIO_SERVICE_TOKEN (optional
bearer token), WLED_STUDIO_SERVICE_BIND (0.0.0.0:8090), WLED_STUDIO_PREVIEW_PINS (the pins
file whose WLED gives previews exact colours; default: the newest).

Standard library only.
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}\.json$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
EMSDK_VERSION = os.environ.get("EMSDK_VERSION", "7.0.1")
PREVIEW_FILES = {"preview.mjs": "text/javascript; charset=utf-8", "preview.wasm": "application/wasm"}
MAX_BODY = 64 * 1024
LOG_TAIL = 200 * 1024


class Config:
    def __init__(self, env=os.environ):
        self.pins_dir = Path(env.get("WLED_STUDIO_PINS_DIR", HERE.parent / "pins"))
        dirs = env.get("WLED_STUDIO_USERMODS_DIRS", f"/effects:{HERE.parent / 'examples' / 'usermods'}")
        self.usermod_dirs = [Path(d) for d in dirs.split(":") if d]
        self.jobs_dir = Path(env.get("WLED_STUDIO_JOBS_DIR", "/out/jobs"))
        self.work = Path(env.get("WLED_STUDIO_WORK", "/work"))
        self.token = env.get("WLED_STUDIO_SERVICE_TOKEN") or None
        self.preview_pins = env.get("WLED_STUDIO_PREVIEW_PINS") or None
        host, _, port = env.get("WLED_STUDIO_SERVICE_BIND", "0.0.0.0:8090").rpartition(":")
        self.bind = (host or "0.0.0.0", int(port))


class BadRequest(ValueError):
    pass


def list_targets(cfg: Config) -> list[dict]:
    out = []
    for f in sorted(cfg.pins_dir.glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        for name, t in p.get("targets", {}).items():
            out.append({"pins": f.name, "release": p.get("name"), "target": name,
                        "verified": sorted(t.get("verified", {}))})
    return out


def list_usermods(cfg: Config) -> list[str]:
    names = set()
    for d in cfg.usermod_dirs:
        if d.is_dir():
            names.update(p.name for p in d.iterdir() if p.is_dir() and NAME_RE.match(p.name))
    return sorted(names)


def find_usermod(cfg: Config, name: str) -> Path:
    if not NAME_RE.match(name):
        raise BadRequest(f"bad usermod name {name!r}")
    for d in cfg.usermod_dirs:
        p = d / name
        if p.is_dir() and p.resolve().parent == d.resolve():
            return p
    raise BadRequest(f"no usermod {name!r}")


def validate_job(cfg: Config, body: object) -> dict:
    if not isinstance(body, dict) or set(body) - {"pins", "target", "usermods"}:
        raise BadRequest("expected {pins, target, usermods}")
    pins, target, usermods = body.get("pins"), body.get("target"), body.get("usermods")
    if not isinstance(pins, str) or not PINS_NAME_RE.match(pins) or not (cfg.pins_dir / pins).is_file():
        raise BadRequest("unknown pins file")
    if not isinstance(target, str) or not TARGET_RE.match(target):
        raise BadRequest("bad target")
    if target not in json.loads((cfg.pins_dir / pins).read_text(encoding="utf-8")).get("targets", {}):
        raise BadRequest(f"target {target!r} not in {pins}")
    if not isinstance(usermods, list) or not 1 <= len(usermods) <= 8 or not all(isinstance(u, str) for u in usermods):
        raise BadRequest("usermods: a list of 1-8 names")
    paths = [find_usermod(cfg, u) for u in usermods]
    return {"pins": pins, "target": target, "usermods": usermods, "usermod_paths": [str(p) for p in paths]}


def preview_pins(cfg: Config, name: str | None) -> str | None:
    """The pins file whose WLED gives a preview its exact colours: the one asked for, else
    WLED_STUDIO_PREVIEW_PINS, else the newest by name; None if there are none (approximate)."""
    if name is not None:
        if not isinstance(name, str) or not PINS_NAME_RE.match(name) or not (cfg.pins_dir / name).is_file():
            raise BadRequest("unknown pins file")
        return name
    if cfg.preview_pins and (cfg.pins_dir / cfg.preview_pins).is_file():
        return cfg.preview_pins
    files = sorted(p.name for p in cfg.pins_dir.glob("*.json")) if cfg.pins_dir.is_dir() else []
    return files[-1] if files else None


def validate_preview(cfg: Config, body: object) -> dict:
    if not isinstance(body, dict) or set(body) - {"usermods", "pins"}:
        raise BadRequest("expected {usermods, pins?}")
    usermods = body.get("usermods")
    if not isinstance(usermods, list) or not 1 <= len(usermods) <= 8 or not all(isinstance(u, str) for u in usermods):
        raise BadRequest("usermods: a list of 1-8 names")
    paths = [find_usermod(cfg, u) for u in usermods]
    job = {"kind": "preview", "usermods": usermods, "usermod_paths": [str(p) for p in paths]}
    pins = preview_pins(cfg, body.get("pins"))
    if pins:
        wled = json.loads((cfg.pins_dir / pins).read_text(encoding="utf-8")).get("wled", {})
        if isinstance(wled.get("repo"), str) and isinstance(wled.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", wled["commit"]):
            job.update(pins=pins, wled_repo=wled["repo"], wled_commit=wled["commit"])
    return job


def run_job(cfg: Config, job: dict, job_dir: Path) -> int:  # pragma: no cover - runs real builds
    with open(job_dir / "build.log", "wb") as log:
        if job.get("kind") == "preview":
            emsdk = cfg.work / "emsdk"
            script = (
                "set -e\n"
                f"if [ ! -x '{emsdk}/emsdk' ]; then git clone -q --depth 1 https://github.com/emscripten-core/emsdk.git '{emsdk}'; fi\n"
                f"'{emsdk}/emsdk' install {EMSDK_VERSION} >/dev/null\n"
                f"'{emsdk}/emsdk' activate {EMSDK_VERSION} >/dev/null\n"
                f". '{emsdk}/emsdk_env.sh' >/dev/null 2>&1\n"
            )
            if job.get("wled_commit"):  # exact colours: WLED's own colour code from its checkout
                src = cfg.work / "preview-wled" / job["wled_commit"]
                script += (
                    f"if [ ! -f '{src}/wled00/colors.h' ]; then rm -rf '{src}'; mkdir -p '{src}'; cd '{src}'; git init -q;"
                    f" git fetch -q --depth 1 '{job['wled_repo']}' {job['wled_commit']}; git checkout -q FETCH_HEAD; cd - >/dev/null; fi\n"
                    f"export WLED_SRC='{src}'\n"
                )
            script += (
                f"'{HERE.parent / 'preview' / 'build.sh'}' '{job_dir / 'preview'}' "
                + " ".join(f"'{p}'" for p in job["usermod_paths"]) + "\n"
            )
            return subprocess.run(["bash", "-c", script], stdout=log, stderr=subprocess.STDOUT).returncode
        cmd = [sys.executable, str(HERE / "gate.py"), str(cfg.pins_dir / job["pins"]), "--target", job["target"],
               "--work", str(cfg.work), "--out", str(job_dir)]
        for p in job["usermod_paths"]:
            cmd += ["--usermod", p]
        return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode


class JobQueue:
    """Jobs on disk (jobs_dir/<id>/job.json), run one at a time by a worker thread."""

    def __init__(self, cfg: Config, runner=run_job):
        self.cfg, self.runner = cfg, runner
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        cfg.jobs_dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._work, daemon=True).start()

    def _path(self, jid: str) -> Path:
        if not JOB_ID_RE.match(jid):
            raise KeyError(jid)
        return self.cfg.jobs_dir / jid

    def _save(self, jid: str, job: dict) -> None:
        # atomic: readers never see a half-written file
        with self.lock:
            tmp = self._path(jid) / "job.json.tmp"
            tmp.write_text(json.dumps(job, indent=2))
            os.replace(tmp, self._path(jid) / "job.json")

    def get(self, jid: str) -> dict:
        p = self._path(jid) / "job.json"
        if not p.exists():
            raise KeyError(jid)
        job = json.loads(p.read_text())
        rep = self._path(jid) / "gate-report.json"
        # Only once the job has finished: before that the runner may be halfway
        # through writing the report.
        if job["state"] in ("passed", "failed") and rep.exists():
            job["report"] = json.loads(rep.read_text())
        return job

    def list(self) -> list[dict]:
        jobs = []
        for d in self.cfg.jobs_dir.iterdir():
            if (d / "job.json").exists():
                j = json.loads((d / "job.json").read_text())
                j.pop("usermod_paths", None)
                jobs.append(j)
        return sorted(jobs, key=lambda j: j["created"], reverse=True)

    def submit(self, spec: dict) -> dict:
        jid = uuid.uuid4().hex
        self._path(jid).mkdir(parents=True)
        job = {"id": jid, "state": "queued", "created": time.time(), "kind": "gate", **spec}
        self._save(jid, job)
        self.q.put(jid)
        return job

    def _work(self) -> None:
        while True:
            jid = self.q.get()
            job = self.get(jid)
            job.update(state="running", started=time.time())
            self._save(jid, job)
            try:
                rc = self.runner(self.cfg, job, self._path(jid))
            except Exception as e:  # noqa: BLE001 - recorded in the job
                rc, job["error"] = -1, f"{e.__class__.__name__}: {e}"
            job.update(state="passed" if rc == 0 else "failed", finished=time.time(), exit=rc)
            job.pop("report", None)
            self._save(jid, job)


def make_handler(cfg: Config, jobs: JobQueue):
    class Handler(BaseHTTPRequestHandler):
        server_version = "wled-studio-builder"
        sys_version = ""

        def log_message(self, fmt, *args):  # quieter, and never logs headers
            sys.stderr.write("%s %s\n" % (self.command, self.path))

        def _send(self, status: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            if cfg.token is None or self.path == "/health":
                return True
            auth = self.headers.get("Authorization", "")
            given = auth[7:] if auth.lower().startswith("bearer ") else ""
            return hmac.compare_digest(given.encode(), cfg.token.encode())

        def do_GET(self):
            try:
                return self._get()
            except Exception as e:  # noqa: BLE001 - answer instead of dropping the connection
                return self._send(500, {"detail": e.__class__.__name__})

        def _get(self):
            if not self._authorised():
                return self._send(401, {"detail": "missing or wrong token"})
            parts = [p for p in self.path.split("?")[0].split("/") if p]
            try:
                if parts == ["health"]:
                    return self._send(200, {"status": "ok"})
                if parts == ["targets"]:
                    return self._send(200, list_targets(cfg))
                if parts == ["usermods"]:
                    return self._send(200, list_usermods(cfg))
                if parts == ["jobs"]:
                    return self._send(200, jobs.list())
                if len(parts) == 2 and parts[0] == "jobs":
                    job = jobs.get(parts[1])
                    job.pop("usermod_paths", None)
                    return self._send(200, job)
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "log":
                    jobs.get(parts[1])
                    log = jobs._path(parts[1]) / "build.log"
                    data = log.read_bytes()[-LOG_TAIL:] if log.exists() else b""
                    return self._send(200, data, "text/plain; charset=utf-8")
                if len(parts) == 4 and parts[0] == "jobs" and parts[2] == "preview" and parts[3] in PREVIEW_FILES:
                    job = jobs.get(parts[1])
                    f = jobs._path(parts[1]) / "preview" / parts[3]
                    if job.get("kind") != "preview" or job["state"] != "passed" or not f.exists():
                        return self._send(409, {"detail": "no compiled preview for this job"})
                    return self._send(200, f.read_bytes(), PREVIEW_FILES[parts[3]])
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "effects.json":
                    job = jobs.get(parts[1])
                    f = jobs._path(parts[1]) / "custom" / "effects.json"
                    if job.get("kind", "gate") != "gate" or job["state"] != "passed" or not f.exists():
                        return self._send(409, {"detail": "no effect list for this job"})
                    return self._send(200, f.read_bytes())
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "firmware.bin":
                    job = jobs.get(parts[1])
                    fw = jobs._path(parts[1]) / "custom" / "firmware.bin"
                    if job.get("kind", "gate") != "gate" or job["state"] != "passed" or not fw.exists():
                        return self._send(409, {"detail": "only jobs that passed the gate have firmware"})
                    return self._send(200, fw.read_bytes(), "application/octet-stream")
            except KeyError:
                return self._send(404, {"detail": "no such job"})
            return self._send(404, {"detail": "not found"})

        def do_POST(self):
            if not self._authorised():
                return self._send(401, {"detail": "missing or wrong token"})
            if self.path not in ("/jobs", "/previews"):
                return self._send(404, {"detail": "not found"})
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or int(length) > MAX_BODY:
                return self._send(413, {"detail": "body too large or missing length"})
            try:
                body = json.loads(self.rfile.read(int(length)) or b"null")
                spec = validate_job(cfg, body) if self.path == "/jobs" else validate_preview(cfg, body)
            except (BadRequest, json.JSONDecodeError) as e:
                return self._send(400, {"detail": str(e)})
            job = jobs.submit(spec)
            job.pop("usermod_paths", None)
            return self._send(202, job)

    return Handler


def serve(cfg: Config | None = None, runner=run_job) -> ThreadingHTTPServer:
    cfg = cfg or Config()
    server = ThreadingHTTPServer(cfg.bind, make_handler(cfg, JobQueue(cfg, runner)))
    return server


if __name__ == "__main__":  # pragma: no cover
    srv = serve()
    print(f"wled-studio-builder service on {srv.server_address[0]}:{srv.server_address[1]}", flush=True)
    srv.serve_forever()
