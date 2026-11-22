#!/usr/bin/env python3
"""Reserve at most three task identities for the local Sonnet implementation pilot."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys

PILOT = "sonnet-medium-implementation-v1"
CAP = 3
DEFAULT = Path.home() / ".traycer" / "sonnet-medium-implementation-v1.sqlite3"


def connect(path):
    # mode=rw is intentional: another host must not silently create its own pilot.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=15, isolation_level=None)
    row = db.execute("SELECT pilot, host, cap FROM pilot WHERE id = 1").fetchone()
    if row != (PILOT, socket.gethostname(), CAP):
        db.close()
        raise RuntimeError("pilot state missing, incompatible, or belongs to another host")
    return db


def initialize(path):
    if not path.parent.is_dir():
        raise RuntimeError("pilot state parent directory is missing")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE pilot (id INTEGER PRIMARY KEY CHECK (id = 1), pilot TEXT NOT NULL, host TEXT NOT NULL, cap INTEGER NOT NULL, paused INTEGER NOT NULL DEFAULT 0, reason TEXT)")
        db.execute("CREATE TABLE slots (slot INTEGER PRIMARY KEY CHECK (slot BETWEEN 1 AND 3), task_key TEXT NOT NULL UNIQUE, reserved_at TEXT NOT NULL)")
        db.execute("INSERT INTO pilot (id, pilot, host, cap) VALUES (1, ?, ?, ?)", (PILOT, socket.gethostname(), CAP))
    return {"pilot": PILOT, "host": socket.gethostname(), "capacity": CAP, "reserved": 0}


def status(db):
    rows = db.execute("SELECT slot, task_key, reserved_at FROM slots ORDER BY slot").fetchall()
    paused, reason = db.execute("SELECT paused, reason FROM pilot WHERE id = 1").fetchone()
    return {"pilot": PILOT, "capacity": CAP, "reserved": len(rows), "paused": bool(paused), "reason": reason, "slots": [dict(zip(("slot", "task_key", "reserved_at"), row)) for row in rows]}


def reserve(db, task_key):
    # A stable canonical identity is required, not a branch name or user text.
    key = task_key.strip().lower()
    if not re.fullmatch(r"(?:linear:[a-z][a-z0-9_-]*-[0-9]+|task:[a-z0-9][a-z0-9._-]{2,127})", key):
        raise ValueError("use linear:ISSUE-ID or task:STABLE-TASK-ID")
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT paused FROM pilot WHERE id = 1").fetchone()[0]:
            raise RuntimeError("pilot is paused; use the existing implementation contract")
        existing = db.execute("SELECT slot FROM slots WHERE task_key = ?", (key,)).fetchone()
        if existing:
            db.commit()
            return {"pilot": PILOT, "task_key": key, "slot": existing[0], "existing": True}
        used = {row[0] for row in db.execute("SELECT slot FROM slots")}
        slot = next((i for i in range(1, CAP + 1) if i not in used), None)
        if slot is None:
            db.rollback()
            raise RuntimeError("pilot capacity exhausted; use the existing implementation contract")
        db.execute("INSERT INTO slots VALUES (?, ?, ?)", (slot, key, dt.datetime.now(dt.timezone.utc).isoformat()))
        db.commit()
        return {"pilot": PILOT, "task_key": key, "slot": slot, "existing": False}
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT, help="local pilot state (test override supported)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    pause = commands.add_parser("pause")
    pause.add_argument("--reason", required=True)
    p = commands.add_parser("reserve")
    p.add_argument("--task-key", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.db)
        else:
            with connect(args.db) as db:
                if args.command == "status":
                    result = status(db)
                elif args.command == "pause":
                    reason = args.reason.strip()
                    if not reason or len(reason) > 300:
                        raise ValueError("pause reason must contain 1 to 300 characters")
                    db.execute("UPDATE pilot SET paused = 1, reason = ? WHERE id = 1", (reason,))
                    result = status(db)
                else:
                    result = reserve(db, args.task_key)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
