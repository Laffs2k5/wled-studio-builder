"""Unit tests for the studio tools. Standard library only: python -m unittest -v"""
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
import build  # noqa: E402
import imgdiff  # noqa: E402


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
