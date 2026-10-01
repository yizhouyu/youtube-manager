"""Tests for the renderer's audio path (src/editor/render.py): the mastering loop's gain/ceiling
logic and a real encode through it.

    ./venv/bin/python scripts/test_audio.py
"""
import os
import subprocess
import sys
import tempfile
import json
import unittest
from fractions import Fraction

import numpy as np

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
        g, auto = R.vo_gain_db({}, -18.0, -22.0, offset=0.5, trim=2.2)
        self.assertAlmostEqual(g, -1.3)
        self.assertTrue(auto)

    def test_legacy_gains_become_relative_trims(self):
        self.assertEqual(R.legacy_trims([4.5, 4.5, 4.5]), [0.0, 0.0, 0.0])     # uniform compensation: dropped
        self.assertEqual([round(t, 2) for t in R.legacy_trims([1.6, 6.0])], [-2.2, 2.2])  # intent kept
        self.assertEqual(R.legacy_trims([None, 3.0]), [0.0, 0.0])
        self.assertEqual(R.legacy_trims([]), [])

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


def _fake_project(td, clip_dur=6.0, noise=False):
    """A project with one source clip (speech-like audio, or steady pink noise like wind/ambience,
    + a black picture) -> (project dir, clip id)."""
    proj = os.path.join(td, "AudioTest")
    os.makedirs(os.path.join(proj, "01 - Unedited"))
    os.makedirs(os.path.join(proj, "02 - Export", "edit"))
    raw = os.path.join(td, "speech.wav")
    if noise:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"anoisesrc=d={clip_dur}:c=pink:r={SR}:a=0.1:s=7", "-ac", "2", raw], check=True)
    else:
        _speechlike(raw, clip_dur)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=320x180:r=30:d={clip_dur}",
                    "-i", raw, "-c:v", "libx264", "-c:a", "aac", "-b:a", "256k", "-shortest",
                    os.path.join(proj, "01 - Unedited", "CLIP.MP4")], check=True)
    return proj, "CLIP"


class PeakGuard(unittest.TestCase):
    def test_ceiling(self):
        self.assertEqual(R.peak_guard_ceiling(-30.0), -18.0)
        self.assertEqual(R.peak_guard_ceiling(-12.0), -3.0)        # never above -3 dBFS
        self.assertIsNone(R.peak_guard_ceiling(None))
        self.assertIsNone(R.peak_guard_ceiling(-80.0))
        self.assertEqual(R.peak_guard(None), [])
        deep = R.peak_guard(-40.0)                                   # -28 dBFS: below alimiter's -24 floor
        self.assertTrue(deep[0].startswith("volume=8.00dB") and deep[-1] == "volume=-8.00dB", deep)

    def test_boosted_shot_is_limited_unboosted_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            proj, clip = _fake_project(td)
            edl = {"project": proj, "shots": []}
            base = {"id": "s1", "clip": clip, "in": 0.5, "out": 5.5, "audio": "voice"}
            cache = os.path.join(td, "cache")
            os.makedirs(cache)
            plain = R._measure(R.render_segment_audio(edl, dict(base), "30", cache))
            boosted = R._measure(R.render_segment_audio(edl, dict(base, gain_db=6), "30", cache))
            self.assertAlmostEqual(boosted["I"] - plain["I"], 6.0, delta=1.5)        # still lifted
            self.assertLess(boosted["TP"] - boosted["I"], plain["TP"] - plain["I"] - 2.0)  # transients not lifted
            self.assertLessEqual(boosted["TP"], boosted["I"] + R.PEAK_GUARD_PLR + 1.0)


def _rms_db(x):
    return 20 * np.log10(max(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))), 1e-12))


