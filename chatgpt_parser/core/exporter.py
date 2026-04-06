import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from ..db.common import connect_db

def format_messages_markdown(conv: Dict[str, Any],
                             messages: List[Dict[str, Any]],
                             anchor: Optional[str] = None,
                             frontmatter: bool = False) -> str:
    """Render a conversation + messages into reasonably readable Markdown."""
    title = conv.get("title") or conv.get("id") or "Conversation"
    fm_lines = []
    if frontmatter:
        safe_title = (title or "").replace('"', '\"')
        fm_lines.append("---")
        fm_lines.append(f'title: "{safe_title}"')
        fm_lines.append(f'conversation_id: "{conv.get("id")}"')
        if conv.get("created_at"):
            fm_lines.append(f'created_at: "{conv.get("created_at")}"')
        fm_lines.append("tags: [chatgpt_export]")
        fm_lines.append("---")
        fm_lines.append("")

    lines = []
    if anchor:
        lines.append(f"<a id=\"{anchor}\"></a>")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Conversation ID: `{conv.get('id')}`")
    if conv.get("created_at"):
        lines.append(f"- Created at: {conv.get('created_at')}")
    lines.append("")

    for idx, msg in enumerate(messages, start=1):
        role = msg.get("role") or "unknown"
        header = f"## {idx}. {role}"
        if msg.get("created_at"):
            header += f" @ {msg['created_at']}"
        lines.append(header)
        if msg.get("message_kind"):
            lines.append(f"*kind:* `{msg['message_kind']}`")
        if msg.get("model"):
            lines.append(f"*model:* `{msg['model']}`")
        lines.append("")

        text = msg.get("text") or ""
        lines.append("```")
        lines.append(text)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(fm_lines + lines)


def run_export_conversation(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM conversations WHERE id = ?", (args.conversation_id,))
    conv = cur.fetchone()
    if not conv:
        logger.error("Conversation not found")
        return

    include_hidden = str(getattr(args, "include_hidden", "false")).lower() == "true"
    sql = "SELECT * FROM messages WHERE conversation_id = ?"
    params = [args.conversation_id]
    if not include_hidden:
        sql += " AND (is_hidden IS NULL OR is_hidden = 0)"
    sql += " ORDER BY time_index ASC"
    cur.execute(sql, params)
    messages = [dict(r) for r in cur.fetchall()]
    conv_dict = dict(conv)
    conn.close()

    if args.format == "json":
        content = json.dumps({"conversation": conv_dict, "messages": messages}, indent=2, default=str)
    else:
        fm = getattr(args, "frontmatter", False)
        content = format_messages_markdown(conv_dict, messages, frontmatter=fm)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote conversation to {args.output}")
    else:
        print(content)
