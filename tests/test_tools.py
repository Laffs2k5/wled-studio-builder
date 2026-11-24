# SPDX-License-Identifier: EUPL-1.2
"""Unit tests for the studio tools. Standard library only: python -m unittest -v"""
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "studio"))
import build  # noqa: E402
import discover  # noqa: E402
import gate  # noqa: E402
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


class DownloadTests(unittest.TestCase):
    """download() retries a server error or a network failure, not a client error."""

    def run_with(self, outcomes):
        import io
        import urllib.error
        from unittest import mock
        calls = []

        def fake(req, timeout):
            calls.append(req.full_url)
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return io.BytesIO(o)
        dest = Path(tempfile.mkdtemp()) / "f"
        with mock.patch("urllib.request.urlopen", fake):
            try:
                build.download("https://x/f", dest, sleep=lambda s: None)
                return calls, dest.read_bytes()
            except urllib.error.URLError as e:
                return calls, e

    def http(self, code):
        import urllib.error
        return urllib.error.HTTPError("https://x/f", code, "err", {}, None)

    def test_retries_a_503(self):
        calls, body = self.run_with([self.http(503), b"ok"])
        self.assertEqual((len(calls), body), (2, b"ok"))

    def test_gives_up_after_three(self):
        calls, err = self.run_with([self.http(503)] * 3)
        self.assertEqual((len(calls), err.code), (3, 503))

    def test_a_404_fails_at_once(self):
        calls, err = self.run_with([self.http(404), b"never"])
        self.assertEqual((len(calls), err.code), (1, 404))


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


class UsermodCaseTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name in ("Temperature", "audioreactive", "Internal_Temperature_v2", "multi_relay"):
            (self.dir / name).mkdir()

    def test_fixes_plain_names_only_in_the_env(self):
        ov = ("[env:a]\ncustom_usermods = audioreactive temperature\n"
              "  internal_temperature https://github.com/o/r.git\nbuild_flags = -D X\n"
              "[env:b]\ncustom_usermods = temperature\n")
        out, fixes = build.fix_usermod_case(ov, "a", self.dir)
        self.assertIn("custom_usermods = audioreactive Temperature\n", out)
        self.assertIn("  Internal_Temperature_v2 https://github.com/o/r.git\n", out)
        self.assertIn("[env:b]\ncustom_usermods = temperature\n", out)  # other env untouched
        self.assertEqual(fixes, ["temperature -> Temperature", "internal_temperature -> Internal_Temperature_v2"])

    def test_no_change_when_names_exist(self):
        ov = "[env:a]\ncustom_usermods = audioreactive multi_relay\n"
        out, fixes = build.fix_usermod_case(ov, "a", self.dir)
        self.assertEqual((out, fixes), (ov, []))

    def test_missing_env_or_dir(self):
        self.assertEqual(build.fix_usermod_case("x\n", "a", self.dir), ("x\n", []))
        self.assertEqual(build.fix_usermod_case("x\n", "a", self.dir / "nope"), ("x\n", []))


class VirtualFlagsTests(unittest.TestCase):
    """The engine's flags: from a compile command, then only what shapes the effect engine."""

    def test_defines_and_the_engine_filter(self):
        import manifest
        import virtual_check
        d = manifest.defines({"command": 'g++ -DARDUINO=10812 -D WLED_PS_DONT_REPLACE_FX -DNAMES="a b" '
                                         '-DWLED_RELEASE_NAME=\\"Dig\\" -DBOARD_HAS_PSRAM -DUSERMOD_X -c FX.cpp'})
        self.assertEqual(d, ["-DARDUINO=10812", "-DWLED_PS_DONT_REPLACE_FX", "-DNAMES=a b",
                             '-DWLED_RELEASE_NAME="Dig"', "-DBOARD_HAS_PSRAM", "-DUSERMOD_X"])
        self.assertEqual(virtual_check.engine_flags(d), ["-DWLED_PS_DONT_REPLACE_FX", '-DWLED_RELEASE_NAME="Dig"',
                                                         "-DBOARD_HAS_PSRAM", "-DUSERMOD_X"])


