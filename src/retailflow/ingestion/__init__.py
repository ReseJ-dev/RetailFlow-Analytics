"""File-ingestion interfaces for RetailFlow Analytics."""

from retailflow.ingestion.file_loader import load_file
from retailflow.ingestion.models import FileMetadata, LoadedDataset

__all__ = ["FileMetadata", "LoadedDataset", "load_file"]
