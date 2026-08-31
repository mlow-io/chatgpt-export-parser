"""Content-free structural inspection for candidate ChatGPT exports.

This module deliberately does not share the ingest trace format.  It never
returns a supplied path, file/member name, JSON string value, URL, identifier,
or parser exception text.  It is intended to establish compatibility evidence
before an export is offered to canonical ingest.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator


REPORT_VERSION = 1
PROFILE_MAX_PATHS = 512
PROFILE_MAX_UNKNOWN_KEY_HASHES = 128
CONVERSATION_FILE_RE = re.compile(r"^conversations(?:-\d+)?\.json$", re.IGNORECASE)


# Only names with stable structural meaning are emitted.  Every other object
# key is represented as ``<unknown>`` and accounted for with an opaque hash.
KNOWN_KEYS = {
    "id",
    "conversation_id",
    "title",
    "create_time",
    "update_time",
    "mapping",
    "current_node",
    "conversation_origin",
    "is_do_not_remember",
    "async_status",
    "is_read_only",
    "default_model_slug",
    "is_archived",
    "is_starred",
    "safe_urls",
    "blocked_urls",
    "parent",
    "children",
    "message",
    "author",
    "role",
    "name",
    "recipient",
    "channel",
    "content",
    "content_type",
    "parts",
    "text",
    "metadata",
    "model_slug",
    "is_visually_hidden_from_conversation",
    "content_references",
    "citations",
    "attachments",
    "asset_pointer",
    "source_ref",
    "file_id",
    "filename",
    "mime_type",
    "content_type_mime_type",
    "size",
    "size_bytes",
    "width",
    "height",
    "url",
    "start_idx",
    "start_ix",
    "end_idx",
    "end_ix",
    "type",
    "result",
    "shared_conversation_id",
    "is_anonymous",
}

SAFE_ENUMS = {
    "roles": {"user", "assistant", "system", "tool", "developer"},
    "content_types": {
        "text",
        "multimodal_text",
        "code",
        "execution_output",
        "reasoning_recap",
        "thoughts",
        "model_thoughts",
        "image_asset_pointer",
    },
    "resource_types": {"image", "file", "image_asset_pointer"},
    "tool_types": {"all", "python", "browser", "web", "search", "dalle"},
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _opaque_unknown(value: str) -> str:
    return f"sha256:{_sha256_bytes(value.encode('utf-8'))[:16]}"


def _safe_enum(category: str, value: str) -> str:
    return value if value in SAFE_ENUMS[category] else _opaque_unknown(value)


def _safe_member_name(original_name: str, index: int, *, direct: bool = False) -> str:
    """Return a stable display handle without exposing a user-controlled name."""

    basename = original_name.replace("\\", "/").rsplit("/", 1)[-1]
    lower = basename.lower()
    if CONVERSATION_FILE_RE.fullmatch(basename):
        filename = lower
    elif lower in {"chat.html", "shared_conversations.json"}:
        filename = lower
    else:
        suffix = Path(basename).suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""
        filename = f"input{suffix}" if direct else f"member-{index:04d}{suffix}"
    return filename if direct or "/" not in original_name.replace("\\", "/") else f"member-{index:04d}/{filename}"


def _member_extension(original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


def _is_auxiliary_name(name: str) -> bool:
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower() in {
        "chat.html",
        "shared_conversations.json",
    }


@dataclass(frozen=True)
class _Member:
    original_name: str
    display_name: str
    extension: str
    declared_size: int | None
    source_kind: str
    opener: Callable[[], Iterator[BinaryIO]]

    @property
    def is_conversation_named(self) -> bool:
        return bool(CONVERSATION_FILE_RE.fullmatch(self.original_name.replace("\\", "/").rsplit("/", 1)[-1]))

    @property
    def is_auxiliary(self) -> bool:
        return _is_auxiliary_name(self.original_name)


@contextmanager
def _open_file(path: Path) -> Iterator[BinaryIO]:
    with path.open("rb") as handle:
        yield handle


@contextmanager
def _open_zip_member(path: Path, info: zipfile.ZipInfo) -> Iterator[BinaryIO]:
    with zipfile.ZipFile(path, "r") as archive:
        with archive.open(info, "r") as handle:
            yield handle


class _StructureCollector:
    """Aggregate only types, cardinalities, key structure, and safe enums."""

    def __init__(self) -> None:
        self.path_stats: dict[str, dict[str, Any]] = {}
        self.path_limit_reached = False
        self.unknown_key_count = 0
        self.unknown_key_hashes: set[str] = set()
        self.string_value_count = 0
        self.enums: dict[str, set[str]] = {key: set() for key in SAFE_ENUMS}
        self.recognized_features: set[str] = set()
        self.top_values = 0
        self.top_non_objects = 0
        self.conversation_candidates = 0
        self.candidate_missing_identity = 0
        self.candidate_mapping_not_object = 0
        self.graph = Counter()
        self.graph_ranges: dict[str, list[int]] = {}

    def _record(self, path: str, value: Any) -> None:
        if path not in self.path_stats and len(self.path_stats) >= PROFILE_MAX_PATHS:
            self.path_limit_reached = True
            return
        stat = self.path_stats.setdefault(
            path,
            {"observations": 0, "types": set(), "null_count": 0, "array_lengths": [], "object_key_counts": []},
        )
        stat["observations"] += 1
        if value is None:
            stat["types"].add("null")
            stat["null_count"] += 1
        elif isinstance(value, bool):
            stat["types"].add("boolean")
        elif isinstance(value, str):
            stat["types"].add("string")
            self.string_value_count += 1
        elif isinstance(value, int):
            stat["types"].add("integer")
        elif isinstance(value, float):
            stat["types"].add("number")
        elif isinstance(value, list):
            stat["types"].add("array")
            stat["array_lengths"].append(len(value))
        elif isinstance(value, dict):
            stat["types"].add("object")
            stat["object_key_counts"].append(len(value))
        else:
            stat["types"].add(type(value).__name__)

    def _record_range(self, name: str, value: int) -> None:
        values = self.graph_ranges.setdefault(name, [])
        values.append(value)

    def _record_enum(self, key: str | None, value: Any, path: str) -> None:
        if not isinstance(value, str) or key is None:
            return
        if key == "role":
            self.enums["roles"].add(_safe_enum("roles", value))
        elif key == "content_type":
            self.enums["content_types"].add(_safe_enum("content_types", value))
        elif key == "recipient" and ".message." in path:
            self.enums["tool_types"].add(_safe_enum("tool_types", value))
        elif key == "type" and (".attachments" in path or ".parts" in path):
            self.enums["resource_types"].add(_safe_enum("resource_types", value))

    def walk(self, value: Any, path: str = "$", *, key: str | None = None, depth: int = 0) -> None:
        # A structural report must remain bounded even for hostile nesting.
        if depth > 64:
            self.path_limit_reached = True
            return
        self._record(path, value)
        self._record_enum(key, value, path)
        if isinstance(value, dict):
            for child_key in sorted(value):
                safe_key = child_key if child_key in KNOWN_KEYS else "<unknown>"
                if safe_key == "<unknown>":
                    self.unknown_key_count += 1
                    if len(self.unknown_key_hashes) < PROFILE_MAX_UNKNOWN_KEY_HASHES:
                        self.unknown_key_hashes.add(_opaque_unknown(str(child_key)))
                if child_key in {
                    "mapping",
                    "parent",
                    "children",
                    "current_node",
                    "author",
                    "content",
                    "content_references",
                    "citations",
                    "attachments",
                }:
                    self.recognized_features.add(child_key)
                self.walk(value[child_key], f"{path}.{safe_key}", key=child_key, depth=depth + 1)
        elif isinstance(value, list):
            for item in value:
                self.walk(item, f"{path}[]", key=key, depth=depth + 1)

    def analyze_top_value(self, value: Any) -> None:
        self.top_values += 1
        if not isinstance(value, dict):
            self.top_non_objects += 1
            self.walk(value)
            return
        self.walk(value)
        mapping = value.get("mapping")
        if "mapping" not in value:
            return
        self.conversation_candidates += 1
        if not (value.get("id") or value.get("conversation_id")):
            self.candidate_missing_identity += 1
        if not isinstance(mapping, dict):
            self.candidate_mapping_not_object += 1
            return
        self._analyze_mapping(mapping, value.get("current_node"))

    def _analyze_mapping(self, mapping: dict[str, Any], current_node: Any) -> None:
        self.graph["mappings"] += 1
        self.graph["nodes"] += len(mapping)
        self._record_range("mapping_nodes", len(mapping))
        parents: dict[str, str | None] = {}
        child_edges: list[tuple[str, str]] = []
        for node_id, node in mapping.items():
            if node is None:
                self.graph["null_nodes"] += 1
                continue
            if not isinstance(node, dict):
                self.graph["non_object_nodes"] += 1
                continue
            if isinstance(node.get("message"), dict):
                self.graph["nodes_with_message"] += 1
            if "parent" in node:
                self.graph["nodes_with_parent_field"] += 1
            if "children" in node:
                self.graph["nodes_with_children_field"] += 1
            parent = node.get("parent")
            parents[str(node_id)] = str(parent) if isinstance(parent, str) else None
            if isinstance(parent, str):
                self.graph["parent_references"] += 1
                if parent not in mapping:
                    self.graph["dangling_parent_references"] += 1
            children = node.get("children")
            if not isinstance(children, list):
                if children is not None:
                    self.graph["malformed_children_fields"] += 1
                continue
            for child in children:
                if not isinstance(child, str):
                    self.graph["non_string_child_references"] += 1
                    continue
                self.graph["child_references"] += 1
                child_edges.append((str(node_id), child))
                if child not in mapping:
                    self.graph["dangling_child_references"] += 1
        roots = sum(1 for node_id in parents if parents[node_id] is None)
        self.graph["roots"] += roots
        self._record_range("roots", roots)
        for parent, child in child_edges:
            if child in parents and parents[child] != parent:
                self.graph["parent_child_mismatches"] += 1
        self._record_current_path(parents, mapping, current_node)
        if self._has_parent_cycle(parents):
            self.graph["parent_cycles"] += 1

    def _record_current_path(self, parents: dict[str, str | None], mapping: dict[str, Any], current_node: Any) -> None:
        if not isinstance(current_node, str):
            self.graph["current_node_not_provided"] += 1
            return
        self.graph["current_node_provided"] += 1
        if current_node not in mapping:
            self.graph["current_node_missing"] += 1
            return
        seen: set[str] = set()
        cursor: str | None = current_node
        length = 0
        while cursor is not None and cursor in parents:
            if cursor in seen:
                self.graph["current_path_cycle"] += 1
                return
            seen.add(cursor)
            length += 1
            cursor = parents.get(cursor)
        self.graph["current_paths_resolved"] += 1
        self._record_range("current_path_length", length)

    @staticmethod
    def _has_parent_cycle(parents: dict[str, str | None]) -> bool:
        for start in parents:
            seen: set[str] = set()
            cursor: str | None = start
            while cursor is not None and cursor in parents:
                if cursor in seen:
                    return True
                seen.add(cursor)
                cursor = parents.get(cursor)
        return False

    def render(self) -> dict[str, Any]:
        paths: list[dict[str, Any]] = []
        for path in sorted(self.path_stats):
            stat = self.path_stats[path]
            row: dict[str, Any] = {
                "path": path,
                "observations": stat["observations"],
                "types": sorted(stat["types"]),
                "null_count": stat["null_count"],
            }
            if stat["array_lengths"]:
                row["array_length"] = {
                    "min": min(stat["array_lengths"]),
                    "max": max(stat["array_lengths"]),
                }
            if stat["object_key_counts"]:
                row["object_key_count"] = {
                    "min": min(stat["object_key_counts"]),
                    "max": max(stat["object_key_counts"]),
                }
            paths.append(row)
        graph = {key: self.graph[key] for key in sorted(self.graph)}
        for name, values in sorted(self.graph_ranges.items()):
            graph[f"{name}_range"] = {"min": min(values), "max": max(values)}
        return {
            "paths": paths,
            "path_limit_reached": self.path_limit_reached,
            "top_level": {
                "values": self.top_values,
                "non_object_values": self.top_non_objects,
                "mapping_candidates": self.conversation_candidates,
                "candidates_missing_identity": self.candidate_missing_identity,
                "candidates_with_non_object_mapping": self.candidate_mapping_not_object,
            },
            "graph": graph,
            "safe_enums": {key: sorted(values) for key, values in sorted(self.enums.items()) if values},
            "recognized_features": sorted(self.recognized_features),
            "unknown_structure": {
                "unknown_key_count": self.unknown_key_count,
                "unknown_key_hashes": sorted(self.unknown_key_hashes),
                "string_value_count": self.string_value_count,
            },
        }


def _hash_member(member: _Member) -> tuple[str | None, int | None, str | None]:
    digest = hashlib.sha256()
    size = 0
    try:
        with member.opener() as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return None, None, "member_read_error"
    return digest.hexdigest(), size, None


def _first_non_whitespace(member: _Member) -> tuple[str | None, str | None]:
    try:
        with member.opener() as handle:
            prefix = handle.read(65536)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return None, "member_read_error"
    text = prefix.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    return (stripped[0] if stripped else None), None


def _scan_json_array(member: _Member, collector: _StructureCollector) -> str | None:
    decoder = json.JSONDecoder()
    try:
        with member.opener() as binary:
            handle = io.TextIOWrapper(binary, encoding="utf-8")
            buffer = ""
            index = 0
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    return "malformed_json"
                buffer += chunk
                while index < len(buffer) and buffer[index].isspace():
                    index += 1
                if index < len(buffer):
                    if buffer[index] != "[":
                        return "malformed_json"
                    index += 1
                    buffer = buffer[index:]
                    index = 0
                    break
            while True:
                while index < len(buffer) and buffer[index].isspace():
                    index += 1
                if index >= len(buffer):
                    chunk = handle.read(65536)
                    if not chunk:
                        return "malformed_json"
                    buffer = buffer[index:] + chunk
                    index = 0
                    continue
                if buffer[index] == "]":
                    tail = buffer[index + 1:] + handle.read()
                    return None if not tail.strip() else "malformed_json"
                try:
                    value, next_index = decoder.raw_decode(buffer, index)
                except json.JSONDecodeError:
                    chunk = handle.read(65536)
                    if not chunk:
                        return "malformed_json"
                    buffer = buffer[index:] + chunk
                    index = 0
                    continue
                collector.analyze_top_value(value)
                index = next_index
                if index > 1024:
                    buffer = buffer[index:]
                    index = 0
                while True:
                    while index < len(buffer) and buffer[index].isspace():
                        index += 1
                    if index < len(buffer) and buffer[index] == ",":
                        index += 1
                        break
                    if index < len(buffer) and buffer[index] == "]":
                        tail = buffer[index + 1:] + handle.read()
                        return None if not tail.strip() else "malformed_json"
                    if index >= len(buffer):
                        chunk = handle.read(65536)
                        if not chunk:
                            return "malformed_json"
                        buffer = buffer[index:] + chunk
                        index = 0
                        continue
                    return "malformed_json"
    except (OSError, UnicodeError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return "member_read_error"


def _load_json_value(member: _Member) -> tuple[Any, str | None]:
    try:
        with member.opener() as binary:
            return json.load(io.TextIOWrapper(binary, encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return None, "malformed_json"


def _scan_jsonl(member: _Member, collector: _StructureCollector) -> tuple[int, str | None]:
    count = 0
    try:
        with member.opener() as binary:
            handle = io.TextIOWrapper(binary, encoding="utf-8")
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                collector.analyze_top_value(value)
                count += 1
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        return count, "malformed_json"
    return count, None


def _fidelity_capabilities(structure: dict[str, Any]) -> dict[str, str]:
    graph = structure["graph"]
    top = structure["top_level"]
    mappings = graph.get("mappings", 0)
    nodes = graph.get("nodes", 0)
    if not mappings:
        tree = "not_provided"
        branches = "not_provided"
    elif not nodes:
        tree = "explicit_empty_mapping"
        branches = "not_provided"
    else:
        tree = "explicit_mapping"
        branches = (
            "explicit_children"
            if graph.get("nodes_with_children_field", 0) == nodes
            else "partial_or_parent_only"
        )
    if graph.get("current_paths_resolved", 0):
        current_path = "provided_and_resolvable"
    elif graph.get("current_node_provided", 0):
        current_path = "provided_but_unresolvable"
    else:
        current_path = "not_provided"
    return {
        "conversation_identity": "source_identifier_present" if not top["candidates_missing_identity"] else "incomplete",
        "conversation_tree": tree,
        "branch_relationships": branches,
        "current_path": current_path,
        "author_recipient": "structurally_present" if "author" in structure["recognized_features"] else "not_observed",
        "resources": (
            "structurally_present"
            if {"attachments", "citations", "content_references"} & set(structure["recognized_features"])
            else "not_observed"
        ),
    }


def _classify_json(structure: dict[str, Any], framing: str) -> tuple[str, str | None, list[dict[str, str]]]:
    top = structure["top_level"]
    graph = structure["graph"]
    findings: list[dict[str, str]] = []
    if framing == "jsonl":
        return "unsupported_jsonl_not_verified", None, [{"severity": "fatal", "code": "jsonl_not_verified"}]
    if framing != "json_array":
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "top_level_array_required"}]
    if top["values"] == 0:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "empty_conversation_collection"}]
    if top["non_object_values"]:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "non_object_conversation_record"}]
    if top["mapping_candidates"] != top["values"]:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "conversation_record_without_mapping"}]
    if not top["mapping_candidates"]:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "mapping_tree_not_observed"}]
    if top["candidates_missing_identity"]:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "conversation_identity_missing"}]
    if top["candidates_with_non_object_mapping"]:
        return "ambiguous_or_unsupported", None, [{"severity": "fatal", "code": "mapping_not_object"}]
    for name, code in (
        ("dangling_parent_references", "dangling_parent_reference"),
        ("dangling_child_references", "dangling_child_reference"),
        ("parent_child_mismatches", "parent_child_mismatch"),
        ("parent_cycles", "parent_cycle"),
        ("malformed_children_fields", "malformed_children_field"),
        ("non_string_child_references", "non_string_child_reference"),
    ):
        if graph.get(name, 0):
            findings.append({"severity": "fatal", "code": code})
    if graph.get("current_node_missing", 0):
        findings.append({"severity": "nonfatal", "code": "current_node_not_in_mapping"})
    if not graph.get("current_node_provided", 0):
        findings.append({"severity": "nonfatal", "code": "current_path_not_provided"})
    if any(item["severity"] == "fatal" for item in findings):
        return "ambiguous_or_unsupported", None, findings
    return "mapping_tree_array", "mapping-tree-v1", findings


def _inspect_member(member: _Member) -> dict[str, Any]:
    content_sha256, observed_size, read_error = _hash_member(member)
    row: dict[str, Any] = {
        "name": member.display_name,
        "source_kind": member.source_kind,
        "designation": (
            "conversation_payload"
            if member.is_conversation_named
            else "auxiliary" if member.is_auxiliary else "unclassified"
        ),
        "extension": member.extension or None,
        "size_bytes": member.declared_size if member.declared_size is not None else observed_size,
        "content_sha256": content_sha256,
    }
    if read_error:
        row.update({
            "framing": "unreadable",
            "compatibility": "reject",
            "detected_dialect": "unreadable",
            "normalization_generation": None,
            "findings": [{"severity": "fatal", "code": read_error}],
        })
        return row
    if member.extension == ".html":
        row.update({
            "framing": "html",
            "compatibility": "diagnostic_only",
            "detected_dialect": "rendered_html",
            "normalization_generation": None,
            "findings": [{"severity": "nonfatal", "code": "html_not_canonical_ingest_source"}],
        })
        return row
    if member.extension not in {".json", ".jsonl"}:
        row.update({
            "framing": "non_json",
            "compatibility": "auxiliary_or_unsupported",
            "detected_dialect": "not_json",
            "normalization_generation": None,
            "findings": [{"severity": "nonfatal", "code": "non_json_auxiliary_member"}],
        })
        return row

    first, first_error = _first_non_whitespace(member)
    if first_error:
        row.update({
            "framing": "unreadable",
            "compatibility": "reject",
            "detected_dialect": "unreadable",
            "normalization_generation": None,
            "findings": [{"severity": "fatal", "code": first_error}],
        })
        return row
    collector = _StructureCollector()
    if member.extension == ".jsonl":
        _, error = _scan_jsonl(member, collector)
        framing = "jsonl" if not error else "malformed_json"
    elif first == "[":
        error = _scan_json_array(member, collector)
        framing = "json_array" if not error else "malformed_json"
    elif first == "{":
        value, error = _load_json_value(member)
        if error:
            count, jsonl_error = _scan_jsonl(member, collector)
            if not jsonl_error and count > 1:
                framing = "jsonl"
                error = None
            else:
                framing = "malformed_json"
        else:
            collector.analyze_top_value(value)
            framing = "json_object"
    else:
        count, error = _scan_jsonl(member, collector)
        if error:
            framing = "malformed_json"
        elif count > 1:
            framing = "jsonl"
        elif count == 1:
            framing = "json_scalar"
        else:
            framing = "malformed_json"
            error = "malformed_json"
    if error:
        row.update({
            "framing": framing,
            "compatibility": "reject",
            "detected_dialect": "malformed_or_unreadable_json",
            "normalization_generation": None,
            "findings": [{"severity": "fatal", "code": error}],
        })
        return row
    structure = collector.render()
    dialect, generation, findings = _classify_json(structure, framing)
    if dialect == "mapping_tree_array":
        compatibility = "candidate_supported"
    elif member.is_auxiliary:
        compatibility = "auxiliary_or_unsupported"
    else:
        compatibility = "reject"
    row.update({
        "framing": framing,
        "top_level_type": "array" if framing == "json_array" else "object" if framing == "json_object" else "jsonl",
        "compatibility": compatibility,
        "detected_dialect": dialect,
        "normalization_generation": generation,
        "fidelity_capabilities": _fidelity_capabilities(structure),
        "structure": structure,
        "findings": findings,
    })
    return row


def _collect_directory_members(path: Path) -> tuple[list[_Member], dict[str, Any]]:
    entries: list[Path] = []
    skipped_symlinks = 0
    try:
        for root, directories, filenames in os.walk(path, followlinks=False):
            symlink_directories = [name for name in directories if Path(root, name).is_symlink()]
            directories[:] = sorted(name for name in directories if name not in symlink_directories)
            skipped_symlinks += len(symlink_directories)
            for filename in sorted(filenames):
                candidate = Path(root, filename)
                if candidate.is_symlink():
                    skipped_symlinks += 1
                elif candidate.is_file():
                    entries.append(candidate)
        entries.sort(key=lambda item: item.relative_to(path).as_posix())
    except OSError:
        return [], {"kind": "directory", "status": "unreadable", "skipped_symlink_count": skipped_symlinks}
    members = [
        _Member(
            original_name=item.relative_to(path).as_posix(),
            display_name=_safe_member_name(item.relative_to(path).as_posix(), index),
            extension=_member_extension(item.name),
            declared_size=item.stat().st_size,
            source_kind="directory_member",
            opener=lambda item=item: _open_file(item),
        )
        for index, item in enumerate(entries, start=1)
    ]
    return members, {"kind": "directory", "status": "ok", "skipped_symlink_count": skipped_symlinks}


def _collect_zip_members(path: Path) -> tuple[list[_Member], dict[str, Any]]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return [], {"kind": "zip_archive", "status": "unreadable"}
    infos.sort(key=lambda info: (info.filename.replace("\\", "/"), info.header_offset))
    members = [
        _Member(
            original_name=info.filename,
            display_name=_safe_member_name(info.filename, index),
            extension=_member_extension(info.filename),
            declared_size=info.file_size,
            source_kind="zip_member",
            opener=lambda info=info: _open_zip_member(path, info),
        )
        for index, info in enumerate(infos, start=1)
    ]
    return members, {"kind": "zip_archive", "status": "ok", "skipped_symlink_count": 0}


def _collect_members(input_path: str | Path) -> tuple[list[_Member], dict[str, Any]]:
    path = Path(input_path).expanduser()
    try:
        if path.is_dir():
            return _collect_directory_members(path)
        if path.is_file() and path.suffix.lower() == ".zip":
            return _collect_zip_members(path)
        if path.is_file():
            return [
                _Member(
                    original_name=path.name,
                    display_name=_safe_member_name(path.name, 1, direct=True),
                    extension=_member_extension(path.name),
                    declared_size=path.stat().st_size,
                    source_kind="direct_file",
                    opener=lambda: _open_file(path),
                )
            ], {"kind": "direct_file", "status": "ok", "skipped_symlink_count": 0}
    except OSError:
        pass
    return [], {"kind": "unavailable", "status": "unreadable", "skipped_symlink_count": 0}


def _report_structural_fingerprint(container: dict[str, Any], members: list[dict[str, Any]]) -> str:
    # Deliberately excludes file hashes, private values, and user-provided label/date.
    def fingerprint_value(value: Any) -> Any:
        if isinstance(value, list):
            return [fingerprint_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: fingerprint_value(item)
                for key, item in value.items()
                # Unknown key hashes can be derived from node IDs or arbitrary
                # metadata names. They are useful local diagnostics but are not
                # part of a value-independent structural fingerprint.
                if key != "unknown_key_hashes"
            }
        return value

    structural_members = [
        {
            key: member[key]
            for key in (
                "extension",
                "source_kind",
                "framing",
                "top_level_type",
                "compatibility",
                "detected_dialect",
                "normalization_generation",
                "fidelity_capabilities",
                "structure",
                "findings",
            )
            if key in member
        }
        for member in members
    ]
    payload = json.dumps(
        {"container": fingerprint_value(container), "members": fingerprint_value(structural_members)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_bytes(payload.encode("utf-8"))


def profile_export(
    input_path: str | Path,
    *,
    label: str = "input",
    acquisition_date: str | None = None,
) -> dict[str, Any]:
    """Inspect one candidate input without creating or modifying a database.

    ``label`` and ``acquisition_date`` are caller-supplied provenance only.  A
    raw path is intentionally never returned, including in error cases.
    """

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", label):
        raise ValueError("label must be an opaque identifier using letters, digits, hyphen, or underscore")
    if acquisition_date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", acquisition_date):
        raise ValueError("acquisition_date must use YYYY-MM-DD")
    members, container = _collect_members(input_path)
    reports = [_inspect_member(member) for member in members]
    candidates = [member for member in reports if member.get("compatibility") == "candidate_supported"]
    # Auxiliary or unclassified folder/ZIP members do not veto an independently
    # recognized conversation payload.  A direct file or a named conversation
    # payload must be structurally interpretable before it can be considered.
    fatal_payloads = [
        member for member in reports
        if member.get("compatibility") == "reject"
        and (member["source_kind"] == "direct_file" or member["designation"] == "conversation_payload")
    ]
    if container["status"] != "ok":
        compatibility = "reject"
        findings = [{"severity": "fatal", "code": "container_unreadable"}]
    elif fatal_payloads:
        compatibility = "reject"
        findings = [{"severity": "fatal", "code": "unsupported_or_malformed_payload_member"}]
    elif candidates:
        compatibility = "candidate_supported"
        findings = []
    elif reports and all(member["compatibility"] == "diagnostic_only" for member in reports):
        compatibility = "diagnostic_only"
        findings = [{"severity": "nonfatal", "code": "no_canonical_json_payload"}]
    else:
        compatibility = "reject"
        findings = [{"severity": "fatal", "code": "no_recognized_conversation_payload"}]
    report = {
        "report_version": REPORT_VERSION,
        "label": label,
        "acquisition_date": acquisition_date,
        "privacy": {
            "content_free": True,
            "raw_paths_emitted": False,
            "raw_member_names_emitted": False,
            "arbitrary_string_values_emitted": False,
            "safe_enum_values_allowlisted": True,
        },
        "container": {**container, "member_count": len(reports)},
        "members": reports,
        "compatibility": compatibility,
        "findings": findings,
    }
    report["structural_fingerprint"] = _report_structural_fingerprint(report["container"], reports)
    return report
