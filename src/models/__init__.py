"""
Models package - Data structures for the application.
"""
from .document import (
    FiscalDocument,
    DocumentType,
    ProcessingStatus,
    Entity,
    Address,
    TaxValues,
    ServiceItem
)
from .config import (
    Settings,
    CNPJMapper,
    EnvironmentSettings,
    FilialMapping
)
from .results import (
    ProcessingResult,
    ProcessingError,
    BatchProcessingResult,
    ProgressUpdate
)

__all__ = [
    # Document models
    "FiscalDocument",
    "DocumentType",
    "ProcessingStatus",
    "Entity",
    "Address",
    "TaxValues",
    "ServiceItem",
    # Configuration
    "Settings",
    "CNPJMapper",
    "EnvironmentSettings",
    "FilialMapping",
    # Results
    "ProcessingResult",
    "ProcessingError",
    "BatchProcessingResult",
    "ProgressUpdate",
]
