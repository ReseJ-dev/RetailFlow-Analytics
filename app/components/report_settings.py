"""Structured Streamlit form for management-report configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import streamlit as st

from app.components.ui import StatusVariant, section_header, status_badge
from app.services.report_service import (
    LogoUpload,
    ReportRequest,
    ReportServiceError,
    validate_logo_upload,
)


@dataclass(frozen=True, slots=True)
class ReportInputSummary:
    """Non-sensitive source counts displayed before report generation."""

    processed_rows: int
    product_rows: int
    inventory_rows: int
    return_rows: int
    excluded_rows: int
    warning_count: int


def _safe_output_location(path: Path) -> str:
    """Return a useful output label without exposing absolute parent directories."""
    if not path.is_absolute():
        return str(path)
    return f"Configured application directory ({path.name or 'output'})"


def _filename_preview(report_name: str) -> str:
    name = report_name.strip() or "report"
    return name if name.casefold().endswith(".xlsx") else f"{name}.xlsx"


def _uploaded_logo(uploaded_file: object) -> LogoUpload | None:
    filename = getattr(uploaded_file, "name", None)
    getvalue = getattr(uploaded_file, "getvalue", None)
    if not isinstance(filename, str) or not callable(getvalue):
        return None
    content = getvalue()
    return LogoUpload(filename, content) if isinstance(content, bytes) else None


def _render_logo_feedback(logo: LogoUpload | None) -> bool:
    if logo is None:
        st.caption("No logo selected. The workbook will use text-based branding.")
        return True
    st.caption(f"Selected file: {logo.filename}")
    try:
        validate_logo_upload(logo)
    except ReportServiceError as error:
        st.error(error.message)
        return False
    st.success("Logo format and file size are valid.")
    return True


def _optional_sections(
    *,
    inventory: bool,
    returns: bool,
    quality: bool,
    processed: bool,
) -> tuple[str, ...]:
    values = (
        ("Inventory", inventory),
        ("Returns", returns),
        ("Data Quality", quality),
        ("Processed Data", processed),
    )
    return tuple(label for label, included in values if included)


def _render_generation_summary(
    summary: ReportInputSummary,
    *,
    period_start: date,
    period_end: date,
    currency: str,
    optional_sections: tuple[str, ...],
) -> None:
    section_header(
        "Generation Summary",
        "Confirm the reporting scope before creating the workbook.",
    )
    st.caption(
        f"Period: {period_start:%d %b %Y}–{period_end:%d %b %Y} · "
        f"Currency: {currency} · Optional sections: "
        f"{', '.join(optional_sections) if optional_sections else 'None'}"
    )
    metrics = (
        ("Processed order rows", summary.processed_rows),
        ("Product rows", summary.product_rows),
        ("Inventory rows", summary.inventory_rows),
        ("Return rows", summary.return_rows),
        ("Excluded rows", summary.excluded_rows),
        ("Warnings", summary.warning_count),
    )
    for start in range(0, len(metrics), 3):
        columns = st.columns(3)
        for column, (label, value) in zip(columns, metrics[start : start + 3], strict=True):
            column.metric(label, f"{value:,}")


def render_report_settings(
    defaults: ReportRequest,
    *,
    currency_options: tuple[str, ...],
    source_summary: ReportInputSummary | None = None,
    generation_in_progress: bool = False,
) -> ReportRequest | None:
    """Render the report form and return a request only after one valid submission."""
    currencies = tuple(dict.fromkeys((defaults.currency, *currency_options)))
    summary = source_summary or ReportInputSummary(0, 0, 0, 0, 0, 0)
    with st.container(border=True):
        section_header(
            "Report Identity",
            "Define how the workbook identifies the organisation and reporting period.",
        )
        identity_left, identity_right = st.columns(2)
        with identity_left:
            company_name = st.text_input("Company Name", value=defaults.company_name)
            report_title = st.text_input("Report Title", value=defaults.report_title)
            prepared_by = st.text_input("Prepared By", value=defaults.prepared_by)
        with identity_right:
            period = st.date_input(
                "Reporting Period",
                value=(defaults.period_start, defaults.period_end),
            )
            currency = st.selectbox("Currency", currencies or (defaults.currency,), index=0)

        st.divider()
        section_header(
            "Branding",
            "Optionally add a validated PNG or JPEG logo up to 5 MB.",
        )
        logo_file = st.file_uploader(
            "Company Logo",
            type=("png", "jpg", "jpeg"),
            help="The image is used only while generating the workbook.",
        )
        uploaded_logo = _uploaded_logo(logo_file) if logo_file is not None else None
        remove_logo = False
        if defaults.logo is not None and uploaded_logo is None:
            st.caption("Upload another image to replace the current logo.")
            remove_logo = st.checkbox(
                "Remove current logo",
                value=False,
                help="Leave unchecked to keep the previously selected logo.",
            )
        selected_logo = None if remove_logo else (uploaded_logo or defaults.logo)
        logo_valid = _render_logo_feedback(selected_logo)

        st.divider()
        section_header(
            "Included Sections",
            "Core management worksheets are always included; optional worksheets can be removed.",
        )
        st.caption(
            "Always included: Cover · Executive Summary · Sales Analysis · "
            "Product Performance · Report Metadata"
        )
        status_badge("5 core worksheets always included", StatusVariant.INFORMATION)
        section_columns = st.columns(4)
        include_inventory = section_columns[0].checkbox(
            "Inventory", value=defaults.include_inventory_analysis
        )
        include_returns = section_columns[1].checkbox(
            "Returns", value=defaults.include_returns_analysis
        )
        include_quality = section_columns[2].checkbox(
            "Data Quality", value=defaults.include_data_quality_report
        )
        include_processed = section_columns[3].checkbox(
            "Processed Data", value=defaults.include_processed_data
        )
        include_recommendations = st.checkbox(
            "Include Management Recommendations",
            value=defaults.include_recommendations,
            help="Recommendations appear within supported management worksheets.",
        )

        st.divider()
        section_header(
            "Output Configuration",
            "Choose the workbook filename and explicit overwrite behaviour.",
        )
        output_left, output_right = st.columns(2)
        report_name = output_left.text_input("Output Filename", value=defaults.report_name)
        overwrite = output_right.checkbox(
            "Overwrite Existing Report",
            value=defaults.overwrite,
            help="When disabled, an existing file with the same name is preserved.",
        )
        st.caption(f"Filename preview: {_filename_preview(report_name)}")
        st.caption(f"Output location: {_safe_output_location(defaults.output_directory)}")
        if overwrite:
            st.warning("An existing report with this filename may be replaced.")
        else:
            st.info("Existing reports are protected. Choose another filename if one exists.")

        period_start, period_end = _normalise_period(period, defaults)
        optional_sections = _optional_sections(
            inventory=include_inventory,
            returns=include_returns,
            quality=include_quality,
            processed=include_processed,
        )
        st.divider()
        _render_generation_summary(
            summary,
            period_start=period_start,
            period_end=period_end,
            currency=str(currency),
            optional_sections=optional_sections,
        )
        submitted = st.button(
            "Generate Excel Report",
            key="generate_report_submit",
            type="primary",
            disabled=generation_in_progress or not logo_valid,
            width="stretch",
        )
        if generation_in_progress:
            st.caption(
                "Report generation is already in progress. Duplicate submission is disabled."
            )

    if not submitted or not logo_valid:
        return None
    return ReportRequest(
        report_name=report_name,
        period_start=period_start,
        period_end=period_end,
        currency=str(currency),
        include_processed_data=include_processed,
        include_data_quality_report=include_quality,
        include_inventory_analysis=include_inventory,
        include_returns_analysis=include_returns,
        include_recommendations=include_recommendations,
        company_name=company_name,
        report_title=report_title,
        prepared_by=prepared_by,
        output_directory=defaults.output_directory,
        logo=selected_logo,
        overwrite=overwrite,
    )


def _normalise_period(value: object, defaults: ReportRequest) -> tuple[date, date]:
    if isinstance(value, date):
        return value, value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        start, end = value
        if isinstance(start, date) and isinstance(end, date):
            return start, end
    return defaults.period_start, defaults.period_end


__all__ = ["ReportInputSummary", "render_report_settings"]
