"""Delete review previews of episodes that are already uploaded (creator, 2026-10-22: 「要保留那些所有能够还原这个影片的
工程文件，但是 preview 应该是可以删」).
Deletes ONLY `02 - Export/edit/preview.mp4` and `02 - Export/edit/previews/` (+ macOS ._ sidecars) — never the EDL,
masters, captions, scripts, cards, music, sources or anything else needed to rebuild the film.
An episode qualifies when `edit/publish_prep/youtube_ids.json` has a `long` id and YouTube reports that video as
processed (public or scheduled). Scans ~/Desktop/<NNN - name> and, if mounted, the drive's YouTube Channel folder.
Usage: venv/bin/python scripts/cleanup_previews.py            # dry run: list what would go
       venv/bin/python scripts/cleanup_previews.py --apply    # delete"""
import glob, json, os, shutil, sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOTS = [os.path.expanduser("~/Desktop"), "/Volumes/YZY's drive/YouTube Channel"]
apply = "--apply" in sys.argv

def size(p):
    if os.path.isfile(p): return os.path.getsize(p)
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)

cands = []
for root in ROOTS:
    if not os.path.isdir(root): continue
    for proj in sorted(glob.glob(os.path.join(root, "[0-9]*[0-9] - *"))):
        edit = os.path.join(proj, "02 - Export", "edit")
        targets = [p for p in (os.path.join(edit, "preview.mp4"), os.path.join(edit, "previews")) if os.path.lexists(p)]
        if not targets: continue
        ids = os.path.join(edit, "publish_prep", "youtube_ids.json")
        vid = (json.load(open(ids)).get("long") if os.path.exists(ids) else None)
        cands.append((proj, vid, targets))

ok_ids = set()
want = sorted({v for _, v, _ in cands if v})
if want:
    from src.auth.youtube_auth import YouTubeAuthenticator
    yt = YouTubeAuthenticator().get_youtube_service()
    for i in range(0, len(want), 50):
        for v in yt.videos().list(part="status", id=",".join(want[i:i + 50])).execute()["items"]:
            if v["status"].get("uploadStatus") == "processed": ok_ids.add(v["id"])

total = 0
for proj, vid, targets in cands:
    name = os.path.basename(proj)
    if vid not in ok_ids:
        print(f"keep  {name}: {'no long id' if not vid else 'video ' + vid + ' not processed'}")
        continue
    for t in targets:
        n = size(t); total += n
        print(f"{'DEL ' if apply else 'would'} {name}: {os.path.relpath(t, proj)} ({n / 1e6:.0f} MB)")
        if apply:
            side = os.path.join(os.path.dirname(t), "._" + os.path.basename(t))
            shutil.rmtree(t) if os.path.isdir(t) and not os.path.islink(t) else os.remove(t)
            if os.path.lexists(side): os.remove(side)
print(f"{'freed' if apply else 'would free'} {total / 1e9:.2f} GB")
