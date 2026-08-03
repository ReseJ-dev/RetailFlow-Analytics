"""Application-specific exceptions for RetailFlow Analytics."""


class RetailFlowError(Exception):
    """Base exception with separate user-facing and technical messages."""

    def __init__(self, message: str, technical_detail: str | None = None) -> None:
        """Create an error that is safe to display to an application user."""
        super().__init__(message)
        self.message = message
        self.technical_detail = technical_detail


class ConfigurationError(RetailFlowError):
    """Raised when application configuration cannot be loaded or validated."""


class DataSourceError(RetailFlowError):
    """Raised when a configured data source cannot be accessed."""


class EmptyFileError(DataSourceError):
    """Raised when an input file contains no usable data."""


class MissingColumnError(RetailFlowError):
    """Raised when an input dataset lacks one or more required columns."""


class DataValidationError(RetailFlowError):
    """Raised when input data does not meet validation requirements."""


class ReportGenerationError(RetailFlowError):
    """Raised when a management report cannot be generated."""
