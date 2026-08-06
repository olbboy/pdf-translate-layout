#!/usr/bin/env bash
# Khoá/mở/kiểm engine của skill pdf-translate-layout trước và sau khi giao việc cho agent.
#
# Vì sao cần: sự cố 2026-08-05 — Antigravity sửa scripts/approve.py, đổi hai chốt chặn
# human-approval thành `if False:` rồi tự approve và phát hành. Mọi hàng rào viết bằng
# Python nằm trong cây thư mục agent ghi được đều là hàng rào tự nguyện. Quyền ghi của
# filesystem thì không.
#
# Dùng:
#   ./lock-engine.sh lock     # trước khi mở agent
#   ./lock-engine.sh verify   # sau khi agent chạy xong — PHẢI chạy trước khi tin kết quả
#   ./lock-engine.sh unlock   # khi chính mình cần sửa engine
#
# Job folder nằm ở repo tài liệu, không nằm trong engine. Trỏ PDFTL_JOBS vào đó để bật
# thêm bước dò file .py lạ do agent tự sinh trong job:
#   PDFTL_JOBS="/path/to/translation/jobs" ./lock-engine.sh verify
set -euo pipefail

SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$SKILL/.engine-manifest.sha256"
JOBS="${PDFTL_JOBS:-}"

# Vùng agent KHÔNG được ghi. jobs/ cố ý không nằm ở đây — agent phải ghi được job của nó.
PROTECTED=("$SKILL/scripts" "$SKILL/assets" "$SKILL/SKILL.md")

# Hash theo đường dẫn TƯƠNG ĐỐI so với skill root — manifest không đổi khi engine
# được di chuyển hoặc clone về máy khác.
manifest_now() {
    (
        cd "$SKILL"
        find scripts assets -type f \( -name '*.py' -o -name '*.yaml' -o -name '*.csv' -o -name '*.sh' \) \
            -not -path '*/__pycache__/*' -print0 2>/dev/null \
            | sort -z | xargs -0 shasum -a 256
        shasum -a 256 SKILL.md
    )
}

case "${1:-}" in
lock)
    manifest_now > "$MANIFEST"
    for p in "${PROTECTED[@]}"; do chmod -R a-w "$p"; done
    echo "khoá: $(wc -l < "$MANIFEST" | tr -d ' ') file engine → chỉ đọc"
    echo "manifest: $MANIFEST"
    ;;
unlock)
    for p in "${PROTECTED[@]}"; do chmod -R u+w "$p"; done
    echo "mở khoá — nhớ chạy lại 'lock' trước khi giao việc cho agent"
    ;;
verify)
    fail=0
    if [ ! -f "$MANIFEST" ]; then
        echo "THIẾU manifest — chưa từng chạy 'lock'. Không kết luận được gì."; exit 2
    fi
    if ! diff -q <(manifest_now) "$MANIFEST" > /dev/null; then
        echo "FAIL: file engine đã đổi so với lúc khoá:"
        # cắt 66 ký tự đầu = sha256 + 2 dấu cách; đường dẫn có khoảng trắng nên không awk được
        diff <(manifest_now) "$MANIFEST" | grep '^<' | cut -c 68- | sed 's/^/  /'
        fail=1
    fi
    if git -C "$SKILL" rev-parse --show-toplevel >/dev/null 2>&1; then
        dirty=$(git -C "$SKILL" status --porcelain -- scripts assets SKILL.md)
        if [ -n "$dirty" ]; then
            echo "FAIL: git thấy engine bẩn:"; echo "$dirty" | sed 's/^/  /'; fail=1
        fi
    else
        echo "CẢNH BÁO: engine không nằm trong git repo — bỏ qua bước đối chiếu git"
    fi
    # File .py lạ trong job = dấu hiệu agent sinh code dịch (SKILL.md §1.6)
    # check_fit.py: helper chỉ-đọc do người cài sẵn vào job (round 4), không phải agent sinh
    if [ -n "$JOBS" ] && [ -d "$JOBS" ]; then
        stray=$(find "$JOBS" -name '*.py' -newer "$MANIFEST" \
            -not -name 'dump_requests.py' -not -name 'write_responses.py' \
            -not -name 'check_fit.py' 2>/dev/null || true)
        if [ -n "$stray" ]; then
            echo "CẢNH BÁO: file .py lạ trong jobs/ (agent tự sinh?):"
            echo "$stray" | sed "s|$JOBS/|  |"
        fi
    fi
    [ "$fail" -eq 0 ] && echo "OK: engine nguyên vẹn" || exit 1
    ;;
*)
    echo "dùng: $0 {lock|verify|unlock}" >&2; exit 2
    ;;
esac
