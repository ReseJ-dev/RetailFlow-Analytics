"""Tests for safe application logging."""

import logging
from pathlib import Path

from retailflow.common.logging import configure_logging


def test_file_logging_redacts_sensitive_values(tmp_path: Path) -> None:
    """File logs should not contain personal data, tokens, or complete orders."""
    log_path = tmp_path / "retailflow.log"
    logger = configure_logging(log_file=log_path)

    logger.info("Customer jane@example.com used api_token=unsafe-token")
    logger.info("Order: {'order_id': 'O-1', 'total': 25, 'customer': 'Jane'}")
    for handler in logger.handlers:
        handler.flush()

    log_contents = log_path.read_text(encoding="utf-8")
    assert "jane@example.com" not in log_contents
    assert "unsafe-token" not in log_contents
    assert "O-1" not in log_contents
    assert "[REDACTED_EMAIL]" in log_contents
    assert "[REDACTED_ORDER_RECORD]" in log_contents


def test_file_logging_uses_rotating_handler(tmp_path: Path) -> None:
    """Configured file logging should use size-based rotation."""
    logger = configure_logging(log_file=tmp_path / "retailflow.log")

    handler_names = {type(handler).__name__ for handler in logger.handlers}

    assert "StreamHandler" in handler_names
    assert "RotatingFileHandler" in handler_names
    assert logger.level == logging.INFO
