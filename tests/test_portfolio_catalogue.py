"""Portfolio advisor jobs/timestamps catalogue export."""

from __future__ import annotations

from pathlib import Path

from tradingagents.portfolio_advisor import catalogue, state


def test_build_catalogue_markdown_includes_jobs(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    st = state.default_state()
    st["first_scan_complete"] = True
    st["last_init_iso"] = "2026-05-01T12:00:00+00:00"
    st["jobs"] = [
        {
            "id": "j1",
            "ticker": "NVDA",
            "status": "pending",
            "scheduled_at": "2026-05-20T15:00:00+00:00",
            "created_at": "2026-05-01T10:00:00+00:00",
            "completed_at": None,
            "execution_tier": "full_graph",
            "job_type": "routine_monitoring",
            "reason": "test reason",
        }
    ]
    md = catalogue.build_catalogue_markdown(cfg, st)
    assert "NVDA" in md
    assert "pending" in md
    assert "last_init_iso" in md
    assert "j1" in md


def test_write_advisor_catalogue_default_paths(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    paths = catalogue.write_advisor_catalogue(cfg, write_json=True)
    md = Path(paths["markdown"])
    assert md.is_file()
    assert "Portfolio advisor" in md.read_text(encoding="utf-8")
    jp = Path(paths["json"])
    assert jp.is_file()
    assert "jobs" in jp.read_text(encoding="utf-8")
