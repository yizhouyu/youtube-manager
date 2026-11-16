"""审片 app: box notes (Q6), cut <-> raw jump (Q7), picks + APPROVALS lines (Q9), status chips, read-only servers.
Never touches a real project or the real APPROVALS.md. Run: ./venv/bin/python scripts/test_app.py"""
import json
import re
import os
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from flask import Flask  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    os.environ["SHENPIAN_ROOT"] = os.path.join(tmp, "Desktop")
    os.environ["SHENPIAN_APPROVALS"] = os.path.join(tmp, "APPROVALS.md")
    os.environ["SHENPIAN_STATE"] = os.path.join(tmp, "ports.json")
    os.environ["SHENPIAN_LOGS"] = os.path.join(tmp, "logs")
    from src.editor import chat as C, locate as L, app_server as A, appbridge as AB, storyboard as SB  # noqa: E402

    desk = os.environ["SHENPIAN_ROOT"]
    proj = os.path.join(desk, "124 - Test Trip")
    ed = os.path.join(proj, "02 - Export", "edit")
    os.makedirs(os.path.join(ed, "publish_prep"))
    th = os.path.join(proj, "02 - Export", "thumbnail")
    os.makedirs(os.path.join(th, "v2"))
    with open(os.path.join(ed, "edl.json"), "w") as f:
        json.dump({"shots": [{"id": "s1", "clip": "A", "in": 10.0, "out": 20.0},
                             {"id": "s2", "clip": "B", "in": 5.0, "out": 8.0},
                             {"id": "s3", "clip": "C", "in": 0.0, "out": 4.0, "enabled": False}]}, f)
    with open(os.environ["SHENPIAN_APPROVALS"], "w") as f:
        f.write("- 2026-11-09 · 124 cover: E3 南京路 → 外滩 (v4) — 「E3可以的」")   # no trailing newline

    # ---- Q6: ctx.box is kept only as 4 numbers in 0-1; text-only notes unchanged
    assert C.clean_box({"cut_t": 3, "box": [0.1, 0.2, 0.3, 0.4]})["box"] == [0.1, 0.2, 0.3, 0.4]
    assert C.clean_box({"box": [0.9, 0.9, 0.5, 0.5]})["box"] == [0.9, 0.9, 0.1, 0.1], "clamped to the frame"
    assert "box" not in C.clean_box({"box": [0, 0, "x", 1]}) and "box" not in C.clean_box({"box": [0.2, 0.2, 0, 0.3]})
    assert C.clean_box({"cut_t": 1}) == {"cut_t": 1}
    app = Flask("t")
    C.register(app, lambda: proj)
    cl = app.test_client()
    r = cl.post("/api/chat", json={"text": "这里框一下", "ctx": {"cut_t": 61.5, "box": [0.25, 0.5, 0.2, 0.1]}, "page": "cut", "mode": "comment"}).get_json()
    assert r["ok"] and r["message"]["ctx"] == {"cut_t": 61.5, "box": [0.25, 0.5, 0.2, 0.1], "page": "cut"}
    r = cl.post("/api/chat", json={"text": "只有文字", "ctx": {"clip": "A", "clip_t": 3.0}, "page": "raw", "mode": "comment"}).get_json()
    assert r["message"]["ctx"] == {"clip": "A", "clip_t": 3.0, "page": "raw"} and r["message"]["status"] == "pending"
    r = cl.post("/api/chat", json={"text": "Short 意见", "ctx": {"short": "sun_late", "short_t": 2.0}, "page": "shorts", "mode": "comment"}).get_json()
    assert r["message"]["ctx"]["page"] == "shorts"
    assert C._where({"short": "sun_late", "short_t": 2.0, "box": [0, 0, 1, 1]}) == "[Short sun_late @ 2.0s ▭] "
    assert C._where({"cut_t": 61.5}) == "[成片 1:01.5] "

    # ---- Q7: cut time -> raw clip/time and back (no previews: the current EDL is the cut)
    assert L.jump(proj, cut_t=12.0) == {"clip": "B", "clip_t": 7.0, "preview": None}
    assert L.jump(proj, cut_t=3.0)["clip"] == "A" and L.jump(proj, cut_t=3.0)["clip_t"] == 13.0
    assert L.jump(proj, clip="A", clip_t=15.0)["t"] == 5.0
    assert L.jump(proj, clip="B", clip_t=6.5)["t"] == 11.5
    assert L.jump(proj, clip="A", clip_t=25.0)["t"] is None, "unused part of a used clip"
    assert L.jump(proj, clip="C", clip_t=1.0)["t"] is None, "disabled shot = not in the cut"
    assert cl.get("/api/chat/jump?cut_t=12").get_json()["clip"] == "B"
    assert cl.get("/api/chat/jump?clip=A&clip_t=15").get_json()["t"] == 5.0

    # ---- status chips
    assert A.status(proj) == ("review", "素材待审"), "footage first (creator 11/11)"
    A.pick(proj, "raw", "素材审完", now=time.strptime("2026-11-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    assert A.status(proj) == ("work", "粗剪中 · 配乐"), "edl.json = C5 done, next is C6"
    with open(os.path.join(ed, "questions.json"), "w") as f:
        json.dump([{"id": "q1", "text": "?", "answer": None}], f)
    assert A.status(proj)[1] == "有问题没答"
    with open(os.path.join(ed, "questions.json"), "w") as f:
        json.dump([{"id": "q1", "text": "?", "answer": "好"}], f)
    os.makedirs(os.path.join(ed, "previews"))
    open(os.path.join(ed, "previews", "preview-20261110-081519.mp4"), "w").close()
    assert A.status(proj)[1] == "粗剪待审", "no creator notes yet"
    assert [e["name"] for e in A.episodes()] == ["124 - Test Trip"]
    os.makedirs(os.path.join(desk, "125 - Later", "02 - Export", "edit"))
    os.makedirs(os.path.join(desk, "temp - x", "02 - Export", "edit"))
    os.makedirs(os.path.join(desk, "126 - No Edit Yet"))
    assert [e["num"] for e in A.episodes()] == [124, 125], "by number; only <N> - <name> with 02 - Export/edit"
    assert A.status(os.path.join(desk, "125 - Later")) == ("review", "素材待审"), "just organized: his footage review is next"
    os.makedirs(os.path.join(desk, "202612Trip", "sub"))
    open(os.path.join(desk, "202612Trip", "GX010001.MP4"), "w").close()
    os.makedirs(os.path.join(desk, "202601Done"))
    assert [(t["name"], t["clips"]) for t in A.trips()] == [("202612Trip", 1)], "待整理 = trip folder with loose clips"

    # ---- covers / titles candidates
    with open(os.path.join(th, "v2", "covers.json"), "w") as f:
        json.dump({"new": [{"id": "F6", "title": "F6 · 清晨"}, {"id": "F3", "title": "F3"}], "old": [{"id": "E"}], "dropped": [{"id": "X"}]}, f)
    open(os.path.join(th, "v2", "F6_360.jpg"), "w").close()
    cv = A.covers(proj)
    assert [c["id"] for c in cv] == ["F6", "F3", "E"] and cv[0]["img"] == "v2/F6_360.jpg" and cv[0]["v"] == 2
    with open(os.path.join(ed, "publish_prep", "draft_metadata.md"), "w") as f:
        f.write("# x\n\n## Title candidates\n- A (main, recommended): 标题一\n- B2: 标题二\n\n## Description\n- not: a title\n")
    assert A.titles(proj) == [{"id": "A", "text": "标题一"}, {"id": "B2", "text": "标题二"}]
    with open(os.path.join(ed, "publish_prep", "metadata_final.txt"), "w") as f:
        f.write("# x\n\n[YouTube title — main]\n主标题\n\n[YouTube title — A/B (title-only test)]\n备选\n\n[English title (en)]\nEN\n")
    assert A.titles(proj) == [{"id": "main", "text": "主标题"}, {"id": "A/B", "text": "备选"}]

    # ---- Q9 picks: APPROVALS lines, app_picks.json, CHOSEN, undo
    with open(os.path.join(th, "CHOSEN"), "w") as f:
        f.write("E (v1) — agent wrote this\n")
    now = time.strptime("2026-11-10 12:00:00", "%Y-%m-%d %H:%M:%S")
    assert A.pick(proj, "cover", "F6", now=now) == {"raw": "素材审完", "cover": "F6"}
    assert open(os.path.join(th, "CHOSEN")).read() == "F6 (v2) — 2026-11-10 creator: app 点选\n"
    A.pick(proj, "cover", "F3", now=now)
    assert A.current(proj)["cover"] == "F3"
    assert A.pick(proj, "cover", "F3", undo=True, now=now) == {"raw": "素材审完", "cover": "F6"}, "undo brings back the previous pick"
    assert open(os.path.join(th, "CHOSEN")).read().startswith("F6 (v2)")
    A.pick(proj, "cover", "F6", undo=True, now=now)
    assert open(os.path.join(th, "CHOSEN")).read() == "E (v1) — agent wrote this\n", "CHOSEN restored"
    assert A.picks_now(proj)["cover"] == "E", "the agent's CHOSEN shows as the pick"
    with open(os.path.join(th, "CHOSEN"), "w") as f:
        f.write("F6 (v2) — 2026-11-09 creator: 「F6不错」\n")
    assert A.chosen_cover(proj) == "F6" and A.covers(proj)[0]["chosen"]
    with open(os.path.join(th, "v3", "covers.json") if os.path.isdir(os.path.join(th, "v3")) else os.path.join(th, "v2", "covers.json"), "w") as f:
        json.dump({"new": [{"id": "F6_dawn"}, {"id": "F3"}]}, f)
    assert A.chosen_cover(proj) == "F6_dawn", "short id resolves to the candidate"
    A.pick(proj, "cover", "F6_dawn", undo=True, now=now)
    assert not os.path.exists(os.path.join(th, "CHOSEN")) and json.load(open(A.picks_path(proj)))[-1]["chosen_was"].startswith("F6 (v2)")
    with open(os.path.join(th, "CHOSEN"), "w") as f:
        f.write("E (v1) — agent wrote this\n")
    A.pick(proj, "approve", "审片通过", now=now)
    assert A.status(proj) == ("ok", "已通过")
    A.pick(proj, "approve", "审片通过", now=now)   # double click: no second line
    A.pick(proj, "short", "sun_late", now=now)
    A.pick(proj, "short", "pay_code", now=now)
    A.pick(proj, "title", "标题一", now=now)
    assert A.current(proj) == {"raw": "素材审完", "approve": "审片通过", "short": ["sun_late", "pay_code"], "title": "标题一"}
    A.pick(proj, "approve", "审片通过", undo=True, now=now)
    assert A.status(proj)[1] == "粗剪待审"
    pv = os.path.join(ed, "previews", "preview-20261110-081519.mp4")
    os.utime(pv, (1, time.mktime(time.strptime("2026-11-10 10:00:00", "%Y-%m-%d %H:%M:%S"))))
    with open(os.path.join(ed, "chat.jsonl"), "a") as f:
        f.write(json.dumps({"id": 90, "role": "creator", "text": "x", "ts": "2026-11-10 09:00:00", "status": "sent"}) + "\n")
    assert A.status(proj)[1] == "精剪待审", "notes older than the preview = applied"
    with open(os.path.join(ed, "chat.jsonl"), "a") as f:
        f.write(json.dumps({"id": 91, "role": "creator", "text": "y", "ts": "2026-11-10 11:00:00", "status": "sent"}) + "\n")
    assert A.status(proj) == ("work", "改片中")
    lines = open(os.environ["SHENPIAN_APPROVALS"], encoding="utf-8").read().split("\n")
    assert lines[0] == "- 2026-11-09 · 124 cover: E3 南京路 → 外滩 (v4) — 「E3可以的」", "old lines untouched"
    assert lines[1:] == [
        "- 2026-11-10 · 124 素材审完 — app 点选「素材审完」",
        "- 2026-11-10 · 124 cover: F6 (v2) — app 点选「选这个」",
        "- 2026-11-10 · 124 cover: F3 (v2) — app 点选「选这个」",
        "- 2026-11-10 · 124 cover: F3 (v2) 撤销 — app 点选「已选 · 撤销」",
        "- 2026-11-10 · 124 cover: F6 (v2) 撤销 — app 点选「已选 · 撤销」",
        "- 2026-11-10 · 124 cover: F6_dawn (v2) 撤销 — app 点选「已选 · 撤销」",
        "- 2026-11-10 · 124 审片通过 — app 点选「审片通过」",
        "- 2026-11-10 · 124 short: sun_late — app 点选「选这个」",
        "- 2026-11-10 · 124 short: pay_code — app 点选「选这个」",
        "- 2026-11-10 · 124 title: 标题一 — app 点选「选这个」",
        "- 2026-11-10 · 124 审片通过 撤销 — app 点选「已通过 · 撤销」",
        ""], lines
    ev = json.load(open(A.picks_path(proj)))
    assert all({"type", "choice", "at"} <= set(e) for e in ev) and ev[3]["undo"] is True and len(ev) == 11

    # read-only: a folder outside the episodes root never gets a pick
    other = os.path.join(tmp, "Volumes", "74 - Old")
    os.makedirs(os.path.join(other, "02 - Export", "edit"))
    assert not A.writable(other) and A.writable(proj)
    try:
        A.pick(other, "approve", "审片通过")
        raise AssertionError("read-only folder accepted a pick")
    except ValueError:
        pass
    assert not os.path.exists(A.picks_path(other))
    cl2 = A.app.test_client()
    assert cl2.post("/api/pick", json={"path": other, "type": "approve", "choice": "审片通过"}).status_code == 400
    assert cl2.post("/api/pick", json={"path": proj, "type": "bogus", "choice": "x"}).status_code == 400
    eps = cl2.get("/api/episodes").get_json()
    assert eps[0]["label"] == "124" and eps[0]["chip_text"] == "改片中" and not eps[0]["ro"]

    # read-only servers refuse every write and never queue a storyboard
    ro = Flask("ro")
    C.register(ro, lambda: proj)
    AB.read_only(ro)
    n = len(C.load(proj))
    assert ro.test_client().post("/api/chat", json={"text": "x", "mode": "comment"}).status_code == 403
    assert len(C.load(proj)) == n
    assert SB.request(os.path.join(ed, "edl.json"), os.path.join(tmp, "sb")) == {"ready": False, "state": "error"}
    assert not os.path.exists(os.path.join(tmp, "sb"))
    SB.READ_ONLY = AB.RO = False

    # agent control (scripts/shenpian, shenpian:// URLs): open / tab / seek only
    P = A.parse_agent_url
    assert P("shenpian://open?ep=124&tab=cut&t=83.5") == {"action": "open", "path": os.path.realpath(proj), "tab": "cut",
                                                         "t": 83.5, "clip": None, "bg": False}
    assert P("shenpian://open?path=" + urllib.parse.quote(other) + "&tab=%E7%B4%A0%E6%9D%90&bg=1")["path"] == os.path.realpath(other)
    assert P("shenpian://open?path=" + urllib.parse.quote(other) + "&tab=%E7%B4%A0%E6%9D%90&bg=1")["tab"] == "raw", "Chinese tab names"
    assert P("shenpian://open?ep=125")["path"].endswith("125 - Later") and P("shenpian://open?ep=125")["bg"] is False
    assert P("shenpian://open?ep=124&tab=raw&clip=A&t=3")["clip"] == "A"
    assert P("shenpian://quit") == {"action": "quit"}
    for bad in ("http://open?ep=124", "shenpian://pick?ep=124&cover=F6", "shenpian://approve?ep=124", "shenpian://open",
                "shenpian://open?ep=999", "shenpian://open?ep=124&tab=bogus", "shenpian://open?ep=124&t=-1",
                "shenpian://open?ep=124&t=x", "shenpian://open?path=/no/such/folder"):
        try:
            P(bad)
            raise AssertionError("accepted " + bad)
        except ValueError:
            pass
    assert cl2.get("/api/app/parse?url=" + urllib.parse.quote("shenpian://open?ep=124&tab=cut")).get_json()["tab"] == "cut"
    assert cl2.get("/api/app/parse?url=" + urllib.parse.quote("shenpian://save?ep=124")).status_code == 400
    st = cl2.get("/api/app/state").get_json()
    assert st["running"] and st["project"] is None and st["dirty"] is False
    assert cl2.post("/api/app/state", json={"project": proj, "tab": "cut", "t": 61.234, "dirty": True}).get_json()["ok"]
    st = cl2.get("/api/app/state").get_json()
    assert (st["project"], st["tab"], st["t"], st["dirty"], st["label"], st["read_only"]) == (proj, "cut", 61.23, True, "124", False)
    cl2.post("/api/app/state", json={"project": proj, "tab": "nonsense"})
    assert cl2.get("/api/app/state").get_json()["tab"] is None
    assert A.server_info_path() == os.path.join(tmp, "server.json")
    assert not [r for r in A.app.url_map.iter_rules() if "/api/app/" in r.rule and "POST" in r.methods and r.rule != "/api/app/state"], \
        "the agent interface has no write routes"

    # scripts/shenpian open: cold start (foreground or --background) puts the episode in the app's environment
    # instead of sending a URL into a starting app (that URL got lost: 2026-11-10); a running app gets the URL
    import importlib.machinery
    import types
    SP = types.ModuleType("shenpian_cli")
    SP.__file__ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shenpian")
    importlib.machinery.SourceFileLoader("shenpian_cli", os.path.join(os.path.dirname(__file__), "shenpian")).exec_module(SP)
    calls, running = [], {"on": False}
    target = {"running": True, "project": os.path.realpath(proj), "tab": "cut", "t": 83.5, "error": None}
    SP.server = lambda: {"pid": 1, "port": 1, "app_pid": 1} if running["on"] else None
    SP.state = lambda: target
    SP.app_bundle = lambda: "/Apps/审片.app"
    SP.subprocess = types.SimpleNamespace(run=lambda args, **k: calls.append(("run", args, None)),
                                          Popen=lambda args, env=None, **k: calls.append(("popen", args, env)), DEVNULL=None)
    SP.time = types.SimpleNamespace(time=time.time, sleep=lambda s: None)
    def cli_open(*argv):
        calls.clear()
        try:
            SP.cmd_open(types.SimpleNamespace(**dict(dict(ep=proj, tab="cut", t=83.5, clip=None, background=False, wait=5), **dict(argv))))
        except SystemExit as e:
            assert not e.code, e.code
        return calls[0]
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        kind, args, _ = cli_open()                                 # cold, foreground: open -a <app> --env ...
        assert kind == "run" and args[:3] == ["open", "-a", "/Apps/审片.app"] and not any("://" in x for x in args), args
        assert "SHENPIAN_OPEN=" + os.path.realpath(proj) in args and "SHENPIAN_TAB=cut" in args and "SHENPIAN_T=83.5" in args
        kind, args, env = cli_open(("background", True))           # cold, background: the app itself, off-focus
        assert kind == "popen" and args[0].endswith("Contents/MacOS/Shenpian") and env["SHENPIAN_BACKGROUND"] == "1"
        assert env["SHENPIAN_OPEN"] == os.path.realpath(proj) and env["SHENPIAN_TAB"] == "cut" and env["SHENPIAN_T"] == "83.5"
        running["on"] = True                                        # running: the URL (open -g when --background)
        kind, args, _ = cli_open(("background", True))
        assert args[:2] == ["open", "-g"] and args[2].startswith("shenpian://open?path=") and "tab=cut" in args[2] and "bg=1" in args[2]
        kind, args, _ = cli_open()
        assert args[0] == "open" and args[1].startswith("shenpian://open?") and "t=83.5" in args[1]
        assert A.parse_agent_url(args[1])["path"] == os.path.realpath(proj), "the CLI's URL means what it says"

    # 本地视频 (local_player.py): dragged-in videos are copied (never moved) into one folder, listed, served from there only
    from src.editor import local_player as LP  # noqa: E402
    os.environ["SHENPIAN_LOCAL"] = lv = os.path.join(tmp, "Movies", "审片播放器")
    drops = os.path.join(tmp, "Downloads")
    os.makedirs(drops)
    def mk(path, data):
        with open(path, "wb") as f:
            f.write(data)
        return path
    src1 = mk(os.path.join(drops, "旅行 vlog.mp4"), b"MP4" * 1000)
    lc = A.app.test_client()
    r = lc.post("/api/local/add", json={"paths": [src1]}).get_json()
    assert r["ok"] and r["items"] == [{"name": "旅行 vlog.mp4", "ready": True, "job": None, "dup": False}], r
    assert open(os.path.join(lv, "旅行 vlog.mp4"), "rb").read() == b"MP4" * 1000, "a full copy (clonefile on APFS)"
    assert open(src1, "rb").read() == b"MP4" * 1000 and os.path.isfile(src1), "the original stays where it was, unchanged"
    r = lc.post("/api/local/add", json={"paths": [src1]}).get_json()
    assert r["items"][0]["dup"] and r["items"][0]["name"] == "旅行 vlog.mp4" and len(os.listdir(lv)) == 1, "same name + size: no 2nd copy"
    other_dir = os.path.join(tmp, "Other")
    os.makedirs(other_dir)
    src2 = mk(os.path.join(other_dir, "旅行 vlog.mp4"), b"x" * 10)   # same name, another file
    assert LP.add(src2)["name"] == "旅行 vlog (2).mp4" and LP.add(src2)["dup"], "a different file with the same name gets (2)"
    mk(os.path.join(other_dir, "notes.txt"), b"n")
    r = lc.post("/api/local/add", json={"paths": [os.path.join(other_dir, "notes.txt"), drops, os.path.join(drops, "nope.mp4"), "rel.mp4"]}).get_json()
    assert not r["ok"] and len(r["rejected"]) == 4 and "不是能播的视频" in r["rejected"][0]["error"] and "文件夹" in r["rejected"][1]["error"]
    assert lc.post("/api/local/add", json={"paths": []}).status_code == 400
    assert lc.post("/api/local/add", data="paths=" + src1).status_code == 415, "JSON only"
    assert lc.post("/api/local/add", json={"paths": [src1]}, headers={"Origin": "http://evil.example"}).status_code == 403
    # a chunked copy (another volume: no clonefile) runs in a thread; meanwhile the original plays via its job id
    os.environ["SHENPIAN_NO_CLONE"] = "1"
    src3 = mk(os.path.join(drops, "big.mov"), os.urandom(LP.CHUNK * 2 + 17))
    r3 = LP.add(src3, wait=True)
    assert r3["ready"] and r3["job"] and open(os.path.join(lv, "big.mov"), "rb").read() == open(src3, "rb").read()
    assert not [n for n in os.listdir(lv) if n.startswith(".partial")], "temp file renamed into place"
    rr = lc.get("/local/src/" + r3["job"])
    assert rr.status_code == 302 and rr.headers["Location"].endswith("/local/v/big.mov"), "copy done: the copy, not the original"
    LP.JOBS["j1"] = {"id": "j1", "name": "slow.mp4", "orig": "slow.mp4", "src": src1, "size": 3000, "copied": 5, "state": "copying",
                     "error": None, "started": time.time(), "ended": None}
    assert lc.get("/local/src/j1").get_data() == b"MP4" * 1000, "while copying: the dropped original"
    assert lc.get("/api/local/state?name=slow.mp4&job=j1").get_json()["job"]["state"] == "copying", "player works before the copy is there"
    assert lc.get("/api/local/list").get_json()["jobs"][0]["id"] in ("j1", r3["job"])
    assert lc.get("/local/src/nojob").status_code == 404
    del LP.JOBS["j1"]
    os.environ.pop("SHENPIAN_NO_CLONE")
    # the folder is the list: files put there in Finder appear; hidden / non-video files don't; newest first
    time.sleep(0.05)
    mk(os.path.join(lv, "finder.m4v"), b"m4v")
    mk(os.path.join(lv, "readme.txt"), b"t")
    mk(os.path.join(lv, ".partial-abc.mp4"), b"p")
    secret = mk(os.path.join(tmp, "secret.mp4"), b"SECRET")
    os.symlink(secret, os.path.join(lv, "link-out.mp4"))
    names = [x["name"] for x in lc.get("/api/local/list").get_json()["items"]]
    assert names[0] == "finder.m4v" and set(names) == {"finder.m4v", "big.mov", "旅行 vlog (2).mp4", "旅行 vlog.mp4"}, names
    # serving: only regular files right inside the folder
    rv = lc.get("/local/v/" + urllib.parse.quote("旅行 vlog.mp4"))
    assert rv.status_code == 200 and rv.get_data() == b"MP4" * 1000 and rv.mimetype == "video/mp4"
    rv = lc.get("/local/v/big.mov", headers={"Range": "bytes=0-3"})
    assert rv.status_code == 206 and len(rv.get_data()) == 4 and rv.mimetype == "video/quicktime", "range requests (seeking)"
    for bad in ("..%2Fsecret.mp4", "../secret.mp4", "%2E%2E/secret.mp4", "link-out.mp4", ".partial-abc.mp4", "readme.txt",
                "x/../../secret.mp4", urllib.parse.quote(secret), "nope.mp4"):
        rb = lc.get("/local/v/" + bad, follow_redirects=True)
        assert rb.status_code == 404 and b"SECRET" not in rb.get_data(), (bad, rb.status_code)
    assert LP.safe_path("../secret.mp4") is None and LP.safe_path(secret) is None and LP.safe_path("link-out.mp4") is None
    # positions per file + the last speed
    assert lc.post("/api/local/pos", json={"name": "big.mov", "t": 61.27, "dur": 300}).get_json()["ok"]
    assert lc.post("/api/local/pos", json={"speed": 2}).get_json()["ok"]
    st = lc.get("/api/local/state?name=big.mov").get_json()
    assert (st["t"], st["dur"], st["done"], st["speed"]) == (61.3, 300, False, 2), st
    lc.post("/api/local/pos", json={"name": "finder.m4v", "t": 298, "dur": 300})
    st = lc.get("/api/local/state?name=finder.m4v").get_json()
    assert st["t"] == 0 and st["done"], "watched to the end: next time from the top"
    assert [x for x in lc.get("/api/local/list").get_json()["items"] if x["name"] == "big.mov"][0]["t"] == 61.3
    assert lc.post("/api/local/pos", json={"speed": 7}).status_code == 400
    assert lc.post("/api/local/pos", json={"name": "big.mov", "t": "x"}).status_code == 400
    assert lc.post("/api/local/pos", json={"name": "../secret.mp4", "t": 1}).status_code == 404
    assert lc.post("/api/local/pos", json={"speed": 1}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert lc.get("/api/local/state?name=link-out.mp4").status_code == 404
    assert json.load(open(os.path.join(tmp, "local_player.json")))["speed"] == 2, "kept next to the ports memory"
    assert lc.get("/local/play?name=big.mov").status_code == 200
    assert set(os.listdir(drops)) == {"旅行 vlog.mp4", "big.mov"}, "originals untouched"

    # 批注 on a 本地视频 (local_comments.py): app store + a sidecar md / frames next to the ORIGINAL, nothing else
    import shutil as _sh
    import subprocess as _sp
    from src.editor import local_comments as LC  # noqa: E402
    os.environ["SHENPIAN_NO_SPOTLIGHT"] = "1"
    rtmp = os.path.realpath(tmp)   # /var -> /private/var: paths as the code records them
    proj_x = os.path.join(rtmp, "AIProj", "03 - Making-of", "export")
    os.makedirs(proj_x)
    clip = os.path.join(proj_x, "春风 v7.mp4")
    has_ff = bool(_sh.which("ffmpeg"))
    if has_ff:   # a silent 2 s test picture (no audio track at all)
        _sp.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "2", "-an",
                 "-pix_fmt", "yuv420p", clip], check=True)
    else:
        mk(clip, b"not really a video")
    vid = LP.add(clip)["name"]
    assert LP.load_state()["orig"][vid]["path"] == os.path.realpath(clip), "the copy remembers its original"
    def snap():
        return {os.path.join(r, f): os.stat(os.path.join(r, f)).st_mtime for r, _, fs in os.walk(rtmp) for f in fs}
    before = snap()
    C_ = lambda **b: lc.post("/api/local/comments", json=dict(b, name=vid))   # noqa: E731
    r = C_(op="add", t=1.2, text="字幕太快", box=[0.1, 0.2, 0.3, 0.4], dur=2.0).get_json()
    assert r["ok"] and r["on"] and r["comments"][0]["id"] == 1 and r["comments"][0]["box"] == [0.1, 0.2, 0.3, 0.4] and r["sidecar"]["ok"]
    md_p, fr_d = os.path.join(proj_x, "春风 v7.comments.md"), os.path.join(proj_x, "春风 v7.comments")
    assert r["sidecar"]["md"] == md_p
    md = open(md_p, encoding="utf-8").read()
    frame_link = " [画面](<春风 v7.comments/c1.jpg>)" if has_ff else ""
    assert "- [ ] [00:01.2] 字幕太快（框选 0.10,0.20,0.30,0.40）" + frame_link + " <!-- id:1 -->" in md, md
    assert "原文件：" + os.path.realpath(clip) in md and "## 待处理" in md and "## 已解决" in md
    if has_ff:
        jpg = open(os.path.join(fr_d, "c1.jpg"), "rb").read()
        assert jpg[:2] == b"\xff\xd8", "a JPEG frame next to the md"
    r = C_(op="add", t=0.5, text="开头\n太长").get_json()
    assert [c["id"] for c in r["comments"]] == [2, 1], "sorted by time"
    assert "- [ ] [00:00.5] 开头 / 太长" in open(md_p, encoding="utf-8").read()
    assert C_(op="edit", id=1, text="字幕太快了").get_json()["comments"][1]["text"] == "字幕太快了"
    r = C_(op="resolve", id=2, resolved=True).get_json()
    md = open(md_p, encoding="utf-8").read()
    assert "- [x] [00:00.5]" in md and md.index("## 已解决") < md.index("- [x] [00:00.5]") and "字幕太快了" in md
    assert LP.open_comments(vid) == 1 and [x for x in LP.list_videos() if x["name"] == vid][0]["notes"] == 1
    # an agent ticks the md -> the app reads the resolved flag back (only that), then rewrites the md
    with open(md_p, encoding="utf-8") as f:
        md = f.read()
    with open(md_p, "w", encoding="utf-8") as f:
        f.write(md.replace("- [ ] [00:01.2] 字幕太快了", "- [x] [00:01.2] 改掉的文字不算").replace("- [x] [00:00.5]", "- [ ] [00:00.5]"))
    os.utime(md_p, (time.time() + 5, time.time() + 5))
    r = lc.get("/api/local/comments?name=" + urllib.parse.quote(vid)).get_json()
    got = {c["id"]: (c["resolved"], c["text"]) for c in r["comments"]}
    assert got == {1: (True, "字幕太快了"), 2: (False, "开头\n太长")}, got
    md = open(md_p, encoding="utf-8").read()
    assert "- [x] [00:01.2] 字幕太快了" in md and "改掉的文字不算" not in md, "md rewritten from the json"
    assert "待处理 1 条 · 已解决 1 条" in md
    # clipboard md: no image links
    cp = lc.get("/api/local/comments.md?name=" + urllib.parse.quote(vid)).get_data(as_text=True)
    assert "字幕太快了" in cp and "[画面]" not in cp and "<!-- id:1 -->" in cp
    # delete: the line and its frame go
    r = C_(op="delete", id=1).get_json()
    assert [c["id"] for c in r["comments"]] == [2] and "id:1 " not in open(md_p, encoding="utf-8").read()
    assert not os.path.exists(os.path.join(fr_d, "c1.jpg"))
    # bad requests
    assert C_(op="add", t=1, text="  ").status_code == 400 and C_(op="edit", id=99, text="x").status_code == 400
    assert C_(op="add", t=-1, text="x").status_code == 400 and C_(op="nope").status_code == 400
    assert lc.post("/api/local/comments", json={"name": "../x.mp4", "op": "add", "t": 1, "text": "x"}).status_code == 404
    assert lc.get("/api/local/comments?name=..%2Fx.mp4").status_code == 404
    assert C_(op="add", t=1, text="x").status_code == 200 and lc.post("/api/local/comments", json={"name": vid, "op": "add", "t": 1, "text": "x"},
                                                                     headers={"Origin": "http://evil.example"}).status_code == 403
    assert not C_(op="toggle", on=False).get_json()["on"] and not LC.load(vid)["on"], "the 批注 switch is remembered per video"
    # nothing written outside the app store and the sidecar next to the original; the videos themselves untouched
    after = snap()
    allowed = (os.path.join(LP.folder(), ".comments") + os.sep, md_p, fr_d + os.sep, os.path.join(rtmp, "local_player.json"))
    new_or_changed = [p for p in after if before.get(p) != after[p]]
    assert all(p.startswith(allowed) or p in allowed for p in new_or_changed), new_or_changed
    assert before[clip] == after[clip] and before[os.path.join(LP.folder(), vid)] == after[os.path.join(LP.folder(), vid)]
    # no sidecar: unknown original (put in the folder by hand), unwritable folder, original gone, a symlink in the way
    r = lc.post("/api/local/comments", json={"name": "finder.m4v", "op": "add", "t": 1, "text": "x"}).get_json()
    assert r["ok"] and not r["sidecar"]["ok"] and "不知道原文件" in r["sidecar"]["why"] and r["comments"][0]["text"] == "x"
    ro_dir = os.path.join(tmp, "RO")
    os.makedirs(ro_dir)
    ro_clip = mk(os.path.join(ro_dir, "ro.mp4"), b"ro" * 50)
    ro_name = LP.add(ro_clip)["name"]
    os.chmod(ro_dir, 0o555)
    try:
        r = lc.post("/api/local/comments", json={"name": ro_name, "op": "add", "t": 1, "text": "x"}).get_json()
        assert r["ok"] and not r["sidecar"]["ok"] and "不能写" in r["sidecar"]["why"] and os.listdir(ro_dir) == ["ro.mp4"]
    finally:
        os.chmod(ro_dir, 0o755)
    os.symlink(os.path.join(tmp, "elsewhere.md"), os.path.join(ro_dir, "ro.comments.md"))
    r = lc.post("/api/local/comments", json={"name": ro_name, "op": "add", "t": 2, "text": "y"}).get_json()
    assert not r["sidecar"]["ok"] and not os.path.exists(os.path.join(tmp, "elsewhere.md")), "never writes through a symlink"
    os.remove(os.path.join(ro_dir, "ro.comments.md"))
    os.remove(ro_clip)   # the original went away (a temp file of this test)
    assert "不在原来的地方" in lc.get("/api/local/comments?name=ro.mp4").get_json()["sidecar"]["why"]
    assert len(LC.load(ro_name)["comments"]) == 2, "kept in the app store"
    # scripts/shenpian comments: by the original's path, by name; unknown -> error
    env = dict(os.environ)
    sh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shenpian")
    out = _sp.run([sh, "comments", clip], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stdout.startswith("# 批注 · " + vid) and "开头 / 太长" in out.stdout, out.stderr
    if has_ff:
        assert os.path.join(fr_d, "c2.jpg") in out.stdout, "absolute frame paths in the terminal"
    assert _sp.run([sh, "comments", vid], capture_output=True, text=True, env=env).stdout == out.stdout
    assert _sp.run([sh, "comments", os.path.join(tmp, "nothing.mp4")], capture_output=True, text=True, env=env).returncode != 0

    # ports: never the live review ports, remembered per project
    p1 = A.pick_port(proj, "raw")
    assert p1 in A.port_range() and not 8748 <= p1 <= 8755
    assert A.pick_port(proj, "raw") == p1 and A.pick_port(proj, "cut", [p1]) != p1

# the page's script must parse: one quoting slip blanked the whole sidebar (11/11)
import shutil, subprocess, tempfile
if shutil.which("node"):
    from src.editor import local_player as LP  # noqa: E402
    for page in (A.app.test_client().get("/").get_data(as_text=True), LP.PAGE):   # the shell and the local player
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write("\n".join(re.findall(r"<script>(.*?)</script>", page, re.S)))
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:600]

print("ok")
