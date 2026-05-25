"""
observability.py
───────────────────────────────────────────────────────────────
Structured logging and tracing for the trading research pipeline.

Every pipeline run gets a unique trace_id. Each node logs its
start time, duration, inputs summary and outputs summary to:
  data/logs/run_<date>_<trace_id[:8]>.jsonl   (one JSON line per event)
  data/logs/latest.jsonl                        (always overwritten — last run)

Log event structure:
  {
    "trace_id":   "uuid4",
    "run_id":     "uuid4",
    "timestamp":  "ISO8601",
    "node":       "research_candidates",
    "level":      "INFO" | "WARNING" | "ERROR",
    "duration_ms": 1234,
    "message":    "string",
    "data":       {}   # node-specific summary
  }

Usage:
  from observability import Tracer
  tracer = Tracer(run_id="abc")

  with tracer.span("research_candidates") as span:
      # do work
      span.set_data({"candidates": 4, "items_produced": 4})

  tracer.flush()   # write to disk
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Span — represents one node execution
# ─────────────────────────────────────────────────────────────────────────────

class Span:
    def __init__(self, trace_id: str, run_id: str, node: str):
        self.trace_id = trace_id
        self.run_id = run_id
        self.node = node
        self.level = "INFO"
        self.message = ""
        self.data: Dict[str, Any] = {}
        self._start = time.monotonic()
        self._start_ts = datetime.now(timezone.utc).isoformat()

    def set_data(self, data: Dict[str, Any]) -> None:
        self.data.update(data)

    def warn(self, message: str) -> None:
        self.level = "WARNING"
        self.message = message

    def error(self, message: str) -> None:
        self.level = "ERROR"
        self.message = message

    def to_dict(self) -> Dict:
        duration_ms = int((time.monotonic() - self._start) * 1000)
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "timestamp": self._start_ts,
            "node": self.node,
            "level": self.level,
            "duration_ms": duration_ms,
            "message": self.message,
            "data": self.data,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tracer — one per pipeline run
# ─────────────────────────────────────────────────────────────────────────────

class Tracer:
    """
    Collects structured log events for one pipeline run.

    Usage:
        tracer = Tracer(run_id=state.run_id)
        with tracer.span("autonomous_scan") as span:
            result = do_scan()
            span.set_data({"candidates": len(result)})
        tracer.flush()
    """

    def __init__(self, run_id: Optional[str] = None):
        self.trace_id = str(uuid.uuid4())
        self.run_id = run_id or self.trace_id
        self._events: List[Dict] = []
        self._log_dir = Path("data/logs")

        # Log start of run
        self._events.append({
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": "pipeline_start",
            "level": "INFO",
            "duration_ms": 0,
            "message": "Pipeline run started",
            "data": {"run_id": self.run_id},
        })

    @contextmanager
    def span(self, node: str):
        """Context manager that times a node and records its output."""
        s = Span(self.trace_id, self.run_id, node)
        try:
            yield s
        except Exception as exc:
            s.error(str(exc))
            raise
        finally:
            self._events.append(s.to_dict())

    def log(
        self,
        node: str,
        message: str,
        level: str = "INFO",
        data: Optional[Dict] = None,
    ) -> None:
        """Add a one-off log event without timing."""
        self._events.append({
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": node,
            "level": level,
            "duration_ms": 0,
            "message": message,
            "data": data or {},
        })

    def flush(self, final_summary: Optional[Dict] = None) -> Path:
        """
        Writes all events to disk as JSONL.
        Returns the path of the log file written.
        """
        if final_summary:
            self._events.append({
                "trace_id": self.trace_id,
                "run_id": self.run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": "pipeline_end",
                "level": "INFO",
                "duration_ms": 0,
                "message": "Pipeline run complete",
                "data": final_summary,
            })

        self._log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self._log_dir / f"run_{date_str}_{self.trace_id[:8]}.jsonl"
        latest_file = self._log_dir / "latest.jsonl"

        lines = [json.dumps(e, ensure_ascii=False) for e in self._events]
        content = "\n".join(lines) + "\n"

        log_file.write_text(content, encoding="utf-8")
        latest_file.write_text(content, encoding="utf-8")

        return log_file

    def summary(self) -> Dict:
        """Returns a summary of the trace for embedding in reports."""
        errors = [e for e in self._events if e["level"] == "ERROR"]
        warnings = [e for e in self._events if e["level"] == "WARNING"]
        nodes = [e["node"] for e in self._events
                 if e["node"] not in ("pipeline_start", "pipeline_end")]
        total_ms = sum(e.get("duration_ms", 0) for e in self._events)

        return {
            "trace_id": self.trace_id,
            "nodes_executed": nodes,
            "total_duration_ms": total_ms,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": [e["message"] for e in errors],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Global tracer accessor — lazy singleton per run
# ─────────────────────────────────────────────────────────────────────────────

_current_tracer: Optional[Tracer] = None


def get_tracer(run_id: Optional[str] = None) -> Tracer:
    """
    Returns the current tracer. Creates a new one if none exists.
    Call init_tracer() at the start of each run to reset.
    """
    global _current_tracer
    if _current_tracer is None:
        _current_tracer = Tracer(run_id=run_id)
    return _current_tracer


def init_tracer(run_id: Optional[str] = None) -> Tracer:
    """Creates and registers a fresh tracer for a new pipeline run."""
    global _current_tracer
    _current_tracer = Tracer(run_id=run_id)
    return _current_tracer


# ─────────────────────────────────────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tracer = init_tracer(run_id="test-run-0001")

    with tracer.span("autonomous_scan") as span:
        time.sleep(0.05)
        span.set_data({"candidates": 4, "provider": "ctrader"})

    with tracer.span("research_candidates") as span:
        time.sleep(0.08)
        span.set_data({"items_produced": 4, "llm": "mistral/mistral-small-latest"})

    with tracer.span("generate_opportunities") as span:
        time.sleep(0.06)
        span.set_data({"opportunities": 4, "llm": "mistral-fallback-nano"})

    tracer.log("risk_quality_filter", "Rejected 1 opportunity", level="WARNING",
               data={"rejected": ["EURUSD"], "reason": "Sem direção clara"})

    log_file = tracer.flush(final_summary={"opportunities_count": 3, "top": "XAUUSD"})
    print(f"Log written to: {log_file}")
    print(f"Summary: {json.dumps(tracer.summary(), indent=2)}")
