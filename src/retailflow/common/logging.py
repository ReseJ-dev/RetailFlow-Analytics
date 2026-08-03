"""Safe console and rotating-file logging configuration."""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from retailflow.common.exceptions import ConfigurationError

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?token|access[_ -]?token|authorization|password|secret)\b"
    r"\s*([:=])\s*([^\s,;]+)"
)
_ORDER_RECORD_PATTERN = re.compile(
    r"\{[^{}]*\b(?:order_id|order_number)\b[^{}]*\}", re.IGNORECASE
)


def _redact_sensitive_data(message: str) -> str:
    """Remove common personal data, credentials, and complete order mappings."""
    message = _ORDER_RECORD_PATTERN.sub("[REDACTED_ORDER_RECORD]", message)
    message = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", message)
    return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", message)


class SensitiveDataFilter(logging.Filter):
    """Redact sensitive values before a record reaches any configured handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the fully rendered log message and retain the record."""
        record.msg = _redact_sensitive_data(record.getMessage())
        record.args = ()
        return True


def configure_logging(
    level: int | str = logging.INFO,
    log_file: str | Path | None = None,
    *,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure and return the application logger.

    The logger always writes readable output to the console. When ``log_file``
    is supplied, it also writes to a size-limited rotating file. Messages are
    filtered for email addresses, common secret fields, and complete order
    mappings before being emitted.

    Raises:
        ConfigurationError: If a log file cannot be prepared.
    """
    logger = logging.getLogger("retailflow")
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(module)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sensitive_data_filter = SensitiveDataFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_data_filter)
    logger.addHandler(console_handler)

    if log_file is not None:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        except OSError as error:
            raise ConfigurationError(
                f"Could not configure the log file '{path}'.",
                technical_detail=str(error),
            ) from error
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_data_filter)
        logger.addHandler(file_handler)

    return logger
