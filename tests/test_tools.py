"""Unit tests for the studio tools. Standard library only: python -m unittest -v"""
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
import build  # noqa: E402
import discover  # noqa: E402
import imgdiff  # noqa: E402
import json  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def make_image(segments, elf_sha=b"\x11" * 32):
    """A minimal ESP32 app image: header, segments (first carries an app descriptor), checksum, hash."""
    header = bytes([0xE9, len(segments), 2, 0x20]) + struct.pack("<I", 0x40080000)
    ext = bytes(15) + b"\x01"  # hash appended
    body = b""
    datas = []
    for i, (addr, data) in enumerate(segments):
        if i == 0:
            desc = bytearray(256)
            struct.pack_into("<I", desc, 0, imgdiff.APP_DESC_MAGIC)
            desc[imgdiff.APP_ELF_SHA_OFFSET:imgdiff.APP_ELF_SHA_OFFSET + 32] = elf_sha
            data = bytes(desc) + data
        datas.append(data)
        body += struct.pack("<II", addr, len(data)) + data
    raw = bytearray(header + ext + body)
    pad = 15 - (len(raw) % 16)
    raw += bytes(pad)
    chk = 0xEF
    for d in datas:
        for b in d:
            chk ^= b
    raw.append(chk)
    raw += hashlib.sha256(raw).digest()
    return bytes(raw)


class ImgDiffTests(unittest.TestCase):
    def write(self, data):
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        f.write(data)
        f.close()
        return Path(f.name)

    def test_identical(self):
        img = make_image([(0x3F400020, b"abc" * 10), (0x40080000, b"xyz" * 7)])
        a, b = imgdiff.parse(self.write(img)), imgdiff.parse(self.write(img))
        self.assertTrue(imgdiff.compare(a, b, None)["identical"])

    def test_elf_sha_only_is_explained_and_transplants(self):
        segs = [(0x3F400020, b"abc" * 10), (0x40080000, b"xyz" * 7)]
        a = imgdiff.parse(self.write(make_image(segs, b"\x11" * 32)))
        b = imgdiff.parse(self.write(make_image(segs, b"\x22" * 32)))
        rep = imgdiff.compare(a, b, None)
        # the checksum byte may or may not change (it's an XOR over the data)
        kinds = set(rep["summary"])
        self.assertTrue({"app-elf-sha256", "sha256"} <= kinds <= {"app-elf-sha256", "checksum", "sha256"})
        self.assertEqual(imgdiff.transplant_elf_sha(a, b), b.raw)

    def test_code_change_is_unexplained(self):
        a = imgdiff.parse(self.write(make_image([(0x3F400020, b"abc"), (0x40080000, b"xyzw")])))
        b = imgdiff.parse(self.write(make_image([(0x3F400020, b"abc"), (0x40080000, b"xyzv")])))
        rep = imgdiff.compare(a, b, None)
        self.assertIn("unexplained", rep["summary"])
        self.assertNotEqual(imgdiff.transplant_elf_sha(a, b), b.raw)

    def test_web_build_time(self):
        t = 1783528886
        a = imgdiff.parse(self.write(make_image([(0x3F400020, b"zz" + struct.pack("<I", t) + b"zz")])))
        b = imgdiff.parse(self.write(make_image([(0x3F400020, b"zz" + struct.pack("<I", t + 99) + b"zz")])))
        self.assertIn("web-build-time", imgdiff.compare(a, b, t)["summary"])


