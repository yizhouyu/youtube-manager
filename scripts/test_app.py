"""审片 app: box notes (Q6), cut <-> raw jump (Q7), picks + APPROVALS lines (Q9), status chips, read-only servers.
Never touches a real project or the real APPROVALS.md. Run: ./venv/bin/python scripts/test_app.py"""
import json
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
    assert A.status(proj) == ("", "")
    with open(os.path.join(ed, "questions.json"), "w") as f:
        json.dump([{"id": "q1", "text": "?", "answer": None}], f)
    assert A.status(proj)[1] == "有问题没答"
    with open(os.path.join(ed, "questions.json"), "w") as f:
        json.dump([{"id": "q1", "text": "?", "answer": "好"}], f)
    os.makedirs(os.path.join(ed, "previews"))
    open(os.path.join(ed, "previews", "preview-20261110-081519.mp4"), "w").close()
    assert A.status(proj)[1] == "待审片"
    assert [e["name"] for e in A.episodes()] == ["124 - Test Trip"]
    os.makedirs(os.path.join(desk, "125 - Later", "02 - Export", "edit"))
    os.makedirs(os.path.join(desk, "temp - x", "02 - Export", "edit"))
    os.makedirs(os.path.join(desk, "126 - No Edit Yet"))
    assert [e["num"] for e in A.episodes()] == [125, 124], "newest first; only <N> - <name> with 02 - Export/edit"

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
    assert A.pick(proj, "cover", "F6", now=now) == {"cover": "F6"}
    assert open(os.path.join(th, "CHOSEN")).read() == "F6 (v2) — 2026-11-10 creator: app 点选\n"
    A.pick(proj, "cover", "F3", now=now)
    assert A.current(proj)["cover"] == "F3"
    assert A.pick(proj, "cover", "F3", undo=True, now=now) == {"cover": "F6"}, "undo brings back the previous pick"
    assert open(os.path.join(th, "CHOSEN")).read().startswith("F6 (v2)")
    A.pick(proj, "cover", "F6", undo=True, now=now)
    assert open(os.path.join(th, "CHOSEN")).read() == "E (v1) — agent wrote this\n", "CHOSEN restored"
    A.pick(proj, "approve", "审片通过", now=now)
    assert A.status(proj) == ("ok", "已通过")
    A.pick(proj, "approve", "审片通过", now=now)   # double click: no second line
    A.pick(proj, "short", "sun_late", now=now)
    A.pick(proj, "short", "pay_code", now=now)
    A.pick(proj, "title", "标题一", now=now)
    assert A.current(proj) == {"approve": "审片通过", "short": ["sun_late", "pay_code"], "title": "标题一"}
    A.pick(proj, "approve", "审片通过", undo=True, now=now)
    assert A.status(proj)[1] == "待审片"
    lines = open(os.environ["SHENPIAN_APPROVALS"], encoding="utf-8").read().split("\n")
    assert lines[0] == "- 2026-11-09 · 124 cover: E3 南京路 → 外滩 (v4) — 「E3可以的」", "old lines untouched"
    assert lines[1:] == [
        "- 2026-11-10 · 124 cover: F6 (v2) — app 点选「选这个」",
        "- 2026-11-10 · 124 cover: F3 (v2) — app 点选「选这个」",
        "- 2026-11-10 · 124 cover: F3 (v2) 撤销 — app 点选「已选 · 撤销」",
        "- 2026-11-10 · 124 cover: F6 (v2) 撤销 — app 点选「已选 · 撤销」",
        "- 2026-11-10 · 124 审片通过 — app 点选「审片通过」",
        "- 2026-11-10 · 124 short: sun_late — app 点选「选这个」",
        "- 2026-11-10 · 124 short: pay_code — app 点选「选这个」",
        "- 2026-11-10 · 124 title: 标题一 — app 点选「选这个」",
        "- 2026-11-10 · 124 审片通过 撤销 — app 点选「已通过 · 撤销」",
        ""], lines
    ev = json.load(open(A.picks_path(proj)))
    assert all({"type", "choice", "at"} <= set(e) for e in ev) and ev[2]["undo"] is True and len(ev) == 9

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
    assert eps[1]["label"] == "124" and eps[1]["chip_text"] == "待审片" and not eps[1]["ro"]

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

    # ports: never the live review ports, remembered per project
    p1 = A.pick_port(proj, "raw")
    assert p1 in A.port_range() and not 8748 <= p1 <= 8755
    assert A.pick_port(proj, "raw") == p1 and A.pick_port(proj, "cut", [p1]) != p1

print("ok")