class GateTests(unittest.TestCase):
    """The gate's logic, with a fake builder (no compiling)."""

    STOCK = {"core/a.o": "1", "core/b.o": "2", "lib.a:x.o": "3"}

    def run_gate(self, stock_check=None, custom_objects=None, custom_size=1_000_000, slot=1_572_864,
                 fail_stock=False, virtual=None):
        tmp = Path(tempfile.mkdtemp())
        pins = tmp / "pins.json"
        pins.write_text(json.dumps({"name": "p", "app_slot_bytes": slot, "targets": {"t": {}}}))
        um = tmp / "my_fx"
        um.mkdir()
        custom_objects = custom_objects if custom_objects is not None else {**self.STOCK, "my_fx/fx.cpp.o": "9"}

        def builder(pins_path, target, work, out, usermods, check):
            if fail_stock and not usermods:
                return 1
            out.mkdir(parents=True, exist_ok=True)
            objects = custom_objects if usermods else self.STOCK
            report = {"check": stock_check or [], "normalized_sha256": "n", "firmware_size": custom_size if usermods
                      else 900_000, "firmware_sha256": "s", "toolchain_host": "linux-x86_64"}
            (out / "build-report.json").write_text(json.dumps(report))
            (out / "objects.json").write_text(json.dumps(objects))
            return 0

        argv = [str(pins), "--target", "t", "--usermod", str(um), "--out", str(tmp / "out")]
        if virtual is None:
            rc = gate.main(argv, builder=builder)
        else:   # the virtual check, faked: its exit code and the report it writes
            def fake_virtual(a, out):
                (out / "virtual").mkdir(parents=True, exist_ok=True)
                (out / "virtual" / "virtual-report.json").write_text(json.dumps(
                    {"passed": virtual == 0, "effects_run": 3, "crashed": [] if virtual == 0 else ["250 Crash: …"]}))
                return virtual
            from unittest import mock
            with mock.patch.object(gate, "virtual_check", fake_virtual):
                rc = gate.main(argv + ["--emsdk", str(tmp)], builder=builder)
        return rc, json.loads((tmp / "out" / "gate-report.json").read_text())

    def test_the_virtual_twin_is_a_check_with_emsdk(self):
        rc, rep = self.run_gate(virtual=0)
        self.assertEqual(rc, 0)
        self.assertTrue(rep["checks"]["virtual_twin"] and rep["virtual"]["effects_run"] == 3)
        rc, rep = self.run_gate(virtual=1)
        self.assertEqual(rc, 1)
        self.assertFalse(rep["passed"] or rep["checks"]["virtual_twin"])
        self.assertNotIn("firmware", rep)
        self.assertEqual(rep["virtual"]["crashed"], ["250 Crash: …"])
        rc, rep = self.run_gate()                                   # without --emsdk: four checks, as before
        self.assertNotIn("virtual_twin", rep["checks"])

    def test_passes(self):
        rc, rep = self.run_gate()
        self.assertEqual(rc, 0)
        self.assertTrue(rep["passed"])
        self.assertEqual(rep["objects"]["added_from_usermods"], ["my_fx/fx.cpp.o"])
        self.assertEqual(rep["firmware"], "custom/firmware.bin")

    def test_stock_must_match(self):
        rc, rep = self.run_gate(stock_check=["no verified result"])
        self.assertEqual(rc, 1)
        self.assertFalse(rep["checks"]["stock_matches_verified"])

    def test_changed_core_object_fails(self):
        rc, rep = self.run_gate(custom_objects={**self.STOCK, "core/a.o": "X", "my_fx/fx.cpp.o": "9"})
        self.assertEqual(rc, 1)
        self.assertEqual(rep["objects"]["unexpected"], ["core/a.o"])

    def test_removed_object_fails(self):
        objs = {k: v for k, v in self.STOCK.items() if k != "core/b.o"}
        rc, rep = self.run_gate(custom_objects={**objs, "my_fx/fx.cpp.o": "9"})
        self.assertEqual(rc, 1)
        self.assertEqual(rep["objects"]["unexpected"], ["core/b.o"])

    def test_usermod_must_add_something(self):
        rc, rep = self.run_gate(custom_objects=dict(self.STOCK))
        self.assertEqual(rc, 1)
        self.assertFalse(rep["checks"]["only_usermod_objects_changed"])

    def test_size_margin(self):
        rc, rep = self.run_gate(custom_size=1_572_864 - 1000)
        self.assertEqual(rc, 1)
        self.assertFalse(rep["checks"]["fits_app_slot"])

    def test_stock_build_failure(self):
        rc, rep = self.run_gate(fail_stock=True)
        self.assertEqual(rc, 1)
        self.assertIn("stock build failed", rep["error"])


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