class NormalizedTests(unittest.TestCase):
    def write(self, data):
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        f.write(data)
        f.close()
        return Path(f.name)

    def test_normalized_ignores_elf_sha_only(self):
        segs = [(0x3F400020, b"abc" * 10), (0x40080000, b"xyz" * 7)]
        a = imgdiff.parse(self.write(make_image(segs, b"\x11" * 32)))
        b = imgdiff.parse(self.write(make_image(segs, b"\x22" * 32)))
        self.assertNotEqual(a.raw, b.raw)
        self.assertEqual(imgdiff.normalized_sha256(a), imgdiff.normalized_sha256(b))

    def test_normalized_sees_code(self):
        a = imgdiff.parse(self.write(make_image([(0x3F400020, b"abc"), (0x40080000, b"xyzw")])))
        b = imgdiff.parse(self.write(make_image([(0x3F400020, b"abc"), (0x40080000, b"xyzv")])))
        self.assertNotEqual(imgdiff.normalized_sha256(a), imgdiff.normalized_sha256(b))

    def test_normalized_image_is_valid(self):
        a = imgdiff.parse(self.write(make_image([(0x3F400020, b"abc" * 5)], b"\x33" * 32)))
        n = imgdiff.parse(self.write(imgdiff.normalized(a)))
        # re-normalising a normalized image changes nothing
        self.assertEqual(imgdiff.normalized(n), n.raw)


class LoadTargetTests(unittest.TestCase):
    PINS = {
        "schema": 2, "name": "x", "wled": {}, "override": {},
        "pins": {"https://g/a.git": "c1", "https://g/b.git": "c2"},
        "web_build_time": 100, "checkout": {"autocrlf": "false"},
        "targets": {
            "one": {"reference": {"sha256": "r1"}, "pins": {"https://g/b.git": "c9"}, "verified": {}},
            "two": {"reference": {"sha256": "r2"}, "web_build_time": 200, "env": "env-two"},
        },
    }

    def path(self, data=None):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump(data or self.PINS, f)
        f.close()
        return Path(f.name)

    def test_target_overrides_and_merges(self):
        t = build.load_target(self.path(), "one", [], [])
        self.assertEqual(t["pins"], {"https://g/a.git": "c1", "https://g/b.git": "c9"})
        self.assertEqual(t["web_build_time"], 100)
        self.assertEqual(t["env"], "one")
        t2 = build.load_target(self.path(), "two", [], [])
        self.assertEqual(t2["web_build_time"], 200)
        self.assertEqual(t2["env"], "env-two")

    def test_command_line_overrides(self):
        t = build.load_target(self.path(), "one", ["https://g/a.git=c7"],
                              ["web_build_time=300", "autocrlf=true", "gzip_os=3"])
        self.assertEqual(t["pins"]["https://g/a.git"], "c7")
        self.assertEqual(t["web_build_time"], 300)
        self.assertEqual(t["gzip_os"], 3)
        self.assertEqual(t["checkout"]["autocrlf"], "true")
        self.assertIn("web_build_time", t["overrides"])

    def test_target_required_when_several(self):
        with self.assertRaises(SystemExit):
            build.load_target(self.path(), None, [], [])
        with self.assertRaises(SystemExit):
            build.load_target(self.path(), "nope", [], [])

    def test_bad_overrides(self):
        with self.assertRaises(SystemExit):
            build.load_target(self.path(), "one", [], ["colour=red"])
        with self.assertRaises(SystemExit):
            build.load_target(self.path(), "one", ["no-equals-sign"], [])


class CheckTests(unittest.TestCase):
    def test_matches_reference(self):
        rep = {"toolchain_host": "windows", "normalized_sha256": "n", "reference_normalized_sha256": "n"}
        self.assertEqual(build.check_expectations(rep, {"windows": {"matches_reference": True}}), [])
        rep["normalized_sha256"] = "m"
        self.assertTrue(build.check_expectations(rep, {"windows": {"matches_reference": True}}))

    def test_recorded_hash(self):
        rep = {"toolchain_host": "linux-x86_64", "normalized_sha256": "abc"}
        self.assertEqual(build.check_expectations(rep, {"linux-x86_64": {"normalized_sha256": "abc"}}), [])
        self.assertTrue(build.check_expectations(rep, {"linux-x86_64": {"normalized_sha256": "def"}}))

    def test_unknown_host_is_reported(self):
        rep = {"toolchain_host": "linux-riscv64", "normalized_sha256": "abc"}
        self.assertTrue(build.check_expectations(rep, {}))


