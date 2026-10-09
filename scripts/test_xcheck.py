"""xcheck (MOSS cross-check): parsing, token diff, caption matching, speaker-change flags, talk segments —
all without the model — plus a smoke test that runs MOSS on a `say`-generated Mandarin line (skipped when the
MLX env, the cached model or a Chinese `say` voice is missing, or with XCHECK_SMOKE=0).
Run: ./venv/bin/python scripts/test_xcheck.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import xcheck as X  # noqa: E402

# --- parse_moss: stamps, offset, a last phrase without its end stamp, plain text
raw = "[0.96][S01]看完了[1.96][2.03][S02]我们现在从这个Rodeo出来了[4.93][5.53][S02]然后感觉如何"
s = X.parse_moss(raw, offset=10.0, duration=7.0)
assert [x["speaker"] for x in s] == ["S01", "S02", "S02"], s
assert s[0] == {"start": 10.96, "end": 11.96, "speaker": "S01", "text": "看完了"}, s[0]
assert s[1]["text"] == "我们现在从这个Rodeo出来了" and s[1]["end"] == 14.93
assert s[2]["start"] == 15.53 and s[2]["end"] == 17.0, s[2]  # unterminated → span end
p = X.parse_moss("来到了这里", offset=2.0, duration=3.0)
assert p == [{"start": 2.0, "end": 5.0, "speaker": None, "text": "来到了这里"}], p
assert X.parse_moss("") == []

# --- tokens / diff: punctuation, case, traditional chars and spacing don't count; real word changes do
assert X.tokens("Hello 大家好，Texas!") == ["hello", "大", "家", "好", "texas"]
assert X.tokens("這個") == X.tokens("这个")
m, ter, _ = X.diff_tokens("我们现在这里叫 Stockyards。", "我们现在这里叫stockyards")
assert ter == 0 and "[-" not in m, (m, ter)
m, ter, _ = X.diff_tokens("这个菜叫 Texas Wang", "这个菜叫 Texas One")
assert "[-wang-]{+one+}" in m and abs(ter - 1 / 6) < 1e-9, (m, ter)
m, ter, _ = X.diff_tokens("我们这个镇上的活动", "我们这个就是镇上的活动")  # an inserted filler in the middle counts
assert "{+就是+}" in m and ter > 0, (m, ter)
# edge context: words cut off by the approximate time split are recovered from the neighbour …
m, ter, shown = X.diff_tokens("到这个 Dallas downtown 去了", X.tokens("到这个dallas"), right=X.tokens("downtown去了"))
assert ter == 0 and shown == "到这个dallas downtown去了", (m, ter, shown)
# … and a neighbour's word that bled in at the edge is set aside, but still shown
m, ter, shown = X.diff_tokens("就是小朋友", X.tokens("就是小朋友一"))
assert ter == 0 and shown.endswith("‹一›"), (m, ter, shown)
# a real edit inside the line is never trimmed away
m, ter, _ = X.diff_tokens("从小你跟这个小牛玩", X.tokens("从小你就去这个就跟这个小牛玩"))
assert "{+就去这个就+}" in m and ter > 0.4, (m, ter)

# --- matching: a phrase spanning two captions is split by time; speakers inside one caption are flagged
segs = [{"start": 0.0, "end": 4.0, "speaker": "S01", "text": "一二三四五六七八"},
        {"start": 4.2, "end": 6.0, "speaker": "S02", "text": "然后感觉如何"}]
left, heard, right, cover = X.match_caption({"t0": 0.0, "t1": 2.0, "text": "一二三四"}, segs)
assert "".join(heard) == "一二三四" and right == ["五", "六"] and [k for k, _ in cover] == ["S01"], (heard, right, cover)
cap = {"t0": 2.0, "t1": 6.0, "text": "五六七八然后感觉如何"}
left, heard, right, cover = X.match_caption(cap, segs)
assert "".join(heard) == "五六七八然后感觉如何" and left == ["三", "四"], (left, heard)
assert X.speaker_change(cap, cover) == ["S01", "S02"], cover
lines, summ = X.report([dict(cap, where="s1")], segs)
assert any("!! speakers S01→S02" in ln for ln in lines) and summ["flagged"] == 1, lines
# a second speaker who only grazes the caption edge (< 0.6 s) is not a speaker change
cap2 = {"t0": 0.0, "t1": 4.5, "text": "一二三四五六七八然"}
assert X.speaker_change(cap2, X.match_caption(cap2, segs)[3]) == [], X.match_caption(cap2, segs)
# skip spans inside a caption (clip mode) are not heard: their words drop out of the comparison
cap3 = {"t0": 0.0, "t1": 4.0, "text": "一二七八", "skip": [[1.0, 3.0]]}
assert X.windows(cap3) == [(0.0, 1.0), (3.0, 4.0)]
assert X.windows({"t0": 5.0, "t1": 6.0, "skip": [[1.0, 2.0], [9.0, 12.0]]}) == [(5.0, 6.0)]  # skips elsewhere in the shot
assert "".join(X.match_caption(cap3, segs)[1]) == "一二七八"
# a phrase under no caption, inside a used shot → listed; outside the used ranges → ignored
extra = X.uncaptioned(segs + [{"start": 9.0, "end": 10.0, "speaker": "S02", "text": "外面"}],
                      [{"t0": 0.0, "t1": 4.0, "text": "x"}], [(0.0, 7.0)])
assert [e["text"] for e in extra] == ["然后感觉如何"], extra

# --- EDL helpers: notes are not speech, duplicates collapse, talk segments merge across small gaps
edl = {"project": "/nonexistent", "shots": [
    {"id": "a", "clip": "C1", "in": 1.0, "out": 9.0, "subs": [
        {"t0": 1.1, "t1": 3.0, "text": "第一句"}, {"t0": 3.2, "t1": 5.0, "text": "注释", "kind": "note"},
        {"t0": 6.0, "t1": 8.0, "text": "第二句"}]},
    {"id": "b", "clip": "C1", "in": 1.0, "out": 3.1, "subs": [{"t0": 1.1, "t1": 3.0, "text": "第一句"}]},
    {"id": "m", "clip": "C1", "in": 20.0, "out": 25.0, "audio": "mute"},
    {"id": "c", "clip": "C2", "in": 0.0, "out": 4.0, "skip": [[1.0, 2.0]], "subs": [{"t0": 2.0, "t1": 3.5, "text": "跳过后"}]}]}
caps, ranges = X.clip_captions(edl, "C1")
assert [c["text"] for c in caps] == ["第一句", "第二句"] and caps[0]["where"] == "a,b", caps  # reused line: once
assert ranges == [(1.0, 9.0), (1.0, 3.1)], ranges  # the muted shot m (20–25 s) is not an audible range
assert X.clip_captions(edl, "C2")[0][0]["skip"] == [[1.0, 2.0]] and X.clip_captions(edl, "C2")[1] == [(0.0, 1.0), (2.0, 4.0)]
tcaps, tranges = X.timeline_captions(edl)
assert [c["text"] for c in tcaps] == ["第一句", "第二句", "第一句", "跳过后"], tcaps
assert abs(tcaps[3]["t0"] - (8.0 + 2.1 + 5.0 + 1.0)) < 0.01, tcaps[3]  # c starts at 15.1, its skip removes 1 s
assert all(not (r0 < 15.0 and r1 > 10.1) for r0, r1 in tranges), tranges  # the muted shot is not "heard"
assert X.talk_segments([{"t0": 1, "t1": 2}, {"t0": 2.5, "t1": 3}, {"t0": 6, "t1": 7}]) == [(0.75, 3.25), (5.75, 7.25)]
assert X.talk_segments([{"t0": 0, "t1": 30}, {"t0": 30.5, "t1": 60}]) == [(0.0, 30.25), (30.25, 60.25)]  # length cap
print("logic ok")

# --- smoke: the real model on a synthetic Mandarin line
voice = None
try:
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout.splitlines()
    zh = [v.split()[0] for v in voices if "zh_CN" in v]
    voice = "Tingting" if "Tingting" in zh else (zh[0] if zh else None)  # Eddy/Flo render empty files with -o
except OSError:
    pass
cached = os.path.isdir(os.path.expanduser("~/.cache/huggingface/hub/models--OpenMOSS-Team--MOSS-Transcribe-Diarize"))
if os.environ.get("XCHECK_SMOKE") == "0" or not X.mlx_python() or not cached or not voice:
    print("smoke: skipped (MLX env / cached model / zh voice missing, or XCHECK_SMOKE=0)")
    sys.exit(0)
line = "我们现在来到了达拉斯，这里有一个很大的牛仔雕像"
with tempfile.TemporaryDirectory() as td:
    aiff, wav = os.path.join(td, "s.aiff"), os.path.join(td, "s.wav")
    subprocess.run(["say", "-v", voice, "-o", aiff, line], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", aiff, "-ar", "48000", wav], check=True)
    if X._probe_dur(wav) < 1.0:
        print(f"smoke: skipped (`say -v {voice}` wrote no audio)")
        sys.exit(0)
    out = os.path.join(td, "x.json")
    X.run_model([{"src": wav, "a": 0.0, "b": X._probe_dur(wav), "out": out, "source": "say", "offset": 0.0}])
    import json
    rec = json.load(open(out))
    heard = "".join(s["text"] for s in rec["segments"])
    _, ter, _ = X.diff_tokens(line, heard)
    print(f"smoke: MOSS heard {heard!r} (TER {100 * ter:.0f}%, {rec['secs']} s)")
    assert rec["segments"] and ter < 0.35, rec
print("ok")
