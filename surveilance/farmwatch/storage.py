"""SQLite event log, time-series observations and JPEG snapshots."""
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  camera TEXT NOT NULL,
  module TEXT NOT NULL,
  level TEXT NOT NULL,
  kind TEXT NOT NULL,
  track_id INTEGER,
  message TEXT,
  snapshot TEXT,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  camera TEXT NOT NULL,
  module TEXT NOT NULL,
  key TEXT NOT NULL,
  value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS obs_key_ts ON observations(camera, key, ts);
"""


class Storage:
    def __init__(self, db_path: str = "data/events.sqlite", snapshot_dir: str = "data/snapshots"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        os.makedirs(snapshot_dir, exist_ok=True)
        self.db_path = db_path
        self.snapshot_dir = snapshot_dir
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def snapshot(self, camera: str, frame: np.ndarray, tag: str = "") -> str:
        name = "%s_%s_%s.jpg" % (camera, time.strftime("%Y%m%d-%H%M%S"), tag or "snap")
        path = os.path.join(self.snapshot_dir, name)
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path

    def event(self, camera: str, module: str, level: str, kind: str, message: str,
              track_id: Optional[int] = None, snapshot: Optional[str] = None,
              extra: Optional[Dict[str, Any]] = None, ts: Optional[float] = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events(ts,camera,module,level,kind,track_id,message,snapshot,extra) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts or time.time(), camera, module, level, kind, track_id, message, snapshot,
                 json.dumps(extra or {}, default=str)))
            self._conn.commit()
            return int(cur.lastrowid)

    def observe(self, camera: str, module: str, key: str, value: float,
                ts: Optional[float] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO observations(ts,camera,module,key,value) VALUES (?,?,?,?,?)",
                (ts or time.time(), camera, module, key, float(value)))
            self._conn.commit()

    def recent_events(self, limit: int = 100, camera: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM events"
        args: List[Any] = []
        if camera:
            q += " WHERE camera=?"
            args.append(camera)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def series(self, camera: str, key: str, since: float) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, value FROM observations WHERE camera=? AND key=? AND ts>=? ORDER BY ts",
                (camera, key, since))
            return [{"ts": r[0], "value": r[1]} for r in cur.fetchall()]

    def keys(self, camera: Optional[str] = None) -> List[Dict[str, str]]:
        with self._lock:
            if camera:
                cur = self._conn.execute(
                    "SELECT DISTINCT camera, key FROM observations WHERE camera=?", (camera,))
            else:
                cur = self._conn.execute("SELECT DISTINCT camera, key FROM observations")
            return [{"camera": r[0], "key": r[1]} for r in cur.fetchall()]
