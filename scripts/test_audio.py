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


def _speechlike(path, dur=4.0):
    """A voiced, syllable-rate (3 Hz) buzz with a hot plosive click every 1.3 s: PLR ~ 20 dB,
    24 kHz mono like edge-tts output."""
    expr = "0.25*(2*mod(t*130,1)-1)*pow(max(0,sin(2*PI*3*t)),2)+0.6*sin(2*PI*900*t)*lt(mod(t,1.3),0.004)"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d={dur}:s=24000",
                    "-af", "lowpass=f=4000", path], check=True)


class TTSChain(unittest.TestCase):
    def test_manual_gain_overrides_auto(self):
        self.assertEqual(R.vo_gain_db({"gain_db": -3}, -18.0, -22.0), (-3.0, False))
        self.assertEqual(R.vo_gain_db({"gain": 4.5}, -18.0, -22.0, offset=0.5), (-3.5, True))  # legacy gain ignored
        self.assertEqual(R.vo_gain_db({}, -60.0, -20.0)[0], 24.0)  # clamped

    def test_power_mean(self):
        self.assertAlmostEqual(R.power_mean_lufs([-20, -20, -120]), -20.0)
        self.assertAlmostEqual(R.power_mean_lufs([-20, -30]), 10 * __import__("math").log10((0.01 + 0.001) / 2))
        self.assertIsNone(R.power_mean_lufs([-90]))

    def test_tts_sfx_detection(self):
        self.assertTrue(R.is_tts_sfx({"file": "tts/v01.mp3"}))
        self.assertFalse(R.is_tts_sfx({"file": "sfx/whoosh.wav"}))
        self.assertTrue(R.is_tts_sfx({"file": "vo/line.wav", "tts": True}))
        self.assertFalse(R.is_tts_sfx({"file": "tts/riser.wav", "tts": False}))

    def test_chain_lowers_plr_keeps_timing_and_caches(self):
        with tempfile.TemporaryDirectory() as td:
            raw = os.path.join(td, "line.wav")
            _speechlike(raw)
            m0 = R._measure(raw)
            wav, line_i = R.tts_processed(raw, os.path.join(td, "cache"))
            m1 = R._measure(wav)
            self.assertAlmostEqual(line_i, m1["I"])
            # peaks tamed: PLR down by > 2.5 dB (the output is dual-mono stereo: +3 dB = per-channel TP of mono)
            self.assertLess(m1["TP"] + 3.0 - m1["I"], m0["TP"] - m0["I"] - 2.5, (m0, m1))
            self.assertAlmostEqual(R._media_dur(wav), R._media_dur(raw), delta=0.002)  # `at` timing holds
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels",
                                  "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "pcm_f32le,48000,2")  # float WAV, never re-encoded to MP3
            mt = os.path.getmtime(wav)
            self.assertEqual(R.tts_processed(raw, os.path.join(td, "cache"))[0], wav)
            self.assertEqual(os.path.getmtime(wav), mt, "second call is a cache hit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
