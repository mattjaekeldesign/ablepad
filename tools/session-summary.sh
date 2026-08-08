#!/usr/bin/env bash
set -euo pipefail

# Compact Git context for session summaries. State is kept in .git and is
# intentionally not part of the repository.
repo_root=$(git rev-parse --show-toplevel)
state_dir="$repo_root/.ablepad"
baseline_file="$state_dir/session-baseline"

usage() {
  echo "Usage: $0 [--start | --watch [seconds]]"
  echo "  --start  start a new tracking session at the current commit"
  echo "  --watch  keep running and print updates when Git changes (default: 240s)"
}

mode="once"
interval=240

if [[ "${1:-}" == "--start" ]]; then
  mkdir -p "$state_dir"
  git rev-parse HEAD > "$baseline_file"
  echo "Started session at $(git rev-parse --short HEAD)."
  exit 0
elif [[ "${1:-}" == "--watch" ]]; then
  mode="watch"
  if [[ -n "${2:-}" ]]; then
    interval="$2"
  fi
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$mode" == "once" && $# -gt 0 ]] || [[ "$mode" == "watch" && $# -gt 2 ]]; then
  usage >&2
  exit 2
fi

if ! [[ "$interval" =~ ^[1-9][0-9]*$ ]]; then
  echo "Watch interval must be a positive number of seconds." >&2
  exit 2
fi

if [[ ! -s "$baseline_file" ]]; then
  mkdir -p "$state_dir"
  git rev-parse HEAD > "$baseline_file"
  echo "Initialized session baseline at $(git rev-parse --short HEAD)."
  echo
fi

baseline=$(<"$baseline_file")
if ! git cat-file -e "$baseline^{commit}" 2>/dev/null; then
  echo "Session baseline is no longer a valid commit: $baseline" >&2
  echo "Run: $0 --start" >&2
  exit 1
fi

print_summary() {
  echo "Session baseline: $(git rev-parse --short "$baseline")"
  echo

  echo "COMMITS"
  if git diff --quiet "$baseline"..HEAD; then
    echo "  none"
  else
    git log --oneline --decorate "$baseline"..HEAD
  fi
  echo

  echo "WORKTREE SUMMARY"
  if [[ -z "$(git status --short)" ]]; then
    echo "  clean"
  else
    git diff --stat
    git diff --cached --stat
    untracked_count=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
    if [[ "$untracked_count" -gt 0 ]]; then
      echo "  Untracked paths: $untracked_count"
    fi
  fi
  echo

  echo "CHANGED PATHS"
  changed=$(git status --short)
  if [[ -n "$changed" ]]; then
    echo "$changed"
  else
    echo "  none"
  fi
}

print_summary

if [[ "$mode" == "watch" ]]; then
  echo
  echo "Watching every ${interval}s. Press Ctrl-C to stop."
  previous_snapshot=$(git rev-parse HEAD; git status --porcelain=v1)
  while true; do
    sleep "$interval"
    current_snapshot=$(git rev-parse HEAD; git status --porcelain=v1)
    if [[ "$current_snapshot" != "$previous_snapshot" ]]; then
      echo
      echo "--- Git update: $(date '+%Y-%m-%d %H:%M:%S') ---"
      print_summary
      previous_snapshot="$current_snapshot"
    fi
  done
fi
