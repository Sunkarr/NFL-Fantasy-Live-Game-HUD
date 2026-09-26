#!/bin/bash

# We only care if we are pushing commits to a branch.
CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null)
if [ -z "$CURRENT_BRANCH" ]; then
    exit 0
fi

# We need to read stdin to see if we are actually pushing anything new.
has_commits_to_push=false
while read -r local_ref local_sha remote_ref remote_sha; do
    if [ "$local_ref" != "refs/heads/$CURRENT_BRANCH" ]; then
        continue
    fi
    if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi
    if [ "$local_sha" = "$remote_sha" ]; then
        continue
    fi
    has_commits_to_push=true
done

if [ "$has_commits_to_push" = false ]; then
    exit 0
fi

PARENT_PID=$PPID
REMOTE_NAME="${1:-origin}"

(
    # Wait for the parent git push process to exit
    while kill -0 $PARENT_PID 2>/dev/null; do
        sleep 0.2
    done
    
    # Check if the push succeeded by comparing local and remote SHA
    LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null)
    REMOTE_SHA=$(git rev-parse "${REMOTE_NAME}/${CURRENT_BRANCH}" 2>/dev/null)
    
    if [ -n "$LOCAL_SHA" ] && [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
        # Check if the last commit is already a version bump commit to avoid double-bumping
        LAST_COMMIT_MSG=$(git log -1 --pretty=%B 2>/dev/null)
        if [[ "$LAST_COMMIT_MSG" =~ ^chore:\ bump\ version\ to\ [0-9]+\.[0-9]+\.0 ]]; then
            exit 0
        fi
        
        # Increment version
        REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
        VERSION_FILE="${REPO_ROOT}/version.txt"
        
        if [ -f "$VERSION_FILE" ]; then
            VERSION_CONTENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')
        else
            VERSION_CONTENT="1.0.0"
        fi
        
        IFS='.' read -r MAJOR MIDDLE MINOR <<< "$VERSION_CONTENT"
        MAJOR=${MAJOR:-1}
        MIDDLE=${MIDDLE:-0}
        MINOR=${MINOR:-0}
        
        NEW_MIDDLE=$((MIDDLE + 1))
        NEW_MINOR=0
        NEW_VERSION="${MAJOR}.${NEW_MIDDLE}.${NEW_MINOR}"
        
        echo "${NEW_VERSION}" > "$VERSION_FILE"
        
        # Commit the version bump with SKIP_VERSION_BUMP=1 to avoid pre-commit bumping minor
        git add "$VERSION_FILE"
        if ! git diff --quiet --cached; then
            SKIP_VERSION_BUMP=1 git commit -m "chore: bump version to ${NEW_VERSION} [skip ci]"
        fi
    fi
) >/dev/null 2>&1 &
disown

exit 0
