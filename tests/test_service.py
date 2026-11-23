# SPDX-License-Identifier: EUPL-1.2
"""The job service, with a fake gate runner (no compiling)."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
import service  # noqa: E402


def fake_runner(passed=True):
    def run(cfg, job, job_dir):
        if job.get("kind") == "preview":
            (job_dir / "build.log").write_text("compiled")
            if passed:
                (job_dir / "preview").mkdir()
                (job_dir / "preview" / "preview.mjs").write_text("export default 1;")
                (job_dir / "preview" / "preview.wasm").write_bytes(b"\0asm")
            return 0 if passed else 1
        (job_dir / "build.log").write_text("building...\nGATE " + ("PASSED" if passed else "FAILED"))
        (job_dir / "gate-report.json").write_text(json.dumps({"passed": passed}))
        if passed:
            (job_dir / "custom").mkdir()
            (job_dir / "custom" / "firmware.bin").write_bytes(b"\xe9firmware")
        return 0 if passed else 1
    return run


class ServiceTests(unittest.TestCase):
    def start(self, passed=True, token=None, runner=None):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "pins").mkdir()
        (tmp / "pins" / "p.json").write_text(json.dumps({"name": "p", "targets": {"board": {"verified": {"windows": {}}}}}))
        (tmp / "fx" / "my_fx").mkdir(parents=True)
        env = {"WLED_STUDIO_PINS_DIR": str(tmp / "pins"), "WLED_STUDIO_USERMODS_DIRS": str(tmp / "fx"),
               "WLED_STUDIO_JOBS_DIR": str(tmp / "jobs"), "WLED_STUDIO_WORK": str(tmp / "work"),
               "WLED_STUDIO_SERVICE_BIND": "127.0.0.1:0"}
        if token:
            env["WLED_STUDIO_SERVICE_TOKEN"] = token
        srv = service.serve(service.Config(env), runner=runner or fake_runner(passed))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{srv.server_address[1]}"
        self.token = token

    def call(self, method, path, body=None, token=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token or self.token:
            req.add_header("Authorization", f"Bearer {token or self.token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers["Content-Type"] == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(self, jid):
        for _ in range(100):
            _, job = self.call("GET", f"/jobs/{jid}")
            if job["state"] in ("passed", "failed"):
                return job
            time.sleep(0.02)
        raise AssertionError("job didn't finish")

    def test_lists(self):
        self.start()
        self.assertEqual(self.call("GET", "/health"), (200, {"status": "ok"}))
        self.assertEqual(self.call("GET", "/targets")[1],
                         [{"pins": "p.json", "release": "p", "target": "board", "verified": ["windows"]}])
        self.assertEqual(self.call("GET", "/usermods")[1], ["my_fx"])

    def test_job_that_passes(self):
        self.start()
        status, job = self.call("POST", "/jobs", {"pins": "p.json", "target": "board", "usermods": ["my_fx"]})
        self.assertEqual(status, 202)
        self.assertNotIn("usermod_paths", job)
        job = self.wait(job["id"])
        self.assertEqual(job["state"], "passed")
        self.assertEqual(job["report"], {"passed": True})
        self.assertIn(b"GATE PASSED", self.call("GET", f"/jobs/{job['id']}/log")[1])
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/firmware.bin"), (200, b"\xe9firmware"))
        self.assertEqual(len(self.call("GET", "/jobs")[1]), 1)

    def test_report_is_hidden_while_the_job_runs(self):
        # The gate writes its report before it exits; a poll in between must not
        # read a half-written file.
        writing, release = threading.Event(), threading.Event()

        def run(cfg, job, job_dir):
            (job_dir / "gate-report.json").write_text('{"pass')
            writing.set()
            release.wait(5)
            (job_dir / "gate-report.json").write_text(json.dumps({"passed": True}))
            return 0

        self.start(runner=run)
        _, job = self.call("POST", "/jobs", {"pins": "p.json", "target": "board", "usermods": ["my_fx"]})
        self.assertTrue(writing.wait(5))
        status, running = self.call("GET", f"/jobs/{job['id']}")
        release.set()
        self.assertEqual(status, 200)
        self.assertEqual(running["state"], "running")
        self.assertNotIn("report", running)
        self.assertEqual(self.wait(job["id"])["report"], {"passed": True})

    def test_failed_job_has_no_firmware(self):
        self.start(passed=False)
        _, job = self.call("POST", "/jobs", {"pins": "p.json", "target": "board", "usermods": ["my_fx"]})
        job = self.wait(job["id"])
        self.assertEqual(job["state"], "failed")
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/firmware.bin")[0], 409)

    def test_validation(self):
        self.start()
        bad = [
            {"pins": "../etc/passwd.json", "target": "board", "usermods": ["my_fx"]},
            {"pins": "nope.json", "target": "board", "usermods": ["my_fx"]},
            {"pins": "p.json", "target": "other", "usermods": ["my_fx"]},
            {"pins": "p.json", "target": "board", "usermods": ["../my_fx"]},
            {"pins": "p.json", "target": "board", "usermods": ["missing"]},
            {"pins": "p.json", "target": "board", "usermods": []},
            {"pins": "p.json", "target": "board", "usermods": ["my_fx"], "extra": 1},
            ["not", "an", "object"],
        ]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/jobs", body)[0], 400)
        self.assertEqual(self.call("GET", "/jobs/not-an-id")[0], 404)
        self.assertEqual(self.call("GET", "/jobs/" + "0" * 32)[0], 404)
        self.assertEqual(self.call("GET", "/nothing")[0], 404)
        self.assertEqual(self.call("POST", "/elsewhere", {})[0], 404)

    def test_preview_job(self):
        self.start()
        status, job = self.call("POST", "/previews", {"usermods": ["my_fx"]})
        self.assertEqual(status, 202)
        self.assertEqual(job["kind"], "preview")
        job = self.wait(job["id"])
        self.assertEqual(job["state"], "passed")
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/preview/preview.wasm"), (200, b"\0asm"))
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/preview/preview.mjs")[0], 200)
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/preview/other.js")[0], 404)
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/firmware.bin")[0], 409)  # a preview has no firmware
        for bad in ({"usermods": ["../x"]}, {"usermods": []}, {"usermods": ["my_fx"], "pins": "p.json"}):
            self.assertEqual(self.call("POST", "/previews", bad)[0], 400)

    def test_gate_job_has_no_preview(self):
        self.start()
        _, job = self.call("POST", "/jobs", {"pins": "p.json", "target": "board", "usermods": ["my_fx"]})
        job = self.wait(job["id"])
        self.assertEqual(self.call("GET", f"/jobs/{job['id']}/preview/preview.mjs")[0], 409)

    def test_token(self):
        self.start(token="t0k3n")
        self.assertEqual(self.call("GET", "/health", token="x")[0], 200)  # health is open
        self.assertEqual(self.call("GET", "/targets", token="wrong")[0], 401)
        self.assertEqual(self.call("GET", "/targets")[0], 200)


if __name__ == "__main__":
    unittest.main()
