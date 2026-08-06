# RetailFlow Analytics UI Guide

This document describes the implemented Streamlit interface. It complements the
business and operational documentation in the project `README.md`; it does not propose
new product behavior.

## Application shell and workflow

`app/main.py` is the single Streamlit entry point. It applies page configuration and
the shared local theme, initializes canonical session state, renders one branded
sidebar and dispatches the selected `AppPage`.

The primary workflow is:

```text
Overview
  → Upload Data
  → Data Quality
  → Dashboard
  → Generate Report
  → Run History
```

Settings is a secondary destination. Navigating between pages does not intentionally
clear uploaded sources or completed processing results. Workflow reset behavior remains
centralized in `app/state.py`.

## Page responsibilities

| Page | Presentation responsibility | Service/core boundary |
| --- | --- | --- |
| Overview | Workflow readiness, operational summary and valid next actions | Reads session summaries and report prerequisites |
| Upload Data | File/API source selection, source cards and readiness | Calls ingestion and API source services |
| Data Quality | Existing score, issue categories/details and review decisions | Calls the central processing service; does not duplicate validation rules |
| Dashboard | Shared filters, KPI cards, charts, tables and recommendations | Uses one `DashboardResult` calculated through analytics services |
| Generate Report | Report form, observable progress, result metadata and downloads | Calls the report service and existing workbook generator |
| Run History | Filters, newest-first metadata, safe details and downloads | Uses domain records from the run-history service/repository |
| Settings | Effective values, sources and validated session overrides | Uses typed Pydantic settings and existing session keys |

## Shared components

- `app/components/layout.py`: brand, sidebar and the only navigation menu.
- `app/components/ui.py`: page/section headings, metrics, semantic status and alert
  markup, empty states, workflow progress, information cards and action bars.
- `app/components/filter_bar.py`, `kpi_card.py`, `charts.py` and
  `recommendation_card.py`: Dashboard presentation using service-prepared data.
- `app/components/quality_summary.py`, `issue_group.py`, `issue_table.py` and
  `processing_progress.py`: validation presentation and source-row traceability.
- `app/components/report_settings.py`, `report_progress.py` and `report_result.py`:
  report configuration and result presentation.

Components contain no analytics or validation rules and do not own business session
state. Dynamic HTML used by semantic components is escaped before rendering.

## Theme and chart configuration

| Concern | Location |
| --- | --- |
| Typed colour, spacing and typography tokens | `app/styles/tokens.py` |
| One-time theme composition/injection | `app/styles/theme.py` |
| Global responsive and accessible component CSS | `app/styles.css` |
| Native Streamlit theme and chrome settings | `.streamlit/config.toml` |
| Shared Plotly colours, axes, hover, margins and mode bar | `app/styles/plotly_theme.py` |

The theme uses local system fonts and has no CDN dependency. Semantic states combine
text and symbols with colour. At narrower widths, dense column groups wrap; charts
stack when needed; tabs and wide tables retain controlled native scrolling.

## Session-state risks

- `StateKey.CURRENT_PAGE` is the only navigation authority.
- Uploaded sources, mappings, processing results, analytics and report results must
  continue using the keys defined in `app/state.py`.
- Presentation filters must not replace validation or processing results.
- Report generation must remain guarded against duplicate submissions caused by
  Streamlit reruns.
- API tokens must remain transient and must not enter session summaries, logs, YAML or
  run-history snapshots.
- Session Settings overrides are intentionally non-persistent and must not be described
  as saved configuration.

## Accessibility and responsive maintenance

Retain visible labels, textual status names, keyboard focus indicators and meaningful
empty states when changing components. Disabled workflow actions need an adjacent or
tooltip explanation. Chart titles and hover templates should use business language,
not raw internal column names.

Do not compress traceability tables until their fields become unreadable. Horizontal
scrolling is the expected narrow-window behavior for issue and run-history tables.
Responsive changes should use the existing tokens and stable Streamlit test IDs rather
than generated CSS class names.

The test suite includes Streamlit `AppTest` regressions for navigation, workflow
guards, rerun state, filtered analytics, empty results, report generation, historical
file handling, secret masking and dynamic-text escaping. It does not perform fragile
pixel comparisons.
