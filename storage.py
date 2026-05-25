from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import resolve_project_path
from schemas import TradingResearchState


def init_db(sqlite_path: str) -> Path:
    db_path = resolve_project_path(sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                scan_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        conn.commit()

    return db_path


def save_run(state: TradingResearchState) -> None:
    sqlite_path = state.config.get("storage", {}).get("sqlite_path", "data/runs.db")
    try:
        db_path = init_db(sqlite_path)
    except (sqlite3.OperationalError, OSError) as exc:
        import sys
        print(f"[storage] WARNING: cannot initialise DB ({exc}) — run not persisted.", file=sys.stderr)
        return

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, created_at, scan_date, mode, report_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    state.run_id,
                    datetime.now(timezone.utc).isoformat(),
                    state.scan_date,
                    state.final_report.get("mode", "unknown"),
                    json.dumps(state.final_report, ensure_ascii=False, indent=2),
                ),
            )
            conn.commit()
    except (sqlite3.OperationalError, OSError) as exc:
        import sys
        print(f"[storage] WARNING: run not saved to DB: {exc}", file=sys.stderr)

