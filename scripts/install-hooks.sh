#!/usr/bin/env bash
set -euo pipefail

if ! root=$(git rev-parse --show-toplevel 2>/dev/null); then
  echo "install-hooks: not inside a git repository; run it from a clone of this repository" >&2
  exit 2
fi

for hook in pre-commit pre-merge-commit commit-msg; do
  if [ ! -f "$root/.githooks/$hook" ] || [ ! -x "$root/.githooks/$hook" ]; then
    echo "install-hooks: .githooks/$hook is missing or not executable; core.hooksPath left unchanged" >&2
    exit 2
  fi
done

current=$(git -C "$root" config --local --get core.hooksPath || true)
if [ "$current" = ".githooks" ]; then
  echo "install-hooks: core.hooksPath already set to .githooks; nothing changed"
  exit 0
fi

git -C "$root" config --local core.hooksPath .githooks
if [ -n "$current" ]; then
  echo "install-hooks: warning: core.hooksPath was $current; the hooks there no longer run" >&2
fi
echo "install-hooks: core.hooksPath set to .githooks"
