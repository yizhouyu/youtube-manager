"""Contact sheets so the agent can LOOK at every raw clip.

    ./venv/bin/python -m src.editor.scan "<project>"

Writes <project>/02 - Export/edit/scan/:
  meta.json            {clip: {dur, interval, ctime}} in capture order
  sheets/<clip>.jpg    6x2 grid, one frame every max(2 s, dur/12), each labelled with its second
  sheets/grid_NN.jpg   4 clips stacked per image (clip name, duration, camera clock) — read these

This ffmpeg has no drawtext, so labels are drawn with Pillow.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont

from . import edl as E

FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time",
                          "-of", "json", path], capture_output=True, text=True).stdout
    f = json.loads(out)["format"]
    return float(f["duration"]), f.get("tags", {}).get("creation_time", "")


def _sheet(args):
    path, out = args
    dur, ctime = _probe(path)
    iv = max(2.0, round(dur / 12, 2))
    if not os.path.exists(out):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf",
                        f"fps=1/{iv},scale=320:-2,tile=6x2:padding=2", "-frames:v", "1", out], check=True)
    return {"dur": dur, "interval": iv, "ctime": ctime}


def scan(project):
    src = os.path.join(E.project_dir(project), "01 - Unedited")
    out = os.path.join(E.edit_dir(project), "scan", "sheets")
    os.makedirs(out, exist_ok=True)
    clips = sorted(f[:-4] for f in os.listdir(src) if f.upper().endswith(".MP4"))
    with ThreadPoolExecutor(E.jobs(6)) as ex:
        metas = list(ex.map(_sheet, [(os.path.join(src, c + ".MP4"), os.path.join(out, c + ".jpg")) for c in clips]))
    meta = dict(sorted(zip(clips, metas), key=lambda kv: (kv[1]["ctime"] or "9", kv[0])))
    with open(os.path.join(E.edit_dir(project), "scan", "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)

    font, big = ImageFont.truetype(FONT, 18), ImageFont.truetype(BOLD, 22)
    order = list(meta)
    for g in range(0, len(order), 4):
        rows = []
        for c in order[g:g + 4]:
            m = meta[c]
            im = Image.open(os.path.join(out, c + ".jpg")).convert("RGB")
            d = ImageDraw.Draw(im)
            for k in range(12):
                t = k * m["interval"]
                if t >= m["dur"]:
                    break
                x, y = (k % 6) * 322, (k // 6) * 182
                d.rectangle([x, y, x + 62, y + 22], fill="black")
                d.text((x + 3, y + 1), f"{t:.0f}s", fill="yellow", font=font)
            row = Image.new("RGB", (im.width, im.height + 30), "white")
            ImageDraw.Draw(row).text((6, 3), f"{c}   dur {m['dur']:.1f}s   {m['ctime'][:16]} (camera clock)",
                                     fill="black", font=big)
            row.paste(im, (0, 30))
            rows.append(row)
        grid = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), "white")
        y = 0
        for r in rows:
            grid.paste(r, (0, y)); y += r.height
        grid.save(os.path.join(out, f"grid_{g // 4:02d}.jpg"), quality=80)
    return len(order), (len(order) + 3) // 4


if __name__ == "__main__":
    n, g = scan(sys.argv[1])
    print(f"{n} clips -> {g} grids")
