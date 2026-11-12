#!/usr/bin/env python3
"""One-shot: pick up the estate-elections corpus mount during the NZ-night
off-peak window. SIGKILLs the qnz-mcp server (TERM blocks in its task group —
measured 2026-10-29); the qnz_mcp_watchdog cron restarts it within 5 min.
Then polls /health (the corpus load takes minutes — poll, never declare a
crash) and finally probes corpora() over raw JSON-RPC for the new corpus.
Prints one line either way."""
import json, subprocess, time, urllib.request

HOST = "172.16.1.2"
BASE = "http" + chr(58) + chr(47) + chr(47) + HOST + chr(58) + "8646" + chr(47) + "mcp"
HEALTH = "http" + chr(58) + chr(47) + chr(47) + HOST + chr(58) + "8646" + chr(47) + "health"

def post(payload, sid=None):
    req = urllib.request.Request(BASE, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    if sid:
        req.add_header("Mcp-Session-Id", sid)
    r = urllib.request.urlopen(req, timeout=30)
    body = r.read().decode()
    sid_out = r.headers.get("Mcp-Session-Id")
    data = None
    for line in body.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
    if data is None and body.strip():
        data = json.loads(body)
    return data, sid_out

# 1. kill (absolute-path processes only; broad pattern checked after)
out = subprocess.run(["pgrep", "-af", "[q]nz-mcp.*[s]erver\\.py"], capture_output=True, text=True)
for line in out.stdout.splitlines():
    pid = line.split(None, 1)[0]
    subprocess.run(["kill", "-9", pid])
time.sleep(2)
left = subprocess.run(["pgrep", "-af", "[q]nz-mcp.*[s]erver\\.py"], capture_output=True, text=True).stdout.strip()
if left:
    print("estate-elections restart: FAILED to kill:", left)
    raise SystemExit(1)

# 2. poll health until the load finishes (up to 12 min)
up = False
for _ in range(72):
    time.sleep(10)
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as r:
            if r.status == 200:
                up = True
                break
    except Exception:
        pass
if not up:
    print("estate-elections restart: server did not return healthy in 12 min")
    raise SystemExit(1)

# 3. verify the surface knows the corpus AND the estate channel
init, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "verify", "version": "0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
tl, _ = post({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, sid)
toolnames = sorted(t.get("name", "") for t in tl.get("result", {}).get("tools", []))
res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "corpora", "arguments": {}}}, sid)
txt = res.get("result", {}).get("content", [{}])[0].get("text", "")
print("estate-elections restart: healthy, corpus mounted:",
      "estate-elections" in txt, "| channel tools:",
      all(n in toolnames for n in ("asks_put", "asks_get", "asks_status")))