class DiscoverTests(unittest.TestCase):
    OVERRIDE = (
        "[env:board-a]\nbuild_flags =\n  -D WLED_RELEASE_NAME=\"\\\"Board-A\\\"\"\n"
        "[env:board-b]\nbuild_flags =\n  -D WLED_RELEASE_NAME=\"\\\"Board-B-v4\\\"\"\n"
        "[env:no-release]\nbuild_flags = -D X=1\n"
    )

    def test_release_names(self):
        self.assertEqual(discover.release_names(self.OVERRIDE), {"board-a": "Board-A", "board-b": "Board-B-v4"})

    def test_match_assets(self):
        assets = [
            {"name": "WLED_1.2.3_Board-A.bin", "browser_download_url": "u1", "size": 10, "digest": "sha256:aa"},
            {"name": "WLED_1.2.3_Board-B-v4.bin", "browser_download_url": "u2", "size": 20, "digest": "sha256:bb"},
            {"name": "WLED_1.2.3_Unknown.bin", "browser_download_url": "u3", "size": 30},
            {"name": "README.md", "browser_download_url": "u4", "size": 1},
        ]
        t = discover.match_assets(assets, discover.release_names(self.OVERRIDE), "1.2.3")
        self.assertEqual(list(t), ["board-a", "board-b"])
        self.assertEqual(t["board-b"]["reference"], {"url": "u2", "sha256": "bb", "size": 20})

    def test_stamp_at(self):
        ours = b"xx" + struct.pack("<I", 111) + b"yy" + struct.pack("<I", 111)
        vendor = b"xx" + struct.pack("<I", 222) + b"yy" + struct.pack("<I", 333)
        self.assertEqual(discover.stamp_at(ours, vendor, 111), [(2, 222), (8, 333)])

    def test_stamp_candidates(self):
        data = b"\x00" * 3 + struct.pack("<I", 1_700_000_000) + b"\x00" * 3
        found = [v for _, v in discover.stamp_candidates(data, 1_699_999_999, 1_700_000_001)]
        self.assertIn(1_700_000_000, found)


class PinsFileTests(unittest.TestCase):
    """Every pins file in the repository is well formed."""

    def test_pins_files(self):
        files = sorted((REPO / "pins").glob("*.json"))
        self.assertTrue(files)
        hex64 = lambda s: isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)  # noqa: E731
        for f in files:
            with self.subTest(f.name):
                p = json.loads(f.read_text())
                self.assertEqual(p.get("schema"), 2)
                for key in ("name", "wled", "override", "targets", "web_build_time"):
                    self.assertIn(key, p)
                self.assertTrue(len(p["wled"]["commit"]) == 40)
                self.assertTrue(len(p["override"]["commit"]) == 40)
                for url, commit in p.get("pins", {}).items():
                    self.assertTrue(url.startswith("https://") and len(commit) == 40, url)
                for name, t in p["targets"].items():
                    ref = t["reference"]
                    self.assertTrue(hex64(ref["sha256"]), name)
                    self.assertIsInstance(ref["size"], int)
                    for url, commit in t.get("pins", {}).items():
                        self.assertEqual(len(commit), 40, f"{name}: {url}")
                    for host, exp in t.get("verified", {}).items():
                        self.assertIn(host, ("windows", "linux-x86_64", "linux-aarch64"))
                        if "normalized_sha256" in exp:
                            self.assertTrue(hex64(exp["normalized_sha256"]))


class PinTests(unittest.TestCase):
    def test_pins_replace_branch_and_bare_urls(self):
        text = ("lib_deps =\n  https://github.com/o/a.git#optional-debug\n"
                "custom_usermods = x\n  https://github.com/o/b.git\n")
        out, hits = build.apply_pins(text, {"https://github.com/o/a.git": "c1",
                                            "https://github.com/o/b.git": "c2"})
        self.assertIn("https://github.com/o/a.git#c1\n", out)
        self.assertIn("https://github.com/o/b.git#c2\n", out)
        self.assertEqual(len(hits), 2)

    def test_pins_leave_other_urls(self):
        text = "  https://github.com/o/ab.git#x\n"
        out, hits = build.apply_pins(text, {"https://github.com/o/a.git": "c1"})
        self.assertEqual(out, text)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
