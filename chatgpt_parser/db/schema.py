from ..config import CURRENT_SCHEMA_VERSION

CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        jsonl_dir TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        input_files TEXT, -- JSON list
        stats TEXT        -- JSON object
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        source_id TEXT,
        title TEXT,
        created_at TEXT,
        updated_at TEXT,
        default_model TEXT,
        models_used TEXT, -- JSON list
        is_archived BOOLEAN,
        is_starred BOOLEAN,
        current_node_id TEXT,
        message_count INTEGER,
        safe_url_count INTEGER,
        blocked_url_count INTEGER,
        metadata TEXT,    -- JSON object
        source_file TEXT,
        PRIMARY KEY (run_id, id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        parent_id TEXT,
        children_ids TEXT, -- JSON list
        message_id TEXT,
        is_root BOOLEAN,
        is_in_main_path BOOLEAN,
        depth INTEGER,
        main_path_index INTEGER,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS node_children (
        run_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        parent_node_id TEXT NOT NULL,
        child_node_id TEXT NOT NULL,
        child_index INTEGER NOT NULL,
        PRIMARY KEY (run_id, parent_node_id, child_index),
        UNIQUE (run_id, parent_node_id, child_node_id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, parent_node_id)
            REFERENCES nodes(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, child_node_id)
            REFERENCES nodes(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        node_id TEXT,
        conversation_id TEXT NOT NULL,
        role TEXT,
        author_name TEXT,
        recipient TEXT,
        channel TEXT,
        content_type TEXT,
        text TEXT,
        raw_content TEXT, -- JSON object
        created_at TEXT,
        updated_at TEXT,
        is_hidden BOOLEAN,
        hidden_reason TEXT,
        is_in_main_path BOOLEAN,
        main_path_index INTEGER,
        depth INTEGER,
        model TEXT,
        metadata TEXT,    -- JSON object
        time_index INTEGER,
        message_kind TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, node_id)
            REFERENCES nodes(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS links (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
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
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS attachments (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        type TEXT,
        filename TEXT,
        mime_type TEXT,
        filesize_bytes INTEGER,
        source_ref TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        tool_name TEXT,
        call_index INTEGER,
        arguments_json TEXT, -- JSON object
        raw_arguments TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_results (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        tool_call_id TEXT,
        result_json TEXT, -- JSON object
        raw_result TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, tool_call_id)
            REFERENCES tool_calls(run_id, id)
            ON DELETE CASCADE
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
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # Indices for performance
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(run_id, conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_nodes_conv ON nodes(run_id, conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_kind ON messages(run_id, message_kind);",
    "CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(run_id, conversation_id, time_index);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_parent ON node_children(run_id, parent_node_id);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_child ON node_children(run_id, child_node_id);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_conv ON node_children(run_id, conversation_id);",
]