class ManifestTests(unittest.TestCase):
    """The effect list of a built image (manifest.py)."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "studio"))
        import manifest
        self.m = manifest

    def test_c_strings(self):
        self.assertEqual(self.m.c_string('"a\\\\b" "c\\"d" "\\x41\\101\\n"'), 'a\\bc"dAA\n')

    def test_add_effect_follows_wleds_rules(self):
        fx = ["Solid", "RSVD", "RSVD", "Blink"]
        self.assertEqual(self.m.add_effect(fx, 2, "Two"), 2)          # a placeholder is replaced
        self.assertEqual(self.m.add_effect(fx, 3, "Again"), 255)      # an added effect isn't
        self.assertEqual(self.m.add_effect(fx, 255, "Any"), 1)        # 255: the first placeholder
        self.assertEqual(self.m.add_effect(fx, 200, "Far"), 4)        # past the end: appended
        self.assertEqual(fx, ["Solid", "Any", "Two", "Blink", "Far"])

    def test_builtin_effects_from_the_preprocessed_source(self):
        pre = """
        class WS2812FX { WS2812FX() : _modeCount(5) {} };
        static const char _data_FX_MODE_STATIC[] __attribute__((section(".x"))) = "Solid";
        static const char _data_FX_MODE_BLINK[] = "Blink@!,Duty;!,!;!;01";
        static const char _data_FX_MODE_RAIN[] = "Rain" "@!,Spawn;!,!;!";
        static const char _data_RESERVED[] = "RSVD";
        void WS2812FX::setupEffectData() {
          _mode.push_back(&mode_static);
          addEffect(1, &mode_blink, _data_FX_MODE_BLINK);
          // addEffect(2, &mode_old, _data_FX_MODE_OLD);   commented out
          addEffect(3, &mode_rain, _data_FX_MODE_RAIN);
          addEffect(1, &mode_rain, _data_FX_MODE_RAIN);     // taken: not added
        }
        void other() { addEffect(4, &x, _data_FX_MODE_BLINK); }
        """
        fx = self.m.builtin_effects(pre)
        self.assertEqual(fx, ["Solid", "Blink@!,Duty;!,!;!;01", "RSVD", "Rain@!,Spawn;!,!;!", "RSVD"])
        m = self.m.manifest(fx, {"env": "x"})
        self.assertEqual(m["effects"][1], {"id": 1, "name": "Blink", "meta": "!,Duty;!,!;!;01"})
        self.assertEqual(m["effects"][0], {"id": 0, "name": "Solid", "meta": ""})

    def test_a_macro_left_as_an_id_is_an_error(self):
        pre = 'x _modeCount(2) static const char _data_FX_MODE_STATIC[] = "Solid";\n' \
              "void WS2812FX::setupEffectData() { addEffect(FX_MODE_X, &f, _data_FX_MODE_STATIC); }"
        with self.assertRaises(ValueError):
            self.m.builtin_effects(pre)

    def test_usermod_effects_by_the_templates_convention(self):
        src = (ROOT / "examples" / "usermods" / "studio_example_fx" / "studio_example_fx.cpp").read_text()
        found = self.m.usermod_effects(src)
        self.assertEqual(found, [(254, "Studio Comet@Speed,Tail;!;!;1;sx=128,ix=200")])
        fx = ["Solid"] + ["X"] * 9
        self.assertEqual(self.m.place_usermod(fx, *found[0]), 254)
        self.assertEqual((len(fx), fx[10], fx[253]), (255, "RSVD", "RSVD"))
        self.assertEqual(self.m.place_usermod(["Solid"] * 20, 5, "Late"), 255)  # the id is taken already

    def test_usermod_effects_through_a_registration_helper(self):
        src = """
        constexpr uint8_t kAId = 240;
        const char kAData[] PROGMEM =
            "A@Speed;!;;1";
        constexpr uint8_t kBId = 241;
        const char kBData[] PROGMEM = "B@;!;;1";
        bool add_fixed(uint8_t id, mode_ptr fn, const char* data) { return strip.addEffect(id, fn, data) == id; }
        void setup() { add_fixed(kAId, &mode_a, kAData); add_fixed(kBId, &mode_b, kBData); }
        """
        self.assertEqual(self.m.usermod_effects(src), [(240, "A@Speed;!;;1"), (241, "B@;!;;1")])

    def test_preprocess_runs_the_compile_command_with_E(self):
        with tempfile.TemporaryDirectory() as d:
            echo = Path(d) / "echo.py"
            echo.write_text("import sys; print(' '.join(sys.argv[1:]))")
            entry = {"directory": d, "file": "wled00/FX.cpp",
                     "arguments": [sys.executable, str(echo), "-Dx", "-o", "FX.o", "-c", "wled00/FX.cpp"]}
            self.assertEqual(self.m.preprocess(entry).strip(), "-Dx -E wled00/FX.cpp")
            self.assertIs(self.m.compile_entry([{"file": "a/b.cpp"}, entry], "wled00/FX.cpp"), entry)
            with self.assertRaises(KeyError):
                self.m.compile_entry([], "wled00/FX.cpp")
