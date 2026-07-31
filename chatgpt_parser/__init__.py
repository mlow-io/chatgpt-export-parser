"""Public package surface for ChatGPT export ingestion."""

from .api import (
    CONTRACT_VERSION,
    PACKAGE_VERSION,
    IngestError,
    IngestResult,
    InputInspection,
    ingest_exports,
    inspect_inputs,
    parser_contract,
)

__all__ = [
    "CONTRACT_VERSION",
    "PACKAGE_VERSION",
    "IngestError",
    "IngestResult",
    "InputInspection",
    "ingest_exports",
    "inspect_inputs",
    "parser_contract",
]
