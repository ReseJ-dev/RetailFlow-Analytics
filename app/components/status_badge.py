"""Backward-compatible application-status badge adapter."""

from app.components.ui import StatusVariant, status_badge
from app.state import ApplicationStatus

_STATUS_VARIANTS = {
    ApplicationStatus.READY: StatusVariant.SUCCESS,
    ApplicationStatus.WAITING_FOR_DATA: StatusVariant.NEUTRAL,
    ApplicationStatus.VALIDATING: StatusVariant.WARNING,
    ApplicationStatus.PROCESSING: StatusVariant.INFORMATION,
    ApplicationStatus.REPORT_GENERATED: StatusVariant.SUCCESS,
    ApplicationStatus.FAILED: StatusVariant.ERROR,
}


def render_status_badge(status: ApplicationStatus | str) -> None:
    """Render a restrained status label using only trusted application values."""
    try:
        resolved = ApplicationStatus(status)
    except ValueError:
        resolved = ApplicationStatus.FAILED
    status_badge(resolved.value, _STATUS_VARIANTS[resolved])
