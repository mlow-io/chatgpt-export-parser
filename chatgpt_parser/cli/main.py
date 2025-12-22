import argparse
import json
import sys

from ..utils.logging import setup_logging
from . import commands
from ..core import exporter
from ..db import maintenance

def main():
    parser = argparse.ArgumentParser(description="ChatGPT Export Parser & Ingester")
    parser.add_argument("--quiet", action="store_true", help="Minimize stdout")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    # PARSE
    p_parse = subparsers.add_parser("parse", help="Normalize JSON to JSONL")
    p_parse.add_argument("inputs", nargs="+", help="Input JSON files")
    p_parse.add_argument("--output-dir", help="Specific output directory (must be empty)")
    p_parse.add_argument("--output-root", help="Root directory for runs (default: ./normalized_runs)")
    p_parse.add_argument("--run-id", help="Manual run ID")
    p_parse.add_argument("--force", action="store_true", help="Overwrite existing output-dir")
    p_parse.add_argument("--no-streaming", dest="streaming", action="store_false", help="Disable streaming parser (default: on)")
    p_parse.set_defaults(streaming=True)

    # INGEST
    p_ingest = subparsers.add_parser("ingest", help="Ingest JSONL to SQLite")
    p_ingest.add_argument("--jsonl-dir", required=True, help="Directory containing JSONL files")
    p_ingest.add_argument("--db", required=True, help="Path to SQLite DB")
    p_ingest.add_argument("--mode", choices=["skip_existing", "overwrite"], default="skip_existing")
    p_ingest.add_argument("--run-id", help="Override run ID")

    # PARSE-AND-INGEST
    p_both = subparsers.add_parser("parse-and-ingest", help="Parse then Ingest")
    p_both.add_argument("inputs", nargs="+", help="Input JSON files")
    p_both.add_argument("--output-dir", help="Specific output directory")
    p_both.add_argument("--output-root", help="Root directory for runs")
    p_both.add_argument("--run-id", help="Manual run ID")
    p_both.add_argument("--force", action="store_true")
    p_both.add_argument("--db", required=True, help="Path to SQLite DB")
    p_both.add_argument("--mode", choices=["skip_existing", "overwrite"], default="skip_existing")
    p_both.add_argument("--no-streaming", dest="streaming", action="store_false", help="Disable streaming parser (default: on)")
    p_both.set_defaults(streaming=True)

    # QUERY
    p_query = subparsers.add_parser("query", help="Query DB")
    p_query.add_argument("--db", required=True)
    p_query.add_argument("--type", choices=["conversations", "conversation_detail"], required=True)
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--conversation-id")
    p_query.add_argument("--include-hidden", default="false")
    p_query.add_argument("--format", choices=["json", "text"], default="text")
    p_query.add_argument("--order-by")

    # SEARCH
    p_search = subparsers.add_parser("search", help="Full-text search over messages")
    p_search.add_argument("--db", required=True)
    p_search.add_argument("--q", required=True, help="FTS query string")
    p_search.add_argument("--role")
    p_search.add_argument("--kind")
    p_search.add_argument("--conversation-id")
    p_search.add_argument("--run-id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--offset", type=int, default=0)
    p_search.add_argument("--format", choices=["json", "text"], default="json")

    # EXPORT
    p_export = subparsers.add_parser("export-conversation", help="Export a conversation to markdown/text")
    p_export.add_argument("--db", required=True)
    p_export.add_argument("--conversation-id", required=True)
    p_export.add_argument("--format", choices=["markdown", "text", "json"], default="markdown")
    p_export.add_argument("--output", help="Output file (default: stdout)")
    p_export.add_argument("--include-hidden", default="false")
    p_export.add_argument("--frontmatter", action="store_true")

    # BATCH EXPORT
    p_exports = subparsers.add_parser("export-conversations", help="Export multiple conversations")
    p_exports.add_argument("--db", required=True)
    p_exports.add_argument("--query", help="FTS query to select conversations")
    p_exports.add_argument("--limit", type=int, default=20)
    p_exports.add_argument("--output-dir", required=True)
    p_exports.add_argument("--format", choices=["markdown", "text"], default="markdown")
    p_exports.add_argument("--include-hidden", default="false")
    p_exports.add_argument("--frontmatter", action="store_true")

    # BUNDLE
    p_bundle = subparsers.add_parser("export-bundle", help="Export multiple conversations into one markdown")
    p_bundle.add_argument("--db", required=True)
    p_bundle.add_argument("--since-days", type=int, default=9)
    p_bundle.add_argument("--output-markdown", default="./exports/recent_bundle.md")
    p_bundle.add_argument("--include-hidden", default="false")
    p_bundle.add_argument("--frontmatter", action="store_true")

    # MAINTENANCE
    p_check = subparsers.add_parser("check", help="Integrity checks")
    p_check.add_argument("--db", required=True)
    p_check.add_argument("--format", choices=["json", "text"], default="json")

    p_runs = subparsers.add_parser("list-runs", help="List runs in DB")
    p_runs.add_argument("--db", required=True)
    p_runs.add_argument("--format", choices=["json", "text"], default="text")

    p_diff = subparsers.add_parser("diff-runs", help="Diff two runs")
    p_diff.add_argument("--db", required=True)
    p_diff.add_argument("--run-a", required=True)
    p_diff.add_argument("--run-b", required=True)
    p_diff.add_argument("--format", choices=["json", "text"], default="json")

    p_dump = subparsers.add_parser("dump-db", help="Dump SQLite DB to SQL file")
    p_dump.add_argument("--db", required=True)
    p_dump.add_argument("--output", required=True)

    p_restore = subparsers.add_parser("restore-db", help="Restore SQLite DB from SQL file")
    p_restore.add_argument("--input", required=True)
    p_restore.add_argument("--db", required=True)
    p_restore.add_argument("--force", action="store_true")

    p_migrate = subparsers.add_parser("migrate", help="Apply schema migrations")
    p_migrate.add_argument("--db", required=True)

    args = parser.parse_args()
    
    logger_verbose = args.verbose and not args.quiet and not args.json
    logger = setup_logging(None, verbose=logger_verbose)

    summary = {}

    if args.command == "parse":
        res = commands.run_parse(args, logger)
        if res:
            out_dir, run_id = res
            summary = {"run_id": run_id, "output_dir": out_dir}

    elif args.command == "ingest":
        commands.run_ingest(args, logger)
        summary = {"status": "ingested", "db": args.db}

    elif args.command == "parse-and-ingest":
        res = commands.run_parse(args, logger)
        if res:
            out_dir, run_id = res
            args.jsonl_dir = out_dir
            commands.run_ingest(args, logger)
            summary = {"run_id": run_id, "output_dir": out_dir, "db": args.db, "status": "completed"}
            
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

    elif args.command == "diff-runs":
        maintenance.run_diff_runs(args, logger)
        return

    elif args.command == "dump-db":
        maintenance.run_dump_db(args, logger)
        summary = {"status": "dumped", "output": args.output}

    elif args.command == "restore-db":
        maintenance.run_restore_db(args, logger)
        summary = {"status": "restored", "db": args.db}

    elif args.command == "migrate":
        maintenance.run_migrate(args, logger)
        summary = {"status": "migrated", "db": args.db}

    if args.json:
        print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
