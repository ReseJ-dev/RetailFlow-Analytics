"""Streamlit report-settings form."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.services.report_service import LogoUpload, ReportRequest


def render_report_settings(
    defaults: ReportRequest,
    *,
    currency_options: tuple[str, ...],
) -> ReportRequest | None:
    """Render report controls and return a request only after form submission."""
    st.subheader("Report settings")
    st.caption("Choose the workbook identity, reporting period, and included sections.")
    currencies = tuple(dict.fromkeys((defaults.currency, *currency_options)))
    with st.form("generate_report_settings"):
        identity_left, identity_right = st.columns(2)
        with identity_left:
            report_name = st.text_input("Report Name", value=defaults.report_name)
            company_name = st.text_input("Company Name", value=defaults.company_name)
            prepared_by = st.text_input("Prepared By", value=defaults.prepared_by)
        with identity_right:
            report_title = st.text_input("Report Title", value=defaults.report_title)
            period = st.date_input(
                "Reporting Period",
                value=(defaults.period_start, defaults.period_end),
            )
            currency = st.selectbox(
                "Currency",
                currencies or (defaults.currency,),
                index=0,
            )

        st.markdown("#### Included sections")
        first, second, third = st.columns(3)
        with first:
            include_processed = st.checkbox(
                "Include Processed Data", value=defaults.include_processed_data
            )
            include_quality = st.checkbox(
                "Include Data Quality Report", value=defaults.include_data_quality_report
            )
        with second:
            include_inventory = st.checkbox(
                "Include Inventory Analysis", value=defaults.include_inventory_analysis
            )
            include_returns = st.checkbox(
                "Include Returns Analysis", value=defaults.include_returns_analysis
            )
        with third:
            include_recommendations = st.checkbox(
                "Include Management Recommendations",
                value=defaults.include_recommendations,
            )
            overwrite = st.checkbox(
                "Overwrite Existing Report", value=defaults.overwrite
            )

        logo_file = st.file_uploader(
            "Company Logo",
            type=("png", "jpg", "jpeg"),
            help="Optional PNG or JPEG, up to 5 MB.",
        )
        st.caption(f"Output directory: {defaults.output_directory}")
        submitted = st.form_submit_button("Generate Excel Report", type="primary")

    if not submitted:
        return None
    period_start, period_end = _normalise_period(period, defaults)
    logo = (
        LogoUpload(filename=logo_file.name, content=logo_file.getvalue())
        if logo_file is not None
        else defaults.logo
    )
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
        logo=logo,
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


__all__ = ["render_report_settings"]
