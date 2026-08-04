#!/usr/bin/env bash
# setup.sh — resolve/bootstrap Python interpreter cho pdf-translate-layout.
# Hợp đồng (SKILL.md §8): mọi agent (Claude Code / Codex / Antigravity) chạy script này
# để lấy interpreter; dòng stdout cuối cùng luôn là `PYTHON=<path>` khi thành công.
#
# Usage:
#   bash scripts/setup.sh            # resolve; tự tạo .venv trong skill folder nếu chưa có env hợp lệ
#   bash scripts/setup.sh --check    # chỉ kiểm tra, không cài gì (exit 3 nếu không có env hợp lệ)
#   bash scripts/setup.sh --force    # tạo lại .venv từ đầu
#
# Thứ tự ưu tiên: $PDFTL_PYTHON > <skill>/.venv > python hệ thống thỏa pin (3.12/3.11/3.10/python3).
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ="$SKILL_ROOT/requirements.txt"
VENV="$SKILL_ROOT/.venv"
PIN_PYMUPDF="$(sed -n 's/^pymupdf==//p' "$REQ" | head -1)"

log() { echo "[setup] $*" >&2; }

# Env hợp lệ = Python >= 3.10 + import đủ deps + pymupdf đúng pin (fail-closed như engine).
valid() {
  local py="$1"
  [ -n "$py" ] && [ -x "$py" ] || command -v "$py" >/dev/null 2>&1 || return 1
  "$py" - "$PIN_PYMUPDF" <<'EOF' >/dev/null 2>&1
import sys
assert sys.version_info >= (3, 10)
import pymupdf, yaml, numpy, PIL
assert pymupdf.version[0] == sys.argv[1]
EOF
}

resolve() {
  local candidates=()
  [ -n "${PDFTL_PYTHON:-}" ] && candidates+=("$PDFTL_PYTHON")
  candidates+=("$VENV/bin/python3")
  for c in python3.12 python3.11 python3.10 python3; do
    p="$(command -v "$c" 2>/dev/null || true)"
    [ -n "$p" ] && candidates+=("$p")
  done
  for py in "${candidates[@]}"; do
    if valid "$py"; then echo "$py"; return 0; fi
  done
  return 1
}

MODE="${1:-}"

if [ "$MODE" != "--force" ]; then
  if PY="$(resolve)"; then
    log "env hợp lệ: $PY (pymupdf==$PIN_PYMUPDF)"
    echo "PYTHON=$PY"
    exit 0
  fi
  if [ "$MODE" = "--check" ]; then
    log "không có env hợp lệ. Chạy: bash scripts/setup.sh (cần network 1 lần để cài deps)"
    exit 3
  fi
fi

# Bootstrap .venv — chọn base python >= 3.10 để tạo venv.
BASE=""
for c in python3.12 python3.11 python3.10 python3; do
  p="$(command -v "$c" 2>/dev/null || true)"
  [ -n "$p" ] && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null && BASE="$p" && break
done
[ -n "$BASE" ] || { log "LỖI: không tìm thấy Python >= 3.10 trên hệ thống"; exit 2; }

log "tạo venv tại $VENV (base: $BASE)"
rm -rf "$VENV"
"$BASE" -m venv "$VENV"
"$VENV/bin/python3" -m pip install --quiet --upgrade pip
"$VENV/bin/python3" -m pip install --quiet -r "$REQ"

if valid "$VENV/bin/python3"; then
  log "venv sẵn sàng"
  echo "PYTHON=$VENV/bin/python3"
else
  log "LỖI: venv cài xong nhưng không pass validation (xem requirements.txt)"
  exit 2
fi
