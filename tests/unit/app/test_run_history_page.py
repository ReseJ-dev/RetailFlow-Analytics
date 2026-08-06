"""Rendering regressions for safe historical-run presentation."""

from __future__ import annotations

from app.pages import run_history
from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest

from .test_run_history_service import _record, _RepositoryStub


def test_missing_report_and_sensitive_metadata_render_safely(
    tmp_path,
    monkeypatch,
) -> None:
    record = _record(
        report_path=str(tmp_path / "deleted-report.xlsx"),
        report_filename="deleted-report.xlsx",
    )
    monkeypatch.setattr(
        run_history,
        "get_run_repository",
        lambda: _RepositoryStub((record,)),
    )
    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.session_state[StateKey.CURRENT_PAGE.value] = AppPage.RUN_HISTORY

    app = app.run()

    assert not app.exception
    assert app.title[0].value == "Run History"
    assert any(
        "Run metadata is available, but the generated file can no longer be found."
        in markdown.value
        for markdown in app.markdown
    )
    assert not any(button.label == "Download Excel Report" for button in app.get("download_button"))
    rendered = " ".join(
        str(element.value) for kind in ("markdown", "caption", "json") for element in app.get(kind)
    )
    assert "do-not-display" not in rendered
    assert "bearer-secret" not in rendered
    assert "/private/uploads" not in rendered
    assert "orders.csv" in rendered
