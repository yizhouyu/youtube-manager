"""Make a view-only review page for a film built outside the EDL renderer (e.g. 123's code-rendered trailer).
Writes `<proj>/02 - Export/edit/edl.json` with "view_only": true (review_server then refuses save/render),
hard-links the film to `edit/preview.mp4` and to `01 - Unedited/_film/<name>.mp4` (so the shot list can show
thumbnails), and splits the film into labelled sections from a markers file.
Usage: venv/bin/python scripts/view_only_edl.py "<project>" "<film.mp4>" [markers.json]
markers.json = [[t_seconds, "label"], ...]; without it, 8 s sections. Re-run after every re-render
(a new render replaces the file, which breaks the hard links)."""
import json, os, subprocess, sys
proj = os.path.abspath(os.path.expanduser(sys.argv[1] if os.path.isabs(os.path.expanduser(sys.argv[1])) else os.path.join("~/Desktop", sys.argv[1])))
film = os.path.abspath(os.path.expanduser(sys.argv[2]))
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", film],
                           capture_output=True, text=True).stdout.strip())
marks = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else [[t, f"{int(t // 60)}:{int(t % 60):02d}"] for t in range(0, int(dur), 8)]
marks = sorted({round(float(t), 2): str(l) for t, l in marks if 0 <= float(t) < dur - 0.3}.items())
if not marks or marks[0][0] > 0: marks.insert(0, (0.0, "开头"))
edit = os.path.join(proj, "02 - Export", "edit"); src = os.path.join(proj, "01 - Unedited", "_film")
os.makedirs(src, exist_ok=True)
name = "film"
for dst in (os.path.join(edit, "preview.mp4"), os.path.join(src, name + ".mp4")):
    if os.path.lexists(dst): os.remove(dst)
    os.link(film, dst)
edl_p = os.path.join(edit, "edl.json")
if os.path.exists(edl_p):
    old = json.load(open(edl_p))
    if not old.get("view_only"): sys.exit(f"{edl_p} is a real EDL — refusing to overwrite")
shots = []
for i, (t, label) in enumerate(marks):
    t1 = marks[i + 1][0] if i + 1 < len(marks) else dur
    shots.append({"id": f"s{i + 1:03d}", "clip": "_film/" + name, "in": round(t, 3), "out": round(t1, 3), "note": label, "audio": "voice"})
edl = {"view_only": True, "project": os.path.basename(proj), "source_dir": "01 - Unedited", "film": film, "shots": shots}
json.dump(edl, open(edl_p, "w"), ensure_ascii=False, indent=1)
print(f"view-only EDL: {len(shots)} sections over {dur:.1f} s → {edl_p}")
