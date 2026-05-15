"""Tests for advisor outbound message hygiene."""

from __future__ import annotations

from tradingagents.portfolio_advisor import messaging


def test_send_advisor_message_suppresses_near_duplicate(tmp_path):
    cfg = {
        "message_log_path": str(tmp_path / "messages.jsonl"),
        "portfolio_advisor_message_dedupe_minutes": 180,
    }

    messaging.send_advisor_message(cfg, "PM", "TEAM must exit today. Close 5 lots.")
    sent = messaging.send_advisor_message(cfg, "PM", "TEAM must exit today. Close 5 lots.")

    rows = messaging.load_recent_messages(cfg, limit=5)
    assert sent is False
    assert rows[0]["suppressed_duplicate"] is True
    assert rows[1]["suppressed_duplicate"] is False


def test_send_advisor_message_never_suppresses_correction(tmp_path):
    cfg = {
        "message_log_path": str(tmp_path / "messages.jsonl"),
        "portfolio_advisor_message_dedupe_minutes": 180,
    }

    messaging.send_advisor_message(cfg, "PM", "TEAM must exit today. Close 5 lots.")
    messaging.send_advisor_message(cfg, "PM", "Correction: TEAM date was wrong.")

    rows = messaging.load_recent_messages(cfg, limit=5)
    assert rows[0]["suppressed_duplicate"] is False
    assert rows[0]["body"].startswith("Correction:")
