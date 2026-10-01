"""Tests for the renderer's audio path (src/editor/render.py): the mastering loop's gain/ceiling
logic and a real encode through it.

    ./venv/bin/python scripts/test_audio.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import render as R  # noqa: E402

SR = 48000


class MasterStep(unittest.TestCase):
    def test_done_when_both_in_spec(self):
        self.assertEqual(R.master_step(5.0, -2.5, I=-14.1, TP=-2.3), (5.0, -2.5, True))

    def test_tp_over_lowers_ceiling_by_excess_plus_margin(self):
        g, c, done = R.master_step(5.0, -2.5, I=-14.0, TP=-1.2)
        self.assertFalse(done)
        self.assertEqual(g, 5.0)                       # loudness was fine: gain untouched
        self.assertAlmostEqual(c, -2.5 - 0.3 - 0.2)    # excess 0.3 + margin 0.2

    def test_tp_exactly_at_limit_passes(self):
        self.assertTrue(R.master_step(5.0, -2.5, I=-14.0, TP=-1.5)[2])

    def test_loudness_error_moves_gain(self):
        g, c, done = R.master_step(5.0, -2.5, I=-14.6, TP=-2.8)
        self.assertFalse(done)
        self.assertAlmostEqual(g, 5.6)
        self.assertEqual(c, -2.5)

    def test_loudness_within_tolerance_is_left_alone(self):
        self.assertTrue(R.master_step(5.0, -2.5, I=-13.75, TP=-2.0)[2])
        self.assertFalse(R.master_step(5.0, -2.5, I=-13.65, TP=-2.0)[2])

    def test_both_corrected_in_one_step(self):
        g, c, done = R.master_step(5.0, -2.5, I=-14.5, TP=-0.9)
        self.assertFalse(done)
        self.assertAlmostEqual(g, 5.5)
        self.assertAlmostEqual(c, -2.5 - 0.6 - 0.2)

    def test_ceiling_floor(self):
        self.assertEqual(R.master_step(5.0, -5.8, I=-14.0, TP=3.0)[1], R.MASTER_CEIL_MIN)

    def test_slope_scales_the_gain_correction(self):
        # the limiter is eating loudness: +6 dB of gain bought only +3 LU -> twice the correction
        tries = [{"I": -20.0, "gain": 4.0}, {"I": -17.0, "gain": 10.0}]
        self.assertAlmostEqual(R.master_slope(tries), 0.5)
        self.assertAlmostEqual(R.master_step(10.0, -2.5, I=-17.0, TP=-2.0, slope=0.5)[0], 16.0)
        self.assertEqual(R.master_slope(tries[:1]), 1.0)
        self.assertAlmostEqual(R.master_step(10.0, -2.5, I=-17.0, TP=-2.0, slope=0.01)[0], 22.0)  # clamped

    def test_pick_prefers_tp_safe_then_closest_loudness(self):
        tries = [{"I": -14.0, "TP": -1.2}, {"I": -14.45, "TP": -1.6}, {"I": -14.9, "TP": -2.0}]
        self.assertIs(R.master_pick(tries), tries[1])
        unsafe = [{"I": -14.0, "TP": -1.2}, {"I": -14.0, "TP": -1.4}]
        self.assertIs(R.master_pick(unsafe), unsafe[1])  # none safe: the lowest TP


class MasterEncode(unittest.TestCase):
    """A quiet mix with hot transients (PLR ~ 20 dB, like boosted speech + TTS) must come out at
    -14 +-0.3 LUFS and <= -1.5 dBTP measured on the AAC."""

    def test_master_hits_targets(self):
        with tempfile.TemporaryDirectory() as td:
            mix = os.path.join(td, "mix.wav")
            # pink noise at about -20 LUFS with a 3 ms tone burst every 0.5 s near full scale (PLR ~ 19 dB)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"anoisesrc=d=12:c=pink:r={SR}:a=0.3", "-f", "lavfi", "-i",
                            f"aevalsrc='0.95*sin(2*PI*1500*t)*lt(mod(t,0.5),0.003)':d=12:s={SR}",
                            "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo",
                            "-c:a", "pcm_f32le", mix], check=True)
            out = os.path.join(td, "m.m4a")
            st = R._master(mix, out)
            m = R._measure(out)
            self.assertLessEqual(m["TP"], R.MASTER_TP)
            self.assertLessEqual(abs(m["I"] - R.MASTER_I), 0.5)
            self.assertAlmostEqual(st["I"], m["I"], places=1)
            self.assertLessEqual(st["iterations"], R.MASTER_ITERS)
            self.assertFalse([f for f in os.listdir(td) if ".try" in f], "temporary tries cleaned up")


if __name__ == "__main__":
    unittest.main(verbosity=2)
