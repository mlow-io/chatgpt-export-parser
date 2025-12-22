import json
from typing import Any, Dict, Iterable

def write_jsonl_line(f, obj: Dict[str, Any]) -> None:
    f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def stream_json_array(path: str, chunk_size: int = 65536) -> Iterable[Dict[str, Any]]:
    """
    Stream a top-level JSON array from disk without loading the whole file.
    Uses the standard library JSONDecoder to incrementally parse objects.
    """
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as f:
        buffer = ""
        idx = 0

        # Seek to the opening bracket
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                raise ValueError(f"File {path} does not contain a JSON array.")
            buffer += chunk
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1
            if idx < len(buffer):
                if buffer[idx] != "[":
                    raise ValueError(f"File {path} must start with a JSON array.")
                idx += 1
                buffer = buffer[idx:]
                idx = 0
                break

        while True:
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1

            # If buffer is exhausted, read more
            if idx >= len(buffer):
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                buffer = buffer[idx:] + chunk
                idx = 0
                continue

            # End of array
            if buffer[idx] == "]":
                return

            try:
                obj, next_idx = decoder.raw_decode(buffer, idx)
            except json.JSONDecodeError:
                chunk = f.read(chunk_size)
                if not chunk:
                    raise
                buffer = buffer[idx:] + chunk
                idx = 0
                continue

            yield obj
            idx = next_idx

            # Compact buffer occasionally to keep memory bounded
            if idx > 1024:
                buffer = buffer[idx:]
                idx = 0

            # Consume trailing whitespace and comma between elements
            while True:
                while idx < len(buffer) and buffer[idx].isspace():
                    idx += 1
                if idx < len(buffer) and buffer[idx] == ",":
                    idx += 1
                    break
                if idx < len(buffer) and buffer[idx] == "]":
                    return
                if idx >= len(buffer):
                    chunk = f.read(chunk_size)
                    if not chunk:
                        return
                    buffer = buffer[idx:] + chunk
                    idx = 0
                    continue
                # Unexpected character; try reading more
                chunk = f.read(chunk_size)
                if not chunk:
                    raise json.JSONDecodeError(
                        "Unexpected character while parsing JSON array", buffer, idx
                    )
                buffer = buffer[idx:] + chunk
                idx = 0
                break


def stream_json_array_from_file(f, chunk_size: int = 65536) -> Iterable[Dict[str, Any]]:
    """
    Stream a top-level JSON array from a file-like object without loading the whole file.
    Uses the standard library JSONDecoder to incrementally parse objects.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    idx = 0

    # Seek to the opening bracket
    while True:
        chunk = f.read(chunk_size)
        if not chunk:
            raise ValueError("File does not contain a JSON array.")
        buffer += chunk
        while idx < len(buffer) and buffer[idx].isspace():
            idx += 1
        if idx < len(buffer):
            if buffer[idx] != "[":
                raise ValueError("File must start with a JSON array.")
            idx += 1
            buffer = buffer[idx:]
            idx = 0
            break

    while True:
        while idx < len(buffer) and buffer[idx].isspace():
            idx += 1

        if idx >= len(buffer):
            chunk = f.read(chunk_size)
            if not chunk:
                return
            buffer = buffer[idx:] + chunk
            idx = 0
            continue

        if buffer[idx] == "]":
            return

        try:
            obj, next_idx = decoder.raw_decode(buffer, idx)
        except json.JSONDecodeError:
            chunk = f.read(chunk_size)
            if not chunk:
                raise
            buffer = buffer[idx:] + chunk
            idx = 0
            continue

        yield obj
        idx = next_idx

        if idx > 1024:
            buffer = buffer[idx:]
            idx = 0

        while True:
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1
            if idx < len(buffer) and buffer[idx] == ",":
                idx += 1
                break
            if idx < len(buffer) and buffer[idx] == "]":
                return
            if idx >= len(buffer):
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                buffer = buffer[idx:] + chunk
                idx = 0
                continue
            chunk = f.read(chunk_size)
            if not chunk:
                raise json.JSONDecodeError(
                    "Unexpected character while parsing JSON array", buffer, idx
                )
            buffer = buffer[idx:] + chunk
            idx = 0
            break
