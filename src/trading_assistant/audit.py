from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                create table if not exists audit_events (
                    id integer primary key autoincrement,
                    created_at text not null,
                    order_intent_id text,
                    event_type text not null,
                    payload_json text not null
                )
                """
            )

    def append(self, event_type: str, payload: Any, order_intent_id: str | None = None) -> None:
        if is_dataclass(payload):
            payload = asdict(payload)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                insert into audit_events (
                    created_at,
                    order_intent_id,
                    event_type,
                    payload_json
                ) values (?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    order_intent_id,
                    event_type,
                    json.dumps(payload, default=str, ensure_ascii=True),
                ),
            )

