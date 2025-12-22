import json
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

from ..utils.io import write_jsonl_line
from ..utils.text import extract_urls_from_text, parse_url
from ..utils.date import iso_from_timestamp

def determine_message_kind(role: str, ctype: str, recipient: str, content: Dict[str, Any]) -> str:
    if role == "user":
        return "user_visible_user"
    
    if role == "system":
        return "system_context"
        
    if role == "tool":
        return "tool_result"
        
    if role == "assistant":
        if ctype == "code" and recipient != "all":
            return "tool_call"
        if ctype in ("reasoning_recap", "thoughts", "model_thoughts"):
            return "internal_reasoning"
        return "user_visible_assistant"
        
    return "unknown"


def process_conversation(conv: Dict[str, Any],
                         writers: Dict[str, Any],
                         stats: Dict[str, Any],
                         run_id: str,
                         source_file: str) -> None:
    conv_id = conv.get("id") or conv.get("conversation_id")
    mapping = conv.get("mapping") or {}
    current_node_id = conv.get("current_node")

    # 1. Build Graph
    parents: Dict[str, Optional[str]] = {}
    children: Dict[str, List[str]] = defaultdict(list)
    for node_id, node in mapping.items():
        parent_id = node.get("parent")
        parents[node_id] = parent_id
        for child_id in node.get("children") or []:
            children[node_id].append(child_id)
            
    roots = [nid for nid, pid in parents.items() if pid is None]
    depth: Dict[str, int] = {}
    queue = deque(roots)
    for r in roots:
        depth[r] = 0
    
    while queue:
        nid = queue.popleft()
        d = depth[nid]
        for child_id in children.get(nid, []):
            if child_id not in depth:
                depth[child_id] = d + 1
                queue.append(child_id)

    # 2. Main Path
    main_path_index: Dict[str, int] = {}
    if current_node_id and current_node_id in mapping:
        path = []
        curr = current_node_id
        while curr and curr in mapping:
            path.append(curr)
            curr = parents.get(curr)
        path.reverse()
        main_path_index = {nid: idx for idx, nid in enumerate(path)}

    # 3. Time Index Calculation
    # Collect all messages, sort by created_at, assign index
    all_msgs = []
    for node_id, node in mapping.items():
        msg = node.get("message")
        if msg:
            create_time = msg.get("create_time") or 0
            all_msgs.append((create_time, node_id))
    
    all_msgs.sort(key=lambda x: x[0]) # stable sort by time
    time_indices = {nid: i for i, (ct, nid) in enumerate(all_msgs)}

    # 3b. Emit node_children edges for branch reconstruction
    for parent_node_id, child_list in children.items():
        for child_index, child_node_id in enumerate(child_list):
            edge_row = {
                "run_id": run_id,
                "conversation_id": conv_id,
                "parent_node_id": parent_node_id,
                "child_node_id": child_node_id,
                "child_index": child_index,
            }
            write_jsonl_line(writers["node_children"], edge_row)
            stats["node_children"] += 1

    # 4. Models Used
    models_used = set()
    message_count = 0
    
    # emit nodes & messages
    for node_id, node in mapping.items():
        if node is None:
            continue  # skip null mapping entries
        msg_obj = node.get("message") or {}

        # NODE
        node_row = {
            "run_id": run_id,
            "id": node_id,
            "conversation_id": conv_id,
            "parent_id": parents.get(node_id),
            "children_ids": children.get(node_id, []),
            "message_id": msg_obj.get("id") if isinstance(msg_obj, dict) else None,
            "is_root": parents.get(node_id) is None,
            "is_in_main_path": node_id in main_path_index,
            "depth": depth.get(node_id),
            "main_path_index": main_path_index.get(node_id),
        }
        write_jsonl_line(writers["nodes"], node_row)
        stats["nodes"] += 1

        # MESSAGE
        message = msg_obj if isinstance(msg_obj, dict) else None
        if message:
            message_count += 1
            msg_id = message.get("id")
            author = message.get("author") or {}
            role = author.get("role")
            content = message.get("content") or {}
            ctype = content.get("content_type")
            recipient = message.get("recipient")
            
            # Normalize text
            text = None
            if ctype == "text":
                parts = content.get("parts") or []
                text = "\n\n".join(str(p) for p in parts)
            elif ctype in ("code", "execution_output", "reasoning_recap"):
                text = content.get("text") or content.get("content")
            
            md = message.get("metadata") or {}
            if md.get("model_slug"): models_used.add(md["model_slug"])
            if md.get("default_model_slug"): models_used.add(md["default_model_slug"])

            m_kind = determine_message_kind(role, ctype, recipient, content)

            msg_row = {
                "run_id": run_id,
                "id": msg_id,
                "node_id": node_id,
                "conversation_id": conv_id,
                "role": role,
                "author_name": author.get("name"),
                "recipient": recipient,
                "channel": message.get("channel"),
                "content_type": ctype,
                "text": text,
                "raw_content": content,
                "created_at": iso_from_timestamp(message.get("create_time")),
                "updated_at": iso_from_timestamp(message.get("update_time")),
                "is_hidden": bool(md.get("is_visually_hidden_from_conversation")),
                "hidden_reason": "visually_hidden" if md.get("is_visually_hidden_from_conversation") else None,
                "is_in_main_path": node_id in main_path_index,
                "main_path_index": main_path_index.get(node_id),
                "depth": depth.get(node_id),
                "model": md.get("model_slug") or md.get("default_model_slug"),
                "metadata": md,
                "time_index": time_indices.get(node_id),
                "message_kind": m_kind,
            }
            write_jsonl_line(writers["messages"], msg_row)
            stats["messages"] += 1

            # Links (from text)
            for idx, (url, start, end) in enumerate(extract_urls_from_text(text or "")):
                scheme, domain, path, query = parse_url(url)
                link_row = {
                    "run_id": run_id,
                    "id": f"msg_{msg_id}_{idx}",
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "source": "message_text",
                    "url": url,
                    "display_text": url,
                    "position_start": start,
                    "position_end": end,
                    "scheme": scheme,
                    "domain": domain,
                    "path": path,
                    "query": query,
                    "kind": None,
                    "metadata": {}
                }
                write_jsonl_line(writers["links"], link_row)
                stats["links"] += 1

            # Attachments (multimodal)
            if ctype == "multimodal_text":
                parts = content.get("parts") or []
                for idx, part in enumerate(parts):
                    if isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                        att_row = {
                            "run_id": run_id,
                            "id": str(uuid.uuid4()),
                            "conversation_id": conv_id,
                            "message_id": msg_id,
                            "type": "image",
                            "filename": None,
                            "mime_type": None,
                            "filesize_bytes": part.get("size_bytes"),
                            "source_ref": part.get("asset_pointer"),
                            "metadata": {
                                "width": part.get("width"),
                                "height": part.get("height"),
                                **(part.get("metadata") or {})
                            }
                        }
                        write_jsonl_line(writers["attachments"], att_row)
                        stats["attachments"] += 1

            # Tools (Calls & Results)
            if m_kind == "tool_call":
                 # Try to parse arguments
                raw_args = content.get("text")
                args_json = None
                try:
                    if raw_args: args_json = json.loads(raw_args)
                except:
                    pass
                
                tc_row = {
                    "run_id": run_id,
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "tool_name": recipient,
                    "call_index": 0,
                    "arguments_json": args_json,
                    "raw_arguments": raw_args,
                    "metadata": {}
                }
                write_jsonl_line(writers["tool_calls"], tc_row)
                stats["tool_calls"] += 1

            if m_kind == "tool_result":
                raw_res = content
                if content.get("content_type") == "execution_output":
                    raw_res = content.get("text")
                
                tr_row = {
                    "run_id": run_id,
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "tool_call_id": None, # Hard to link without more context
                    "result_json": None,
                    "raw_result": raw_res,
                    "metadata": {}
                }
                write_jsonl_line(writers["tool_results"], tr_row)
                stats["tool_results"] += 1

    # Conversation Row
    safe_urls = conv.get("safe_urls") or []
    blocked_urls = conv.get("blocked_urls") or []
    
    conv_row = {
        "run_id": run_id,
        "id": conv_id,
        "source_id": conv.get("conversation_id") or conv_id,
        "title": conv.get("title"),
        "created_at": iso_from_timestamp(conv.get("create_time")),
        "updated_at": iso_from_timestamp(conv.get("update_time")),
        "default_model": conv.get("default_model_slug"),
        "models_used": sorted(list(models_used)),
        "is_archived": conv.get("is_archived"),
        "is_starred": conv.get("is_starred"),
        "current_node_id": conv.get("current_node"),
        "message_count": message_count,
        "safe_url_count": len(safe_urls),
        "blocked_url_count": len(blocked_urls),
        "metadata": {
            "conversation_origin": conv.get("conversation_origin"),
            "is_do_not_remember": conv.get("is_do_not_remember"),
        },
        "source_file": source_file
    }
    write_jsonl_line(writers["conversations"], conv_row)
    stats["conversations"] += 1

    # Conv-level links
    for idx, url in enumerate(safe_urls):
        scheme, domain, path, query = parse_url(url)
        link_row = {
            "run_id": run_id,
            "id": f"safe_{conv_id}_{idx}",
            "conversation_id": conv_id,
            "message_id": None,
            "source": "safe_url",
            "url": url,
            "display_text": url,
            "position_start": None,
            "position_end": None,
            "scheme": scheme,
            "domain": domain,
            "path": path,
            "query": query,
            "kind": None,
            "metadata": {}
        }
        write_jsonl_line(writers["links"], link_row)
        stats["links"] += 1
