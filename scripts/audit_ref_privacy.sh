#!/bin/bash

set -euo pipefail

candidate_ref="${1:-HEAD}"
candidate_commit=$(git rev-parse --verify "${candidate_ref}^{commit}")
approved_database="demo/demo_chatgpt_export.db"
approved_export="demo/demo_conversations.json"
approved_normalized_prefix="demo/normalized_runs/demo_run/"
failed=0

shopt -s nocasematch
while IFS= read -r -d '' record; do
    metadata=${record%%$'\t'*}
    path=${record#*$'\t'}
    size=${metadata##* }

    case "$path" in
        "$approved_database"|"$approved_export"|"$approved_normalized_prefix"*)
            ;;
        *.db|*.db-wal|*.db-shm|*.sqlite|*.sqlite-wal|*.sqlite-shm|*.sqlite3|*.sqlite3-wal|*.sqlite3-shm|*.zip|*.tar|*.tar.gz|*.tgz|*/conversations.json|conversations.json|*/chat.html|chat.html|*/user.json|user.json|*/message_feedback.json|message_feedback.json|*/model_comparisons.json|model_comparisons.json|*/shared_conversations.json|shared_conversations.json|*/normalized_runs/*|*/attachments/*|exports/*)
            echo "Forbidden private-data-shaped path is reachable from $candidate_ref: $path" >&2
            failed=1
            ;;
    esac

    if [[ "$size" =~ ^[0-9]+$ ]] && (( size > 2097152 )); then
        echo "Reachable blob exceeds the 2 MiB privacy-review threshold: $path ($size bytes)" >&2
        failed=1
    fi
done < <(git ls-tree -r -l -z "$candidate_commit")

if git grep -I -n -E '(/Users/|/home/|/private/var/folders|/var/folders)' "$candidate_commit" -- . ':!scripts/check_repository_privacy.sh' ':!scripts/audit_ref_privacy.sh'; then
    echo "Reachable text contains an absolute local-user path." >&2
    failed=1
fi

if git grep -I -n -E '@(gmail|outlook|hotmail|yahoo|icloud|protonmail)\.' "$candidate_commit" -- .; then
    echo "Reachable text contains a personal-email-provider address." >&2
    failed=1
fi

if git show-ref --verify --quiet refs/heads/legacy-main \
   && git merge-base --is-ancestor refs/heads/legacy-main "$candidate_commit"; then
    echo "legacy-main is an ancestor of $candidate_ref; publication is forbidden." >&2
    failed=1
fi

if (( failed != 0 )); then
    exit 1
fi

echo "Ref privacy audit passed for $candidate_ref ($candidate_commit)."
