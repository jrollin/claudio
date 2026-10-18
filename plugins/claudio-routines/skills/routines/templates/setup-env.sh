#!/bin/bash
repo={{runtime.repo}}
tag={{runtime.tag}}
sha={{runtime.sha}}
dir={{runtime.dir}}
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0

name=${dir%/}
case "${name##*/}" in
  claudio-runtime*) ;;
  *)
    echo "runtime dir refused: its last part must start with claudio-runtime" >&2
    exit 0
    ;;
esac

fail() {
  echo "$1" >&2
  rm -rf "$dir" 2>/dev/null
  exit 0
}

tmp=$(mktemp -d 2>/dev/null) || fail "runtime install failed"
trap 'rm -rf "$tmp"' EXIT
git -c credential.helper= -c advice.detachedHead=false \
  clone --quiet --depth 1 --branch "$tag" "$repo" "$tmp/claudio" 2>/dev/null || fail "runtime clone failed"
head=$(git -C "$tmp/claudio" rev-parse HEAD 2>/dev/null) || fail "runtime clone failed"
[ "$head" = "$sha" ] || fail "runtime hash mismatch"
mkdir -p "$(dirname "$dir")" 2>/dev/null || fail "runtime install failed"
rm -rf "$dir" 2>/dev/null || fail "runtime install failed"
mv "$tmp/claudio" "$dir" 2>/dev/null || fail "runtime install failed"
exit 0
