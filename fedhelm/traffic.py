"""Bounded metadata for actual transport events, without secrets or message bodies."""
import json
import os
import sqlite3
import time
from pathlib import Path
from threading import Lock
from contextlib import closing
guard=Lock()
def record(source,target,kind,status='ok',bytes_count=0,event_id=''):
    path=Path(os.getenv('DATA_DIR','runtime/edge'))/'traffic.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    with guard,closing(sqlite3.connect(path,timeout=10)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS traffic(seq INTEGER PRIMARY KEY,time REAL,source TEXT,target TEXT,kind TEXT,status TEXT,bytes INTEGER,event_id TEXT)')
        con.execute('INSERT INTO traffic(time,source,target,kind,status,bytes,event_id) VALUES(?,?,?,?,?,?,?)',(time.time(),source,target,kind,status,bytes_count,event_id))
        con.execute('DELETE FROM traffic WHERE seq NOT IN (SELECT seq FROM traffic ORDER BY seq DESC LIMIT 2000)')
def recent(after=0):
    path=Path(os.getenv('DATA_DIR','runtime/edge'))/'traffic.sqlite'
    if not path.exists():return []
    with guard,closing(sqlite3.connect(path,timeout=10)) as con:
        con.row_factory=sqlite3.Row
        return [dict(r) for r in con.execute('SELECT * FROM traffic WHERE seq>? ORDER BY seq DESC LIMIT 100',(after,)).fetchall()]
