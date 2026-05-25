"""
slack_notify.py
───────────────────────────────────────────────────────────────
Slack Human-in-the-Loop notifications for the trading research pipeline.

Sends a formatted message to Slack for each ranked opportunity,
with Approve/Reject context so the human reviewer can act quickly.

Setup:
  1. Create a Slack Incoming Webhook:
     https://api.slack.com/messaging/webhooks
  2. Add to .env:
     SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
     SLACK_CHANNEL=#trading-research   (optional, overrides webhook default)

Usage:
  from slack_notify import notify_opportunities, notify_run_summary
  notify_opportunities(ranked_opportunities, run_id)
  notify_run_summary(state)

IMUTÁVEL: execution_enabled: false — notifications are read-only alerts.
No orders are placed. Human approval is informational only.
"""
from __future__ import annotations

import os
import sys
import json
from typing import List, Dict, Any, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def notify_opportunities(
    ranked_opportunities: List[Dict],
    run_id: str,
    max_to_send: int = 3,
) -> bool:
    """
    Sends one Slack message per top opportunity (up to max_to_send).
    Returns True if at least one message was sent successfully.
    """
    if not is_available():
        return False

    sent = False
    for item in ranked_opportunities[:max_to_send]:
        opp = item.get("opportunity", {})
        score = item.get("score", 0)
        rank = item.get("rank", "?")
        why = item.get("why", "")
        decision = item.get("decision", "watch_for_entry")

        msg = _build_opportunity_message(opp, score, rank, why, decision, run_id)
        ok = _send(msg)
        if ok:
            sent = True

    return sent


def notify_run_summary(state_dict: Dict, run_id: str) -> bool:
    """
    Sends a single summary message for the full pipeline run.
    """
    if not is_available():
        return False

    summary = state_dict.get("summary", {})
    top = state_dict.get("top_opportunity", "—")
    n_opps = state_dict.get("opportunities_count", 0)
    rejected = len(state_dict.get("rejected", []))
    errors = state_dict.get("errors", [])
    scan_date = state_dict.get("scan_date", datetime.utcnow().strftime("%Y-%m-%d"))

    error_block = ""
    if errors:
        error_block = f"\n⚠️ *Errors:* {len(errors)} — `{errors[0]}`"

    text = (
        f"*🔍 Trading Research Run Complete*\n"
        f"Run ID: `{run_id[:8]}`  |  Date: `{scan_date}`\n"
        f"Candidates scanned: *{summary.get('raw_candidates', 0)}* → "
        f"Opportunities: *{n_opps}* → "
        f"Rejected: *{rejected}*\n"
        f"Top pick: *{top}*"
        f"{error_block}"
    )

    return _send({"text": text})


def is_available() -> bool:
    """Returns True if SLACK_WEBHOOK_URL is configured."""
    return bool(os.environ.get("SLACK_WEBHOOK_URL", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Message builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_opportunity_message(
    opp: Dict,
    score: float,
    rank: int,
    why: str,
    decision: str,
    run_id: str,
) -> Dict:
    """Builds a rich Slack Block Kit message for one opportunity."""

    asset = opp.get("asset", "?")
    direction = opp.get("direction", "?").upper()
    setup_type = opp.get("setup_type", "?")
    confidence = opp.get("confidence_initial", 0)
    thesis = opp.get("thesis", "")[:280]
    catalyst = opp.get("catalyst", "")[:120]
    entry = opp.get("entry_logic", "")[:120]
    stop = opp.get("stop_logic", "")[:120]
    target = opp.get("target_logic", "")[:120]
    metrics = opp.get("metrics", {})

    direction_emoji = "📈" if direction == "LONG" else "📉" if direction == "SHORT" else "➡️"
    score_bar = "█" * int(score / 2) + "░" * (5 - int(score / 2))

    # Metrics line
    metrics_line = ""
    if metrics.get("move_pct"):
        metrics_line = (
            f"Move: `{metrics['move_pct']:.2f}%` | "
            f"Range: `{metrics.get('range_pct', 0):.2f}%` | "
            f"Period: `{metrics.get('period', '?')}`"
        )

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"#{rank} {direction_emoji} {asset} — {direction} | Score: {score:.1f} {score_bar}",
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Setup:*\n{setup_type}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                {"type": "mrkdwn", "text": f"*Decision:*\n`{decision}`"},
                {"type": "mrkdwn", "text": f"*Run ID:*\n`{run_id[:8]}`"},
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Thesis:*\n{thesis}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Catalyst:*\n{catalyst}"},
                {"type": "mrkdwn", "text": f"*Why ranked:*\n{why}"},
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Entry:*\n{entry}"},
                {"type": "mrkdwn", "text": f"*Stop:*\n{stop}"},
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Target:*\n{target}"}
        },
    ]

    if metrics_line:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Scanner metrics:*\n{metrics_line}"}
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"⚠️ *Research only — no orders placed.* "
                    f"requires_human_approval: true | execution_enabled: false"
                )
            }
        ]
    })

    return {"blocks": blocks}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP sender
# ─────────────────────────────────────────────────────────────────────────────

def _send(payload: Dict) -> bool:
    """
    Posts a payload to the Slack Incoming Webhook.
    Returns True on success, False on any error.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return False

    try:
        import requests
        resp = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200 and resp.text == "ok":
            return True
        print(
            f"[slack_notify] WARNING: Slack returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        return False
    except Exception as exc:
        print(f"[slack_notify] WARNING: Failed to send: {exc}", file=sys.stderr)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print(f"Slack available: {is_available()}")

    # Send a test message
    test_opp = {
        "asset": "XAUUSD",
        "direction": "long",
        "setup_type": "momentum_breakout",
        "thesis": "Gold showing strong upside momentum driven by safe-haven demand and USD weakness.",
        "catalyst": "Fed rate cut expectations + geopolitical risk",
        "entry_logic": "Break above 2350 with H1 close confirmation",
        "stop_logic": "Below 2320 swing low",
        "target_logic": "2400 — 2.0R target",
        "confidence_initial": 0.85,
        "metrics": {"move_pct": 1.43, "range_pct": 1.96, "period": "H1"},
    }
    ok = notify_opportunities(
        [{"opportunity": test_opp, "score": 10.9, "rank": 1,
          "why": "Forte movimento (1.43%)", "decision": "watch_for_entry"}],
        run_id="test-run-0001",
    )
    print(f"Message sent: {ok}")
