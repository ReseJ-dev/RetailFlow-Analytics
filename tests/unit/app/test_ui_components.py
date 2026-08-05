from pathlib import Path

import pytest
from app.components.ui import StatusVariant, callout, status_badge, workflow_progress
from streamlit.testing.v1 import AppTest


def test_status_variants_are_stable() -> None:
    assert tuple(StatusVariant) == (
        StatusVariant.NEUTRAL,
        StatusVariant.INFORMATION,
        StatusVariant.SUCCESS,
        StatusVariant.WARNING,
        StatusVariant.ERROR,
    )


@pytest.mark.parametrize("renderer", [status_badge, callout])
def test_html_components_escape_dynamic_values(monkeypatch, renderer) -> None:
    captured: list[tuple[str, bool]] = []

    def capture(markup: str, *, unsafe_allow_html: bool) -> None:
        captured.append((markup, unsafe_allow_html))

    monkeypatch.setattr("app.components.ui.st.markdown", capture)
    unsafe = '<script>alert("unsafe")</script>'

    if renderer is status_badge:
        renderer(unsafe, accessible_label=unsafe)
    else:
        renderer(unsafe, unsafe, accessible_label=unsafe)

    markup, allows_html = captured[0]
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert 'role="status"' in markup
    assert allows_html is True


@pytest.mark.parametrize(
    ("steps", "current_step", "message"),
    [
        ((), 1, "requires at least one step"),
        (("Upload",), 0, "must be within"),
        (("Upload",), 2, "must be within"),
    ],
)
def test_workflow_progress_rejects_invalid_stage(
    steps: tuple[str, ...], current_step: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        workflow_progress(steps, current_step)


def test_shared_component_preview_renders_without_errors() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "streamlit_components.py"
    app = AppTest.from_file(str(fixture), default_timeout=10).run()

    assert not app.exception
    assert app.title[0].value == "Component preview"
    assert any(metric.label == "Net Revenue" for metric in app.metric)
    assert any("1. Upload" in caption.value for caption in app.caption)
    assert any(button.label == "Continue" for button in app.button)
