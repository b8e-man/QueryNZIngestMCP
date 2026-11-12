#!/usr/bin/env python3
"""channel_post.py — our side of the estate channel (estate-channel@2026-11-13).
Appends one message to channel/outbox.jsonl (never edits) so the estate reads
it with asks_get. Also the writer for channel/status.jsonl rows.

  post a reply/question/report/refusal:
    channel_post.py message --kind reply --request estate-collect@2026-11-13 \
        --body body.json [--amends ID] [--answers-message-id ID]
  record a status row (state per request/section):
    channel_post.py status --request estate-collect@2026-11-13 \
        --section electoral-commission --state collecting \
        [--corpus estate-elections] [--last-block 'host|at|what'] [--next-run ISO]

Nothing here ever carries a credential. Append-only; ids are content-derived
and stable."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CH = os.path.join(BASE, "channel")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("message")
    m.add_argument("--kind", required=True,
                   choices=["reply", "question", "report", "refusal"])
    m.add_argument("--request", required=True)
    m.add_argument("--body", required=True, help="path to the body JSON file")
    m.add_argument("--amends")
    m.add_argument("--answers-message-id")
    s = sub.add_parser("status")
    s.add_argument("--request", required=True)
    s.add_argument("--section", default="request")
    s.add_argument("--state", required=True,
                   choices=["received", "accepted", "building", "collecting",
                            "blocked", "done", "withdrawn"])
    s.add_argument("--corpus")
    s.add_argument("--last-block", help="host|at|what")
    s.add_argument("--next-run")
    args = ap.parse_args()

    for d in (CH, os.path.join(CH, "bodies"), os.path.join(CH, "attachments")):
        os.makedirs(d, exist_ok=True)

    if args.cmd == "message":
        body = json.load(open(args.body))
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        bp = os.path.join(CH, "bodies", sha)
        if not os.path.exists(bp):
            with open(bp, "wb") as f:
                f.write(raw)
        row = {"message_id": "out-" + sha[:16], "at": now_iso(),
               "request_id": args.request, "amends": args.amends,
               "answers_message_id": args.answers_message_id,
               "kind": args.kind, "body_sha256": sha, "body_size": len(raw)}
        with open(os.path.join(CH, "outbox.jsonl"), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps({"message_id": row["message_id"], "sha256": sha}))
    else:
        lb = None
        if args.last_block:
            host, at, what = (args.last_block.split("|", 2) + ["", ""])[:3]
            lb = {"host": host, "at": at, "what": what}
        row = {"request_id": args.request, "section": args.section,
               "state": args.state, "corpus": args.corpus,
               "last_block": lb, "next_run": args.next_run, "at": now_iso()}
        with open(os.path.join(CH, "status.jsonl"), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps({"status_row": row["at"], "state": args.state}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
