#!/usr/bin/env bash
# Publish docs/wiki/*.md to the GitHub wiki (https://github.com/timainge/good-cop/wiki).
# GitHub creates the wiki's git repo only after its first page exists: open the wiki tab once,
# click "Create the first page", save anything, then run this. (Wikis on private repos need a paid plan.)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${1:-timainge/good-cop}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q "https://github.com/$REPO.wiki.git" "$TMP/wiki"
find docs/wiki -name "*.md" ! -name README.md -exec cp {} "$TMP/wiki/" \;
cd "$TMP/wiki"
git add -A
if git diff --cached --quiet; then echo "wiki already up to date"; exit 0; fi
git commit -qm "Update wiki from docs/wiki ($(git -C "$OLDPWD" rev-parse --short HEAD))"
git push -q
echo "published: https://github.com/$REPO/wiki"
