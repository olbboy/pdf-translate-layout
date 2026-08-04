#!/usr/bin/env bash
# install.sh — đăng ký skill vào các vị trí discovery của Claude Code / Codex / Antigravity.
# Mặc định symlink (không copy dữ liệu); tool không theo symlink thì dùng --copy.
#
# Usage:
#   bash scripts/install.sh repo     # symlink vào <git root>/.agents/skills + .claude/skills
#   bash scripts/install.sh global   # symlink vào ~/.agents/skills (Codex), ~/.claude/skills
#                                    # (Claude Code), ~/.gemini/config/skills (Antigravity)
#   bash scripts/install.sh status   # xem trạng thái các vị trí
#   ... repo|global --copy           # copy thay vì symlink (loại trừ jobs/, .venv/, __pycache__/)
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="$(basename "$SKILL_ROOT")"
MODE="${1:-status}"
COPY="${2:-}"

log() { echo "[install] $*" >&2; }

repo_targets() {
  local root
  root="$(git -C "$SKILL_ROOT" rev-parse --show-toplevel 2>/dev/null)" || return 1
  echo "$root/.agents/skills/$NAME"
  echo "$root/.claude/skills/$NAME"
}

global_targets() {
  echo "$HOME/.agents/skills/$NAME"
  echo "$HOME/.claude/skills/$NAME"
  echo "$HOME/.gemini/config/skills/$NAME"
}

install_one() {
  # $2 = "relative": symlink tương đối (repo-level — commit được, không leak path máy local).
  local target="$1" style="${2:-absolute}" parent src
  parent="$(dirname "$target")"
  mkdir -p "$parent"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    log "SKIP $target — đã tồn tại và không phải symlink (không ghi đè)"
    return 0
  fi
  if [ "$COPY" = "--copy" ]; then
    rm -f "$target"
    rsync -a --exclude jobs/ --exclude .venv/ --exclude __pycache__/ "$SKILL_ROOT/" "$target/"
    log "COPIED $target"
    return 0
  fi
  src="$SKILL_ROOT"
  if [ "$style" = "relative" ]; then
    src="$(python3 -c 'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
      "$SKILL_ROOT" "$parent")"
  fi
  ln -sfn "$src" "$target"
  log "LINKED $target -> $src"
}

status_one() {
  local target="$1"
  if [ -L "$target" ]; then
    if [ -f "$target/SKILL.md" ]; then echo "  OK (symlink) $target"; else echo "  BROKEN link  $target"; fi
  elif [ -f "$target/SKILL.md" ]; then echo "  OK (copy)    $target"
  else echo "  chưa cài     $target"; fi
}

case "$MODE" in
  repo)
    repo_targets >/dev/null || { log "LỖI: skill không nằm trong git repo"; exit 2; }
    while IFS= read -r t; do install_one "$t" relative; done < <(repo_targets)
    ;;
  global)
    while IFS= read -r t; do install_one "$t"; done < <(global_targets)
    ;;
  status)
    echo "Repo-level:";   repo_targets 2>/dev/null | while IFS= read -r t; do status_one "$t"; done || echo "  (không trong git repo)"
    echo "Global-level:"; global_targets | while IFS= read -r t; do status_one "$t"; done
    ;;
  *)
    log "usage: install.sh repo|global|status [--copy]"; exit 1;;
esac
