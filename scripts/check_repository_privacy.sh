#!/bin/bash

set -euo pipefail

approved_database="demo/demo_chatgpt_export.db"
approved_export="demo/demo_conversations.json"
approved_normalized_prefix="demo/normalized_runs/demo_run/"
failed=0

shopt -s nocasematch
while IFS= read -r -d '' path; do
    [[ -f "$path" ]] || continue

    case "$path" in
        "$approved_database"|"$approved_export"|"$approved_normalized_prefix"*)
            ;;
        *.db|*.db-wal|*.db-shm|*.sqlite|*.sqlite-wal|*.sqlite-shm|*.sqlite3|*.sqlite3-wal|*.sqlite3-shm|*.zip|*.tar|*.tar.gz|*.tgz|*/conversations.json|conversations.json|*/chat.html|chat.html|*/user.json|user.json|*/message_feedback.json|message_feedback.json|*/model_comparisons.json|model_comparisons.json|*/shared_conversations.json|shared_conversations.json|*/normalized_runs/*|*/attachments/*)
            echo "Forbidden private-data-shaped file is tracked: $path" >&2
            failed=1
            ;;
    esac

    size=$(wc -c < "$path")
    if (( size > 2097152 )); then
        echo "Tracked file exceeds the 2 MiB privacy-review threshold: $path ($size bytes)" >&2
        failed=1
    fi
done < <(git ls-files -z)

if git grep -I -n -E '(/Users/|/home/|/private/var/folders|/var/folders)' -- . ':!scripts/check_repository_privacy.sh'; then
    echo "Tracked text contains an absolute local-user path." >&2
    failed=1
fi

if git grep -I -n -E '@(gmail|outlook|hotmail|yahoo|icloud|protonmail)\.' -- .; then
    echo "Tracked text contains a personal-email-provider address." >&2
    failed=1
fi

integrity=$(sqlite3 "$approved_database" 'PRAGMA integrity_check;')
conversation_count=$(sqlite3 "$approved_database" 'SELECT count(*) FROM conversations;')
message_count=$(sqlite3 "$approved_database" 'SELECT count(*) FROM messages;')
non_demo_count=$(sqlite3 "$approved_database" "SELECT count(*) FROM conversations WHERE id NOT LIKE 'demo_%';")

if [[ "$integrity" != "ok" || "$conversation_count" != "2" || "$message_count" != "5" || "$non_demo_count" != "0" ]]; then
    echo "The approved parser database no longer matches its synthetic fixture contract." >&2
    failed=1
fi

if (( failed != 0 )); then
    exit 1
fi

echo "Parser privacy guard passed: only the approved synthetic demo archive is tracked."
