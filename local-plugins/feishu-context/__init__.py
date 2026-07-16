"""Read-only contextual retrieval for locally archived Feishu group messages."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import tool_error, tool_result


_GROUP_SESSION_RE = re.compile(r"(?:^|:)feishu:group:(oc_[^:]+)")
_MAX_LIMIT = 30
_MAX_CONTENT_CHARS = 1_200

FEISHU_CONTEXT_SEARCH_SCHEMA = {
    "name": "feishu_context_search",
    "description": (
        "Search archived messages from the current Feishu group only. Use this when "
        "the current request needs prior group context. It cannot access other groups."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword or phrase to find in archived message content.",
            },
            "after": {
                "type": "string",
                "description": "Optional inclusive ISO-8601 received_at lower bound.",
            },
            "before": {
                "type": "string",
                "description": "Optional exclusive ISO-8601 received_at upper bound.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of messages to return, from 1 to 30. Defaults to 12.",
            },
            "include_attachments": {
                "type": "boolean",
                "description": "Include archived attachment metadata and local paths. Defaults to true.",
            },
        },
    },
}


def _check_archive_available() -> bool:
    return (get_hermes_home() / "feishu_messages.db").is_file()


def _current_group_chat_id(session_id: str) -> str:
    match = _GROUP_SESSION_RE.search(session_id or "")
    return match.group(1) if match else ""


def _limit(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 12
    return max(1, min(value, _MAX_LIMIT))


def _short_content(value: Any) -> str:
    text = str(value or "")
    if len(text) <= _MAX_CONTENT_CHARS:
        return text
    return text[:_MAX_CONTENT_CHARS] + "... [truncated]"


def _search_current_group(args: dict, *, session_id: str = "", **_: Any) -> str:
    chat_id = _current_group_chat_id(session_id)
    if not chat_id:
        return tool_error("feishu_context_search is available only from a Feishu group conversation.")

    archive_path = get_hermes_home() / "feishu_messages.db"
    if not archive_path.is_file():
        return tool_error("No Feishu archive database exists yet.")

    query = str(args.get("query") or "").strip()
    after = str(args.get("after") or "").strip()
    before = str(args.get("before") or "").strip()
    include_attachments = args.get("include_attachments", True) is not False
    sql = [
        "SELECT message_id, received_at, create_time, sender_open_id, message_type, content, mentioned_bot",
        "FROM feishu_messages",
        "WHERE chat_id = ?",
    ]
    params: list[Any] = [chat_id]
    if query:
        sql.append("AND content LIKE ?")
        params.append(f"%{query}%")
    if after:
        sql.append("AND received_at >= ?")
        params.append(after)
    if before:
        sql.append("AND received_at < ?")
        params.append(before)
    sql.append("ORDER BY received_at DESC LIMIT ?")
    params.append(_limit(args.get("limit")))

    try:
        uri = f"file:{archive_path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = list(conn.execute(" ".join(sql), params))
            message_ids = [str(row["message_id"]) for row in rows]
            attachments_by_message: dict[str, list[dict[str, Any]]] = {}
            attachments_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'feishu_attachments'"
            ).fetchone()
            if include_attachments and attachments_table and message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                attachment_sql = (
                    "SELECT message_id, resource_type, original_name, mime_type, local_path, "
                    "file_size, download_status, download_error "
                    f"FROM feishu_attachments WHERE message_id IN ({placeholders}) "
                    "ORDER BY message_id, attachment_index"
                )
                for attachment in conn.execute(attachment_sql, message_ids):
                    item = dict(attachment)
                    attachments_by_message.setdefault(str(item.pop("message_id")), []).append(item)
    except sqlite3.Error as exc:
        return tool_error(f"Could not query the Feishu archive: {exc}")

    messages = []
    for row in reversed(rows):
        item = dict(row)
        item["content"] = _short_content(item.get("content"))
        if include_attachments:
            item["attachments"] = attachments_by_message.get(str(item["message_id"]), [])
        messages.append(item)
    return tool_result(
        {
            "success": True,
            "chat_id": chat_id,
            "count": len(messages),
            "messages": messages,
        }
    )


def register(ctx) -> None:
    ctx.register_tool(
        name="feishu_context_search",
        toolset="feishu_context",
        schema=FEISHU_CONTEXT_SEARCH_SCHEMA,
        handler=_search_current_group,
        check_fn=_check_archive_available,
        emoji="🗂️",
    )
