"""Tests for optional SMTP advisory email."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tradingagents.advisor import email_notify as en


def _smtp_cfg(**overrides):
    base = {
        "analysis_email_to": "you@example.com",
        "analysis_email_from": None,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "you@example.com",
        "smtp_password": "secret",
        "smtp_use_tls": True,
    }
    base.update(overrides)
    return base


def test_analysis_smtp_ready_requires_all_parts():
    assert not en.analysis_smtp_ready({})
    assert not en.analysis_smtp_ready(_smtp_cfg(smtp_host=""))
    assert not en.analysis_smtp_ready(_smtp_cfg(smtp_user=""))
    assert en.analysis_smtp_ready(_smtp_cfg())


@patch("tradingagents.advisor.email_notify.smtplib.SMTP")
def test_send_analysis_advisory_email(mock_smtp):
    server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = server
    ok = en.send_analysis_advisory_email(
        _smtp_cfg(),
        ticker="NVDA",
        trade_date="2026-05-01",
        decision_text="**Rating**: Hold\n",
        rating="Hold",
    )
    assert ok is True
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("you@example.com", "secret")
    server.send_message.assert_called_once()


def test_send_analysis_advisory_email_skips_when_not_configured():
    assert (
        en.send_analysis_advisory_email(
            {},
            ticker="NVDA",
            trade_date="2026-05-01",
            decision_text="x",
            rating="Hold",
        )
        is False
    )
