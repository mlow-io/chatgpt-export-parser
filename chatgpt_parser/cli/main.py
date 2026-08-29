import argparse
import json

from ..api import ingest_exports, inspect_inputs, parser_contract
from ..core import exporter
from ..db import maintenance
from ..utils.logging import setup_logging
from . import commands


def _add_ingest_arguments(command_parser: argparse.ArgumentParser, help_text: str) -> None:
    command_parser.description = help_text
    command_parser.add_argument("inputs", nargs="+", help="Input JSON files, export folders, ZIP files, or chat.html diagnostic targets")
    command_parser.add_argument("--db", required=True, help="Path to canonical SQLite DB")
    command_parser.add_argument("--run-id", help="Manual run ID for provenance")
    command_parser.add_argument(
        "--mode",
        choices=["skip_existing"],
        default="skip_existing",
        help="Canonical ingest keeps append/skip semantics for existing run IDs.",
    )
    command_parser.add_argument("--no-streaming", dest="streaming", action="store_false")
    command_parser.add_argument(
        "--trace-run",
        help="Write a JSON trace describing input discovery, ingest mechanics, and per-source outcomes.",
    )
    command_parser.set_defaults(streaming=True)


def main():
    parser = argparse.ArgumentParser(description="AtlasBench Parser canonical archive CLI")
    parser.add_argument("--quiet", action="store_true", help="Minimize stdout")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser(
        "parse-and-ingest",
        help="Standard workflow: ingest ChatGPT exports into the canonical archive DB",
    )
    _add_ingest_arguments(
        p_ingest,
        "Parse ChatGPT export JSON/ZIP files and merge them into a canonical archive DB.",
    )

    p_canonical = subparsers.add_parser(
        "canonical-ingest",
        help="Explicit alias for canonical archive ingestion",
    )
    _add_ingest_arguments(
        p_canonical,
        "Alias of parse-and-ingest for explicit canonical archive workflows.",
    )

    p_query = subparsers.add_parser("query", help="Query canonical archive DB")
    p_query.add_argument("--db", required=True)
    p_query.add_argument("--type", choices=["conversations", "conversation_detail"], required=True)
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--conversation-id")
    p_query.add_argument("--include-hidden", default="false")
    p_query.add_argument("--format", choices=["json", "text"], default="text")
    p_query.add_argument("--order-by")

    p_search = subparsers.add_parser("search", help="Full-text search over canonical messages")
    p_search.add_argument("--db", required=True)
    p_search.add_argument("--q", required=True, help="FTS query string")
    p_search.add_argument("--role")
    p_search.add_argument("--kind")
    p_search.add_argument("--conversation-id")
    p_search.add_argument("--run-id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--offset", type=int, default=0)
    p_search.add_argument("--format", choices=["json", "text"], default="json")

    p_export = subparsers.add_parser("export-conversation", help="Export a conversation to markdown/text")
    p_export.add_argument("--db", required=True)
    p_export.add_argument("--conversation-id", required=True)
    p_export.add_argument("--format", choices=["markdown", "text", "json"], default="markdown")
    p_export.add_argument("--output", help="Output file (default: stdout)")
    p_export.add_argument("--include-hidden", default="false")
    p_export.add_argument("--frontmatter", action="store_true")

    p_exports = subparsers.add_parser("export-conversations", help="Export multiple conversations")
    p_exports.add_argument("--db", required=True)
    p_exports.add_argument("--query", help="FTS query to select conversations")
    p_exports.add_argument("--limit", type=int, default=20)
    p_exports.add_argument("--output-dir", required=True)
    p_exports.add_argument("--format", choices=["markdown", "text"], default="markdown")
    p_exports.add_argument("--include-hidden", default="false")
    p_exports.add_argument("--frontmatter", action="store_true")

    p_bundle = subparsers.add_parser("export-bundle", help="Export multiple conversations into one markdown")
    p_bundle.add_argument("--db", required=True)
    p_bundle.add_argument("--since-days", type=int, default=9)
    p_bundle.add_argument("--output-markdown", default="./exports/recent_bundle.md")
    p_bundle.add_argument("--include-hidden", default="false")
    p_bundle.add_argument("--frontmatter", action="store_true")

    p_check = subparsers.add_parser("check", help="Integrity checks")
    p_check.add_argument("--db", required=True)
    p_check.add_argument("--format", choices=["json", "text"], default="json")

    p_runs = subparsers.add_parser("list-runs", help="List canonical ingest runs")
    p_runs.add_argument("--db", required=True)
    p_runs.add_argument("--format", choices=["json", "text"], default="text")

    p_dump = subparsers.add_parser("dump-db", help="Dump SQLite DB to SQL file")
    p_dump.add_argument("--db", required=True)
    p_dump.add_argument("--output", required=True)

    p_restore = subparsers.add_parser("restore-db", help="Restore SQLite DB from SQL file")
    p_restore.add_argument("--input", required=True)
    p_restore.add_argument("--db", required=True)
    p_restore.add_argument("--force", action="store_true")

    subparsers.add_parser("contract", help="Print the versioned Python/native integration contract")

    p_inspect = subparsers.add_parser("inspect-inputs", help="Inspect export inputs without changing a database")
    p_inspect.add_argument("inputs", nargs="+")

    args = parser.parse_args()
    logger = setup_logging(None, verbose=args.verbose and not args.quiet and not args.json)
    summary = {}

    if args.command in {"canonical-ingest", "parse-and-ingest"}:
        result = ingest_exports(
            args.inputs,
            args.db,
            run_id=args.run_id,
            streaming=args.streaming,
            mode=args.mode,
            trace_path=args.trace_run,
            logger=logger,
            raise_on_failure=False,
        )
        summary = {
            "status": "failed" if result.failed else "canonical_ingested",
            "db": result.database,
            "run_id": result.run_id,
            "stats": result.stats,
            "elapsed_sec": result.elapsed_seconds,
            "skipped": result.skipped,
            "partial": result.partial,
            "source_errors": result.source_errors,
            "conversation_errors": result.conversation_errors,
            "source_results": result.source_results,
            "diagnostics": result.diagnostics,
            "trace_path": result.trace_path,
        }
    elif args.command == "query":
        commands.run_query(args, logger)
        return
    elif args.command == "search":
        commands.run_search(args, logger)
        return
    elif args.command == "export-conversation":
        exporter.run_export_conversation(args, logger)
        return
    elif args.command == "export-conversations":
        commands.run_export_conversations(args, logger)
        return
    elif args.command == "export-bundle":
        commands.run_export_bundle(args, logger)
        return
    elif args.command == "check":
        maintenance.run_check(args, logger)
        return
    elif args.command == "list-runs":
        maintenance.run_list_runs(args, logger)
        return
    elif args.command == "dump-db":
        maintenance.run_dump_db(args, logger)
        summary = {"status": "dumped", "output": args.output}
    elif args.command == "restore-db":
        maintenance.run_restore_db(args, logger)
        summary = {"status": "restored", "db": args.db}
    elif args.command == "contract":
        print(json.dumps(parser_contract(), indent=2))
        return
    elif args.command == "inspect-inputs":
        print(json.dumps(inspect_inputs(args.inputs).to_dict(), indent=2))
        return

    if args.json:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
