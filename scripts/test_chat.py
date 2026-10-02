"""Review chat: 「评论」 drafts stay pending, 「交给 Agent」 hands them over as one batch, the watcher only
announces handed-over notes. Run: ./venv/bin/python scripts/test_chat.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from flask import Flask  # noqa: E402
from src.editor import chat as C  # noqa: E402

with tempfile.TemporaryDirectory() as proj:
    os.makedirs(os.path.join(proj, "02 - Export", "edit"))
    # an existing thread from before the two-mode send: no status field = sent
    with open(C.path(proj), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": 1, "role": "creator", "text": "旧意见", "ts": "2026-10-01 10:00:00"}) + "\n")
        f.write(json.dumps({"id": 3, "role": "claude", "text": "好", "ts": "2026-10-01 10:01:00"}) + "\n")
    assert C.status(C.load(proj)[0]) == C.SENT, "old messages count as sent"
    assert C.pending_ids(C.load(proj)) == []
    seen = set()
    C.announce(C.load(proj), seen)          # the watcher's start: history is not news
    assert C.announce(C.load(proj), seen) == []

    # 评论 x2: pending, the watcher stays quiet
    a = C.post(proj, "creator", "字幕错了", {"cut_t": 61.5}, C.PENDING)
    b = C.post(proj, "creator", "这段太长\n剪短点", {"clip": "DJI_01", "clip_t": 12.0}, C.PENDING)
    assert (a["id"], b["id"]) == (4, 5), "ids: max id + 1"
    assert a["status"] == "pending" and C.pending_ids(C.load(proj)) == [4, 5]
    assert C.announce(C.load(proj), seen) == [], "pending notes must not wake the agent"

    # an Agent reply in between is never announced and never gets a status
    r = C.post(proj, "claude", "收到")
    assert "status" not in r and C.announce(C.load(proj), seen) == []

    # 交给 Agent with text: the new note + both pending notes = batch 1
    h = C.handoff(proj, "音乐换欢快点", {"cut_t": 90.0, "page": "cut"})
    assert h["batch"] == 1 and h["count"] == 3 and h["ids"] == [4, 5, 7], h
    assert h["message"]["id"] == 7 and h["message"]["status"] == "sent"
    ms = {m["id"]: m for m in C.load(proj)}
    assert all(ms[i]["status"] == "sent" and ms[i]["batch"] == 1 for i in (4, 5, 7))
    assert "sent_ts" in ms[4] and ms[1].get("status") is None, "old lines are left alone"
    assert C.pending_ids(C.load(proj)) == []
    out = C.announce(C.load(proj), seen)
    assert len(out) == 1, out
    assert out[0].startswith("CHAT BATCH b1 (3 条): #4 [成片 1:01.5] 字幕错了 ‖ #5 [原片 DJI_01 @ 12.0s] 这段太长 ⏎ 剪短点 ‖ #7 "), out[0]
    assert C.announce(C.load(proj), seen) == [], "each batch is announced once"

    # 交给 Agent with nothing pending and no text: no-op, file untouched
    before = open(C.path(proj), encoding="utf-8").read()
    assert C.handoff(proj, "  ") == {"batch": None, "ids": [], "count": 0, "message": None}
    assert open(C.path(proj), encoding="utf-8").read() == before

    # 交给 Agent with only text: batch 2 with one note -> a plain CHAT line
    h2 = C.handoff(proj, "片头好")
    assert h2["batch"] == 2 and h2["ids"] == [8]
    assert C.announce(C.load(proj), seen) == ["CHAT #8 片头好"]

    # only pending (no text): batch 3
    C.post(proj, "creator", "a", None, C.PENDING)
    h3 = C.handoff(proj)
    assert h3["batch"] == 3 and h3["ids"] == [9] and h3["message"] is None
    assert C.announce(C.load(proj), seen) == ["CHAT #9 a"]

    # an old page (no mode) still sends at once
    C.post(proj, "creator", "老页面")
    assert C.announce(C.load(proj), seen) == ["CHAT #10 老页面"]

    # a pending note handed over later is announced even though it is older than what came after
    p = C.post(proj, "creator", "先攒着", None, C.PENDING)
    C.post(proj, "creator", "直接发")
    assert C.announce(C.load(proj), seen) == ["CHAT #12 直接发"]
    C.handoff(proj)
    assert C.announce(C.load(proj), seen) == [f"CHAT #{p['id']} 先攒着"]

    # react rewrite keeps statuses and ids
    C._set_react(proj, C.post(proj, "claude", "👍")["id"], 4)
    ms = {m["id"]: m for m in C.load(proj)}
    assert ms[13]["react_to"] == 4 and ms[4]["batch"] == 1 and ms[11]["status"] == "sent"

    # a watcher started while notes are pending announces them once they are handed over
    q = C.post(proj, "creator", "等会儿交", None, C.PENDING)
    seen2 = set()
    C.announce(C.load(proj), seen2)
    C.handoff(proj, "一起")
    out = C.announce(C.load(proj), seen2)
    assert len(out) == 1 and out[0].startswith("CHAT BATCH b5 (2 条): #%d 等会儿交 ‖ #" % q["id"]), out

    # HTTP: modes and the pending list on /api/chat/status
    app = Flask(__name__)
    C.register(app, lambda: proj)
    cl = app.test_client()
    j = cl.post("/api/chat", json={"text": "页面评论", "ctx": {"cut_t": 5}, "page": "cut", "mode": "comment"}).get_json()
    assert j["ok"] and j["message"]["status"] == "pending" and j["message"]["ctx"] == {"cut_t": 5, "page": "cut"}
    pid = j["message"]["id"]
    assert cl.get("/api/chat/status").get_json()["pending"] == [pid]
    assert cl.post("/api/chat", json={"text": " ", "mode": "comment"}).status_code == 400
    assert cl.post("/api/chat", json={"text": ""}).status_code == 400, "old page: empty text is still refused"
    j = cl.post("/api/chat", json={"text": "", "mode": "handoff", "page": "cut"}).get_json()
    assert j["ok"] and j["ids"] == [pid] and j["count"] == 1
    assert cl.get("/api/chat/status").get_json()["pending"] == []
    j = cl.post("/api/chat", json={"text": "", "mode": "handoff"}).get_json()
    assert j["ok"] and j["count"] == 0
    j = cl.post("/api/chat", json={"text": "老页面2", "page": "raw"}).get_json()
    assert j["ok"] and "status" not in j["message"]
    after = cl.get(f"/api/chat?after={pid}").get_json()
    assert [m["text"] for m in after] == ["老页面2"]

    # the injected widget has both buttons and the keyboard hint
    page = C.inject("<html><body></body></html>", "cut")
    assert 'id="cbNote"' in page and "交给 Agent" in page and "'comment'" in page and "'handoff'" in page
print("ok")
