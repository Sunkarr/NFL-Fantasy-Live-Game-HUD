#!/bin/bash

# Skip version bump if explicitly instructed (e.g. from pre-push hook)
if [ "$SKIP_VERSION_BUMP" = "1" ]; then
    exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
    exit 0
fi

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

NEW_MINOR=$((MINOR + 1))
NEW_VERSION="${MAJOR}.${MIDDLE}.${NEW_MINOR}"

echo "${NEW_VERSION}" > "$VERSION_FILE"
git add "$VERSION_FILE"
echo "🔖 Incremented commit version: ${VERSION_CONTENT} -> ${NEW_VERSION}"
exit 0
