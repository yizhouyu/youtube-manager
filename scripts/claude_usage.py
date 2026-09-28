#!/usr/bin/env python3
"""Print Claude plan usage (5-hour window + weekly) so a long batch job can budget itself.

    python3 scripts/claude_usage.py            # human-readable
    python3 scripts/claude_usage.py --json     # raw fields
    python3 scripts/claude_usage.py --log "83 start"   # also append a line to sessions/usage_log.tsv

Reads Claude Code's own OAuth token from the macOS Keychain item "Claude Code-credentials" (the same
thing Claude Code / Orca use) and calls the undocumented usage endpoint. The token is never printed
or written anywhere. Field names may change — this prints whatever utilization fields come back.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

URL = "https://api.anthropic.com/api/oauth/usage"


def _token():
    raw = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                         capture_output=True, text=True, check=True).stdout.strip()
    data = json.loads(raw)
    return (data.get("claudeAiOauth") or {}).get("accessToken") or data.get("accessToken")


def usage():
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {_token()}",
                                               "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _fmt_reset(ts):
    if not ts:
        return ""
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        left = t - dt.datetime.now(dt.timezone.utc)
        h, m = divmod(int(left.total_seconds()) // 60, 60)
        d, h = divmod(h, 24)
        return f"resets in {d}d{h}h" if d else f"resets in {h}h{m:02d}m"
    except ValueError:
        return ts


def main():
    u = usage()
    if "--json" in sys.argv:
        print(json.dumps(u, indent=1))
        return
    rows = []
    for k, v in u.items():
        if isinstance(v, dict) and "utilization" in v:
            rows.append((k, v.get("utilization"), _fmt_reset(v.get("resets_at"))))
    for k, pct, reset in rows:
        print(f"{k:28s} {pct if pct is not None else '-':>6}%   {reset}")
    if "--log" in sys.argv:
        label = sys.argv[sys.argv.index("--log") + 1]
        path = os.path.join(os.path.dirname(__file__), "..", "sessions", "usage_log.tsv")
        new = not os.path.exists(path)
        with open(path, "a") as f:
            if new:
                f.write("time_utc\tlabel\t" + "\t".join(k for k, _, _ in rows) + "\n")
            f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M") + f"\t{label}\t"
                    + "\t".join(str(p) for _, p, _ in rows) + "\n")


if __name__ == "__main__":
    main()
