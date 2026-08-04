"""File-ingestion interfaces for RetailFlow Analytics."""

from retailflow.ingestion.api_client import RetailApiClient
from retailflow.ingestion.file_loader import load_file
from retailflow.ingestion.models import FileMetadata, LoadedDataset

__all__ = ["FileMetadata", "LoadedDataset", "RetailApiClient", "load_file"]
