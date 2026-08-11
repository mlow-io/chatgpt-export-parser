"""Stable library API for canonical ChatGPT archive ingestion.

The CLI and native clients share this contract. Callers should import from this
module instead of reaching into ``chatgpt_parser.cli`` or database internals.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .cli.commands import _discover_input_sources, run_canonical_ingest
from .db.canonical_schema import CANONICAL_SCHEMA_VERSION


PACKAGE_VERSION = "0.3.0"
CONTRACT_VERSION = 1


class IngestError(RuntimeError):
    """Raised when no usable source was found or every discovered source failed."""

    def __init__(self, result: "IngestResult") -> None:
        self.result = result
        diagnostics = result.diagnostics or []
        failed_source = next(
            (row for row in result.source_results if row.get("status") == "failed"),
            None,
        )
        reason = diagnostics[0].get("reason") if diagnostics else None
        if not reason and failed_source:
            reason = f"Failed to ingest {failed_source.get('label') or 'a selected source'}."
        super().__init__(reason or "ChatGPT export ingestion failed.")


@dataclass(frozen=True)
class InputInspection:
    """Discovery result for JSON files, export folders, ZIPs, and diagnostics."""

    sources: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @property
    def can_ingest(self) -> bool:
        return bool(self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_ingest": self.can_ingest,
            "sources": self.sources,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class IngestResult:
    """Serializable result returned by :func:`ingest_exports`."""

    run_id: str
    database: str
    stats: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    skipped: bool = False
    failed: bool = False
    partial: bool = False
    source_errors: int = 0
    conversation_errors: int = 0
    source_results: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    trace_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parser_contract() -> dict[str, Any]:
    """Return the versioned capabilities consumed by native clients."""

    return {
        "contract_version": CONTRACT_VERSION,
        "package_version": PACKAGE_VERSION,
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "python_requires": ">=3.10",
        "input_kinds": ["json_file", "export_folder", "zip_file"],
        "diagnostic_input_kinds": ["chat_html"],
        "ingest_semantics": {
            "atomic": True,
            "rejects_partial_runs": True,
            "structured_source_results": True,
        },
        "operations": [
            "inspect_inputs",
            "ingest_exports",
            "query",
            "search",
            "export_conversation",
            "export_conversations",
            "export_bundle",
            "check",
            "list_runs",
            "dump_db",
            "restore_db",
        ],
    }


def inspect_inputs(inputs: Iterable[str | Path]) -> InputInspection:
    """Discover canonical sources without creating or changing a database."""

    paths = [str(Path(item).expanduser().resolve()) for item in inputs]
    sources, diagnostics = _discover_input_sources(paths, include_diagnostics=True)
    return InputInspection(sources=sources, diagnostics=diagnostics)


def ingest_exports(
    inputs: Iterable[str | Path],
    database: str | Path,
    *,
    run_id: str | None = None,
    streaming: bool = True,
    mode: str = "skip_existing",
    trace_path: str | Path | None = None,
    logger: logging.Logger | None = None,
    raise_on_failure: bool = True,
) -> IngestResult:
    """Ingest one or more ChatGPT exports into a canonical SQLite archive.

    Inputs may be JSON files, export folders containing split
    ``conversations-###.json`` files, or ZIP exports. The operation is
    cumulative and preserves run provenance while deduplicating canonical
    conversation and message identities.
    """

    input_paths = [str(Path(item).expanduser().resolve()) for item in inputs]
    if not input_paths:
        raise ValueError("At least one ChatGPT export input is required.")
    if mode != "skip_existing":
        raise ValueError("Only the canonical 'skip_existing' mode is supported.")

    database_path = str(Path(database).expanduser().resolve())
    resolved_trace_path = str(Path(trace_path).expanduser().resolve()) if trace_path else None
    active_logger = logger or logging.getLogger("chatgpt_parser.api")
    raw = run_canonical_ingest(
        SimpleNamespace(
            inputs=input_paths,
            db=database_path,
            run_id=run_id,
            mode=mode,
            streaming=streaming,
            trace_run=resolved_trace_path,
        ),
        active_logger,
    ) or {}

    result = IngestResult(
        run_id=str(raw.get("run_id") or run_id or ""),
        database=database_path,
        stats={key: int(value) for key, value in (raw.get("stats") or {}).items()},
        elapsed_seconds=float(raw.get("elapsed_sec") or 0.0),
        skipped=bool(raw.get("skipped", False)),
        failed=bool(raw.get("failed", False)),
        partial=bool(raw.get("partial", False)),
        source_errors=int(raw.get("source_errors") or 0),
        conversation_errors=int(raw.get("conversation_errors") or 0),
        source_results=list(raw.get("source_results") or []),
        diagnostics=list(raw.get("diagnostics") or []),
        trace_path=raw.get("trace_path"),
    )
    if result.failed and raise_on_failure:
        raise IngestError(result)
    return result
