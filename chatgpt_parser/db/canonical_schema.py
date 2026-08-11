"""
ChatGPT Canonical Archive Schema v2

This is a canonicalized evolution of the original ChatGPT full relational DB.
It preserves the ChatGPT-native tables AtlasBench expects while moving run
provenance out of primary keys and into dedicated snapshot/provenance tables.
"""

CANONICAL_SCHEMA_VERSION = 2

CANONICAL_TABLES_SQL = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA foreign_keys = ON;",

    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        input_files TEXT,
        stats TEXT
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        run_id TEXT,
        source_id TEXT,
        title TEXT,
        created_at TEXT,
        updated_at TEXT,
        earliest_message_at TEXT,
        latest_message_at TEXT,
        default_model TEXT,
        models_used TEXT,
        is_archived BOOLEAN,
        is_starred BOOLEAN,
        current_node_id TEXT,
        message_count INTEGER,
        message_count_main_path INTEGER NOT NULL DEFAULT 0,
        user_message_count INTEGER NOT NULL DEFAULT 0,
        assistant_message_count INTEGER NOT NULL DEFAULT 0,
        system_message_count INTEGER NOT NULL DEFAULT 0,
        tool_message_count INTEGER NOT NULL DEFAULT 0,
        safe_url_count INTEGER,
        blocked_url_count INTEGER,
        keyword_text TEXT,
        summary_text TEXT,
        metadata TEXT,
        source_file TEXT,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS conversation_runs (
        run_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        title TEXT,
        created_at TEXT,
        updated_at TEXT,
        earliest_message_at TEXT,
        latest_message_at TEXT,
        default_model TEXT,
        models_used TEXT,
        is_archived BOOLEAN,
        is_starred BOOLEAN,
        current_node_id TEXT,
        message_count INTEGER,
        message_count_main_path INTEGER NOT NULL DEFAULT 0,
        user_message_count INTEGER NOT NULL DEFAULT 0,
        assistant_message_count INTEGER NOT NULL DEFAULT 0,
        system_message_count INTEGER NOT NULL DEFAULT 0,
        tool_message_count INTEGER NOT NULL DEFAULT 0,
        safe_url_count INTEGER,
        blocked_url_count INTEGER,
        keyword_text TEXT,
        summary_text TEXT,
        metadata TEXT,
        source_file TEXT,
        imported_at TEXT NOT NULL,
        is_canonical_snapshot BOOLEAN NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, conversation_id),
        FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS nodes (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        parent_id TEXT,
        children_ids TEXT,
        message_id TEXT,
        is_root BOOLEAN,
        is_in_main_path BOOLEAN,
        depth INTEGER,
        main_path_index INTEGER,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS node_children (
        conversation_id TEXT NOT NULL,
        parent_node_id TEXT NOT NULL,
        child_node_id TEXT NOT NULL,
        child_index INTEGER NOT NULL,
        run_id TEXT,
        PRIMARY KEY (conversation_id, parent_node_id, child_index),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS messages (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        node_id TEXT,
        role TEXT,
        author_name TEXT,
        recipient TEXT,
        channel TEXT,
        content_type TEXT,
        text TEXT,
        raw_content TEXT,
        created_at TEXT,
        updated_at TEXT,
        is_hidden BOOLEAN,
        hidden_reason TEXT,
        is_in_main_path BOOLEAN,
        main_path_index INTEGER,
        depth INTEGER,
        model TEXT,
        metadata TEXT,
        time_index INTEGER,
        message_kind TEXT,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS message_runs (
        run_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        PRIMARY KEY (run_id, conversation_id, message_id),
        FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
        FOREIGN KEY (conversation_id, message_id)
            REFERENCES messages(conversation_id, id)
            ON DELETE CASCADE
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS links (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        message_id TEXT,
        source TEXT,
        url TEXT,
        display_text TEXT,
        position_start INTEGER,
        position_end INTEGER,
        scheme TEXT,
        domain TEXT,
        path TEXT,
        query TEXT,
        kind TEXT,
        metadata TEXT,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS attachments (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        message_id TEXT,
        type TEXT,
        filename TEXT,
        mime_type TEXT,
        filesize_bytes INTEGER,
        source_ref TEXT,
        metadata TEXT,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        message_id TEXT,
        tool_name TEXT,
        call_index INTEGER,
        arguments_json TEXT,
        raw_arguments TEXT,
        metadata TEXT,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS tool_results (
        conversation_id TEXT NOT NULL,
        id TEXT NOT NULL,
        run_id TEXT,
        message_id TEXT,
        tool_call_id TEXT,
        result_json TEXT,
        raw_result TEXT,
        metadata TEXT,
        PRIMARY KEY (conversation_id, id),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,

    """
    CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
        message_id UNINDEXED,
        conversation_id UNINDEXED,
        run_id UNINDEXED,
        role,
        text,
        tokenize='unicode61'
    );
    """,

    "CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);",
    "CREATE INDEX IF NOT EXISTS idx_conversations_latest_message ON conversations(latest_message_at);",
    "CREATE INDEX IF NOT EXISTS idx_conversation_runs_conversation ON conversation_runs(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_conversation_runs_imported ON conversation_runs(imported_at);",
    "CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(conversation_id, parent_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(conversation_id, time_index);",
    "CREATE INDEX IF NOT EXISTS idx_messages_kind ON messages(message_kind);",
    "CREATE INDEX IF NOT EXISTS idx_links_domain ON links(domain);",
]
