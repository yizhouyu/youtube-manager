"""Tests for the audio/pacing lint warnings (src/editor/lint.py): narration density and placement,
talk without a break, and sound-effect density.

    ./venv/bin/python scripts/test_lint_audio.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import lint as L  # noqa: E402


def card(i, d, **kw):
    return dict({"id": i, "clip": "", "card": {"text": "x"}, "in": 0, "out": d}, **kw)


class AudioLint(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.proj = os.path.join(self.td.name, "Lint test")
        os.makedirs(os.path.join(self.proj, "02 - Export", "edit", "tts"))
        # a 5 s "narration line"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=5",
                        os.path.join(self.proj, "02 - Export", "edit", "tts", "v1.wav")], check=True)

    def tearDown(self):
        self.td.cleanup()

    def edl(self, shots, **kw):
        return dict({"project": self.proj, "shots": shots}, **kw)

    def warns(self, edl, needle):
        return [w for w in L.audio_pacing(edl) if needle in w]

    def test_count_hanzi(self):
        self.assertEqual(L.count_hanzi("这里叫 Cat Haven，一九九八年开放。"), 2 + 4 + 2 * 2 + 4)
        self.assertEqual(L.count_hanzi("1998 年"), 5)

    def test_vo_text_sources(self):
        e = self.edl([card("c1", 10)])
        self.assertEqual(L.vo_text(e, {"file": "tts/v1.wav", "text": "直接写的"}), "直接写的")
        with open(os.path.join(self.proj, "02 - Export", "edit", "tts", "script.tsv"), "w") as f:
            f.write("id\ttts_text\tcaption\nv1\t表里的台词。\t表里的台词\n")
        self.assertEqual(L.vo_text(e, {"file": "tts/v1.wav"}), "表里的台词。")
        os.remove(os.path.join(self.proj, "02 - Export", "edit", "tts", "script.tsv"))
        with open(os.path.join(self.proj, "02 - Export", "edit", "tts", "SCRIPT.md"), "w") as f:
            f.write("| File | Line | Placed |\n|---|---|---|\n| v1.wav (5.0 s) | 文档里的台词。 | s1 |\n")
        self.assertEqual(L.vo_text(e, {"file": "tts/v1.wav"}), "文档里的台词。")

    def test_vo_density(self):
        # 24 字 over a 5 s line; the next on-camera speech starts 5.5 s after it -> 4.4/s: warn
        speech = card("c2", 10, subs=[{"t0": 0.0, "t1": 3.0, "text": "你好"}])
        dense = self.edl([card("c1", 6.0), speech],
                         voiceover=[{"file": "tts/v1.wav", "start": "c1", "at": 0.5, "text": "字" * 24}])
        self.assertTrue(self.warns(dense, "字 in a"))
        roomy = self.edl([card("c1", 9.0), speech],
                         voiceover=[{"file": "tts/v1.wav", "start": "c1", "at": 0.5, "text": "字" * 24}])
        self.assertFalse(self.warns(roomy, "字 in a"))      # 24 / 8.5 s = 2.8/s

    def test_vo_right_after_cut(self):
        e = lambda at, **kw: self.edl([card("c1", 3), card("c2", 9)],  # noqa: E731
                                      voiceover=[dict({"file": "tts/v1.wav", "start": "c2", "at": at}, **kw)])
        self.assertTrue(self.warns(e(0.2), "after a cut"))
        self.assertFalse(self.warns(e(0.3), "after a cut"))
        self.assertFalse(self.warns(e(0.1, jcut=True), "after a cut"))

    def test_talk_without_break(self):
        subs = [{"t0": t, "t1": t + 2.5, "text": "说话"} for t in range(0, 70, 3)]   # 0.5 s gaps for 70 s
        self.assertTrue(self.warns(self.edl([card("c1", 80, subs=subs)]), "without a break"))
        broken = [x for x in subs if not 30 <= x["t0"] < 36]                       # a 6.5 s breather at 30 s
        self.assertFalse(self.warns(self.edl([card("c1", 80, subs=broken)]), "without a break"))

    def test_sfx_density(self):
        fx = lambda ts: [{"file": "sfx/x.wav", "at": t} for t in ts]  # noqa: E731
        self.assertTrue(self.warns(self.edl([card("c1", 90, sfx=fx([1, 15, 30, 45]))]), "sound effects within a minute"))
        self.assertFalse(self.warns(self.edl([card("c1", 90, sfx=fx([1, 30, 62, 80]))]), "sound effects"))
        tts = [{"file": "tts/v1.wav", "at": t} for t in (2, 3, 4)]                 # narration isn't an effect
        self.assertFalse(self.warns(self.edl([card("c1", 90, sfx=fx([1, 15]) + tts)]), "sound effects"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
