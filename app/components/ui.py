"""Reusable, business-agnostic Streamlit presentation primitives."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import Literal

import streamlit as st
from streamlit.delta_generator import DeltaGenerator


class StatusVariant(StrEnum):
    """Supported semantic presentation variants."""

    NEUTRAL = "neutral"
    INFORMATION = "information"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


type ButtonType = Literal["primary", "secondary", "tertiary"]
type DeltaColour = Literal["normal", "inverse", "off"]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Presentation settings for one action-bar button."""

    key: str
    label: str
    button_type: ButtonType = "secondary"
    icon: str | None = None
    help_text: str | None = None
    disabled: bool = False


def _safe_text(value: object) -> str:
    return escape(str(value), quote=True)


def _semantic_markup(
    *,
    css_base: Literal["status", "alert"],
    variant: StatusVariant,
    text: str,
    accessible_label: str,
    title: str | None = None,
) -> str:
    title_markup = f'<span class="rf-semantic-title">{_safe_text(title)}</span>' if title else ""
    return (
        f'<div class="rf-{css_base} rf-{css_base}--{variant.value}" '
        f'role="status" aria-label="{_safe_text(accessible_label)}">'
        '<span class="rf-semantic-copy">'
        f"{title_markup}"
        f'<span class="rf-semantic-message">{_safe_text(text)}</span>'
        "</span>"
        "</div>"
    )


def page_header(
    title: str,
    description: str | None = None,
    *,
    breadcrumb: str | None = "RetailFlow",
    context: Sequence[str] = (),
) -> None:
    """Render a compact page title with optional breadcrumb and context."""
    if breadcrumb:
        st.caption(f"{breadcrumb} / {title}")
    st.title(title)
    if description:
        st.write(description)
    if context:
        st.caption("  ·  ".join(str(item) for item in context if item))


def section_header(
    title: str,
    description: str | None = None,
    *,
    label: str | None = None,
) -> None:
    """Render a consistent section heading and supporting copy."""
    if label:
        st.caption(label)
    st.subheader(title)
    if description:
        st.caption(description)


def metric_card(
    label: str,
    value: str | int | float,
    *,
    delta: str | int | float | None = None,
    help_text: str | None = None,
    delta_colour: DeltaColour = "normal",
) -> None:
    """Render a themed metric with accessible label and optional comparison."""
    st.metric(
        label=label,
        value=value,
        delta=delta,
        delta_color=delta_colour,
        help=help_text,
        border=True,
    )


def status_badge(
    text: str,
    variant: StatusVariant = StatusVariant.NEUTRAL,
    *,
    accessible_label: str | None = None,
) -> None:
    """Render a textual semantic status badge using escaped dynamic content."""
    markup = _semantic_markup(
        css_base="status",
        variant=variant,
        text=text,
        accessible_label=accessible_label or f"Status: {text}",
    )
    st.markdown(markup, unsafe_allow_html=True)


def callout(
    title: str,
    message: str,
    variant: StatusVariant = StatusVariant.INFORMATION,
    *,
    accessible_label: str | None = None,
) -> None:
    """Render an accessible semantic message with safely escaped copy."""
    markup = _semantic_markup(
        css_base="alert",
        variant=variant,
        title=title,
        text=message,
        accessible_label=accessible_label or f"{variant.value.title()}: {title}",
    )
    st.markdown(markup, unsafe_allow_html=True)


def empty_state(
    title: str,
    explanation: str,
    *,
    action_label: str | None = None,
    icon: str | None = None,
    compact: bool = False,
    key: str | None = None,
) -> bool:
    """Render an empty state and return whether its optional action was selected."""
    with st.container():
        if icon:
            st.text(icon)
        if compact:
            st.markdown(f"**{title}**")
            st.write(explanation)
        else:
            st.subheader(title)
            st.info(explanation)
        if action_label:
            return st.button(action_label, key=key, type="primary")
    return False


def workflow_progress(
    steps: Sequence[str],
    current_step: int,
    *,
    accessible_label: str = "Workflow progress",
) -> None:
    """Render one-based workflow progress with a visible current-step label."""
    if not steps:
        raise ValueError("Workflow progress requires at least one step.")
    if not 1 <= current_step <= len(steps):
        raise ValueError("Current workflow step must be within the supplied steps.")
    current_label = steps[current_step - 1]
    st.progress(
        current_step / len(steps),
        text=(f"{accessible_label}: step {current_step} of {len(steps)} — {current_label}"),
    )
    st.caption("  ·  ".join(f"{index}. {step}" for index, step in enumerate(steps, 1)))


def information_card(
    title: str,
    body: str,
    *,
    label: str | None = None,
    icon: str | None = None,
) -> None:
    """Render a bordered card for concise supporting information."""
    with st.container(border=True):
        if icon:
            st.text(icon)
        if label:
            st.caption(label)
        st.markdown(f"**{title}**")
        st.write(body)


@contextmanager
def chart_container(
    title: str,
    description: str | None = None,
    *,
    accessible_label: str | None = None,
) -> Iterator[DeltaGenerator]:
    """Provide a titled surface in which callers render a chart or empty state."""
    container = st.container(border=True)
    with container:
        section_header(title, description, label=accessible_label)
        yield container


def action_bar(
    actions: Sequence[ActionSpec],
    *,
    accessible_label: str = "Available actions",
) -> str | None:
    """Render stateless actions and return the selected action key, if any."""
    if not actions:
        return None
    st.caption(accessible_label)
    columns = st.columns(len(actions))
    selected: str | None = None
    for column, action in zip(columns, actions, strict=True):
        if column.button(
            action.label,
            key=action.key,
            type=action.button_type,
            icon=action.icon,
            help=action.help_text,
            disabled=action.disabled,
            width="stretch",
        ):
            selected = action.key
    return selected


def data_source_status(
    source_name: str,
    status_text: str,
    *,
    variant: StatusVariant = StatusVariant.NEUTRAL,
    detail: str | None = None,
    row_count: int | None = None,
) -> None:
    """Render a source name, textual status, and optional non-sensitive summary."""
    with st.container(border=True):
        st.markdown(f"**{source_name}**")
        status_badge(
            status_text,
            variant,
            accessible_label=f"{source_name} source status: {status_text}",
        )
        if detail:
            st.caption(detail)
        if row_count is not None:
            st.caption(f"Rows: {row_count:,}")


def issue_summary_card(
    category: str,
    affected_rows: int,
    highest_severity: StatusVariant,
    explanation: str,
    recommended_action: str,
) -> None:
    """Render an issue category summary without exposing full source records."""
    with st.container(border=True):
        st.markdown(f"**{category}**")
        status_badge(
            f"{highest_severity.value.title()} · {affected_rows:,} affected rows",
            highest_severity,
            accessible_label=(
                f"{category}: {highest_severity.value}, {affected_rows} affected rows"
            ),
        )
        st.write(explanation)
        st.caption(f"Recommended action: {recommended_action}")


__all__ = [
    "ActionSpec",
    "StatusVariant",
    "action_bar",
    "callout",
    "chart_container",
    "data_source_status",
    "empty_state",
    "information_card",
    "issue_summary_card",
    "metric_card",
    "page_header",
    "section_header",
    "status_badge",
    "workflow_progress",
]