def _min_window_db(x, centre, half=0.05, win=0.005):
    """Lowest 5 ms RMS (dBFS) within +-half s of sample index `centre`."""
    w, lo, hi = int(win * SR), max(0, centre - int(half * SR)), min(len(x), centre + int(half * SR))
    return min(_rms_db(x[i:i + w]) for i in range(lo, hi - w, w // 2))


def _seg(path, body, pre, post, level=0.1, seed=0, click_at=None):
    """A segment wav like render_segment_audio writes: white noise everywhere it 'has' sound."""
    h = R._HS
    x = (np.random.default_rng(seed).standard_normal((h + body + h, 2)) * level).astype(np.float32)
    x[:h - pre] = 0
    x[h + body + post:] = 0
    if click_at is not None:
        x[h + click_at] = 0.99
    R._write_f32(path, x)
    with open(path + ".json", "w") as f:
        json.dump({"pre": pre, "post": post, "body": body, "handle": h}, f)
    return path


class Crossfade(unittest.TestCase):
    def test_equal_power_curves(self):
        fo, fi = R.eq_power(2880)
        np.testing.assert_allclose(fo ** 2 + fi ** 2, 1.0, atol=1e-6)
        self.assertTrue(np.all(np.diff(fi) > 0) and np.all(np.diff(fo) < 0))
        self.assertAlmostEqual(float(fo[1440]), float(fi[1439]), places=3)   # symmetric: -3 dB in the middle
        self.assertEqual(len(R.eq_power(0)[0]), 0)

    def test_window_lengths(self):
        self.assertTrue(0.04 <= R.XF_CUT <= 0.08)
        self.assertEqual(R.join_xfade(0.5, 2.0, 2.0), R.XF_SKIP)
        self.assertEqual(R.join_xfade(0.025, 2.0, 2.0), 0.025)     # never reaches past the skipped span
        self.assertEqual(R.join_xfade(0.5, 0.03, 2.0), 0.03)       # nor past a short kept piece
        self.assertEqual(R.cut_window(1440, 1440, 48000, 48000), (1440, 1440))
        self.assertEqual(R.cut_window(1440, 0, 48000, 48000), (0, 1440))      # one-sided: still no hole
        self.assertEqual(R.cut_window(1440, 1440, 1000, 2000), (500, 1000))   # short shots: half a body max

    def test_assembler_no_hole_exact_length_and_sync(self):
        fps = 30000 / 1001
        bodies_f = [37, 52, 41, 30]                       # frames
        starts, t = [], 0.0
        for nf in bodies_f:
            starts.append(t)
            t += nf / fps
        total = t
        h = R._HS
        with tempfile.TemporaryDirectory() as td:
            segs = [_seg(os.path.join(td, f"s{i}.wav"), int(round(nf / fps * SR)), pre, post, seed=i,
                         click_at=0 if i == 2 else None)
                    for i, (nf, pre, post) in enumerate(zip(bodies_f, [h, h, h, 0], [h, h, 0, h]))]
            out = os.path.join(td, "voice.wav")
            rep = R.assemble_dialogue(segs, starts, total, out)
            x = R._read_f32(out)
            self.assertEqual(len(x), int(round(total * SR)))
            ref = _min_window_db(x, int(0.5 * SR))          # same statistic away from any cut
            cuts = [int(round(s * SR)) for s in starts[1:]]
            self.assertEqual([n for _t, n in rep], [2 * h, 2 * h, 0])
            for c in cuts[:2]:                             # handles on both sides: no dip at all
                self.assertGreater(_min_window_db(x, c), ref - 2.0)
            self.assertLess(_min_window_db(x, cuts[2], win=0.001), ref - 15)   # no handles: the old dip
            # the click at shot 2's first body sample lands on its frame-exact start (the crossfade
            # gain there is sin(pi/4) at the window centre)
            k = int(np.argmax(np.abs(x[:, 0])))
            self.assertEqual(k, cuts[1])

    def test_skip_join_and_cut_handles_from_source(self):
        with tempfile.TemporaryDirectory() as td:
            proj, clip = _fake_project(td, noise=True)
            edl = {"project": proj, "shots": []}
            cache = os.path.join(td, "cache")
            os.makedirs(cache)
            shot = {"id": "s1", "clip": clip, "in": 0.5, "out": 4.5, "audio": "voice", "skip": [[2.0, 2.6]]}
            fps = "30000/1001"
            a = R.render_segment_audio(edl, shot, fps, cache)
            with open(a + ".json") as f:
                m = json.load(f)
            n = R.frames_of(dict(shot), float(Fraction(fps)))
            self.assertEqual(m["body"], int(round(n / float(Fraction(fps)) * SR)))
            self.assertEqual((m["pre"], m["post"]), (R._HS, R._HS))          # source has sound both sides
            x = R._read_f32(a)
            self.assertEqual(len(x), m["body"] + 2 * R._HS)
            ref = _rms_db(x[R._HS + int(0.2 * SR):R._HS + int(1.2 * SR)])
            join = R._HS + int(round(1.5 * SR))                               # 2.0 s source = 1.5 s into the body
            ctrl = R._HS + int(round(0.8 * SR))                               # same statistic, no join
            # an old-style 12 ms fade-out/fade-in hole dips > 15 dB on this statistic
            self.assertGreater(_min_window_db(x, join), _min_window_db(x, ctrl) - 3.0, "no hole at the skip join")
            self.assertGreater(_rms_db(x[:R._HS]), ref - 3.0, "pre-handle is real source sound")
            # a shot starting at 0 s has no pre-handle; a card has silent (usable) handles
            b = R.render_segment_audio(edl, dict(shot, id="s2", **{"in": 0.0}), fps, cache)
            with open(b + ".json") as f:
                self.assertEqual(json.load(f)["pre"], 0)
            c = R.render_segment_audio(edl, {"id": "c1", "clip": "", "card": {"text": "x"}, "in": 0, "out": 2},
                                       fps, cache)
            with open(c + ".json") as f:
                self.assertEqual(json.load(f)["pre"], R._HS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
