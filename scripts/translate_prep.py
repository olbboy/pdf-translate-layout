"""Stage 3 — Translate-prep: action classifier, protected tokens, batch requests.

Spec §5.6, §6.5-6.6. Output: translation/requests.jsonl, translation/batches.json,
translation/AGENT_INSTRUCTIONS.md; cập nhật action vào model/regions.json.
Chạy: python3 translate_prep.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import math
import re

from _common import (BlockingError, Job, append_jsonl, exit_blocking, load_glossary,
                     load_json, make_issue, nfc, save_json, utc_now)

STAGE = "translate_prep"
PH = "⟦{}⟧"  # ⟦TOKEN⟧
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")

NUMERIC_RE = re.compile(r"^[\d\s.,:/×xX+\-±%()~]+$")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s⟦⟧]+")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
STD_RE = re.compile(r"\b(?:IEC|UL|EN|ISO|CE|FCC|RoHS)\s?-?\d[\w.-]*\b")
MEAS_RE = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)?\s?(?:°C|°F|mm2|mm²|mm|cm|kWh|Wh|mAh|Ah|Hz|Nm|AWG|kg|kW|V|A|W|m|g|%))(?![\w])")
MODEL_RE = re.compile(r"\b(?:[A-Z]{1,4}\d+[A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|Ø\s?\d+(?:mm)?)\b")


def protect(text: str, keep_terms: list[str]) -> tuple[str, dict]:
    """Thay typed tokens bằng placeholder ⟦TYPE_N⟧ (spec §6.5). Trả (masked, map)."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    def sub_all(pattern: re.Pattern, ttype: str, s: str) -> str:
        def repl(m):
            counters[ttype] = counters.get(ttype, 0) + 1
            token = f"{ttype}_{counters[ttype]}"
            mapping[token] = m.group(0)
            return PH.format(token)
        return pattern.sub(repl, s)

    masked = sub_all(URL_RE, "URL", text)
    masked = sub_all(EMAIL_RE, "EMAIL", masked)
    if keep_terms:
        brand_re = re.compile(
            "(?<![A-Za-z0-9])(?:" +
            "|".join(re.escape(t) for t in sorted(keep_terms, key=len, reverse=True)) +
            ")(?![A-Za-z0-9])")
        masked = sub_all(brand_re, "BRAND", masked)
    masked = sub_all(STD_RE, "STD", masked)
    masked = sub_all(MEAS_RE, "MEAS", masked)
    masked = sub_all(MODEL_RE, "MODEL", masked)
    return masked, mapping


def restore(text: str, mapping: dict) -> str:
    return PH_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), text)


def classify_action(reg: dict, keep_terms_ci: set, mapping_len: int, masked: str) -> tuple[str, str]:
    """→ (action, keep_class). spec §5.6: translate|keep|manual (delete chỉ do reviewer)."""
    t = reg["source_text"].strip()
    if reg["rotation"] == -1:
        return "manual", "arbitrary_angle"
    if not t:
        return "keep", "empty"
    if NUMERIC_RE.match(t):
        return "keep", "numeric"
    if t.lower() in keep_terms_ci:
        return "keep", "glossary_term"
    residual = PH_RE.sub("", masked).strip(" \n\t:;,.()[]-–—/&+")
    if mapping_len and not residual:
        return "keep", "protected_only"
    return "translate", ""


def prep(job: Job) -> None:
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json — chạy extract_group trước")
    regions = model["regions"]
    by_id = {r["region_id"]: r for r in regions}
    cfg = job.config
    glossary = load_glossary(job)
    keep_terms = [g["term"] for g in glossary if g["type"] == "keep"]
    keep_terms_ci = {t.lower() for t in keep_terms}
    prefer = [g for g in glossary if g["type"] == "prefer"]
    issues: list[dict] = []

    domain_context = ""
    ctx_path = job.p("input", "domain_context.md")
    import os
    if os.path.exists(ctx_path):
        domain_context = open(ctx_path, encoding="utf-8").read()
    if cfg["policy"]["require_domain_context"] and not domain_context:
        raise BlockingError("DOMAIN_CONTEXT_MISSING ở chế độ customer-facing — bổ sung rồi chạy lại")

    req_path = job.p("translation", "requests.jsonl")
    open(req_path, "w").close()  # idempotent re-run: ghi lại từ đầu

    # heading gần nhất theo reading order từng trang
    last_heading: dict[int, str] = {}
    n_requests = 0
    batches: list[dict] = []
    cur_batch: list[str] = []
    cur_page = None
    max_batch = cfg["translation"]["batch_max_regions"]

    def flush_batch():
        nonlocal cur_batch
        if cur_batch:
            batches.append({"batch_id": f"b{len(batches)+1:03d}", "region_ids": cur_batch})
            cur_batch = []

    for reg in regions:
        src = nfc(reg["source_text"])
        masked, mapping = protect(src, keep_terms)
        action, keep_class = classify_action(reg, keep_terms_ci, len(mapping), masked)
        reg["translation_action"] = action
        if keep_class:
            reg["keep_class"] = keep_class
        if reg["region_type"] == "heading":
            last_heading[reg["page"]] = src
        if action != "translate":
            if action == "manual":
                issues.append(make_issue("MANUAL_REGION", "P1", STAGE,
                                         f"cần xử lý thủ công ({keep_class})",
                                         page=reg["page"], region_id=reg["region_id"]))
            continue

        reg["placeholders"] = mapping
        reg["source_masked"] = masked

        # context per spec §6.6
        idx = reg["reading_index"]
        same_page = [r for r in regions if r["page"] == reg["page"]]
        prev_r = next((r for r in reversed(same_page) if r["reading_index"] < idx), None)
        next_r = next((r for r in same_page if r["reading_index"] > idx), None)
        table_headers = []
        if reg["region_type"] == "table_cell":
            cells = [r for r in same_page if r["region_type"] == "table_cell"]
            if cells:
                top_y = min(c["bbox"][1] for c in cells)
                table_headers = [c["source_text"] for c in cells
                                 if abs(c["bbox"][1] - top_y) < 3][:8]
        cont_prev = by_id.get(reg.get("continuation_prev", ""), {}).get("source_text", "")
        cont_next = by_id.get(reg.get("continuation_next", ""), {}).get("source_text", "")

        size = reg["runs"][0]["size"] if reg["runs"] else 10.0
        cw = reg["container"][2] - reg["container"][0]
        ch = reg["container"][3] - reg["container"][1]
        max_lines = max(1, math.floor(ch / (1.15 * size)))
        req = {
            "region_id": reg["region_id"], "page": reg["page"],
            "region_type": reg["region_type"],
            "source_text": masked,
            "placeholders": sorted(mapping.keys()),
            "style_roles": sorted({r["role"] for r in reg["runs"]}),
            "context": {
                "heading": last_heading.get(reg["page"], ""),
                "prev": (prev_r or {}).get("source_text", "")[:80],
                "next": (next_r or {}).get("source_text", "")[:80],
                "table_headers": table_headers,
                "continuation_prev": cont_prev[-120:] if cont_prev else "",
                "continuation_next": cont_next[:120] if cont_next else "",
            },
            "glossary_prefer": [
                {"en": g["term"], "vi": g["target"]} for g in prefer
                if re.search(rf"(?i)(?<![a-z]){re.escape(g['term'])}(?![a-z])", src)],
            "length_guidance": {
                "container_w_pt": round(cw, 1), "container_h_pt": round(ch, 1),
                "font_size": size, "max_lines": max_lines,
                "note": "Tiếng Việt nên ngắn gọn; ưu tiên vừa container, không cần dịch sát từng chữ."},
        }
        append_jsonl(req_path, req)
        n_requests += 1
        if cur_page is not None and (reg["page"] != cur_page or len(cur_batch) >= max_batch):
            if not reg.get("continuation_prev"):
                flush_batch()
        cur_page = reg["page"]
        cur_batch.append(reg["region_id"])
    flush_batch()

    save_json(job.p("translation", "batches.json"),
              {"generated_at": utc_now(), "batches": batches})
    save_json(job.p("model", "regions.json"), model)
    ex = load_json(job.p("model", "regions_issues.json"), [])
    save_json(job.p("model", "regions_issues.json"), ex + issues)

    n_keep = sum(1 for r in regions if r["translation_action"] == "keep")
    n_manual = sum(1 for r in regions if r["translation_action"] == "manual")
    with open(job.p("translation", "AGENT_INSTRUCTIONS.md"), "w", encoding="utf-8") as f:
        f.write(AGENT_INSTRUCTIONS.format(
            n=n_requests, batches=len(batches),
            src=cfg["languages"]["source"], tgt=cfg["languages"]["target"],
            domain=domain_context.strip() or "(không có — dịch trung tính, kỹ thuật)"))
    job.mark_stage(STAGE)
    job.log_event(STAGE, "info", "PREPPED",
                  f"requests={n_requests} keep={n_keep} manual={n_manual} batches={len(batches)}")
    job.write_summary(
        f"Agent dịch {n_requests} regions theo `translation/AGENT_INSTRUCTIONS.md` "
        f"({len(batches)} batches), ghi `translation/responses.jsonl`, "
        f"rồi chạy `validate_responses.py --job <job>`.")
    print(f"translate_prep: {n_requests} requests, {n_keep} keep, "
          f"{n_manual} manual, {len(batches)} batches")


AGENT_INSTRUCTIONS = """# Hướng dẫn dịch cho agent (prompt_version: req-v1)

Dịch {src} → {tgt}. Có {n} requests trong `requests.jsonl`, chia {batches} batches
(`batches.json`). Với MỖI request, append một dòng JSON vào `responses.jsonl`:

```json
{{"region_id": "...", "target_runs": [{{"role": "body", "text": "..."}}],
  "placeholders": ["BRAND_1"], "notes": []}}
```

Quy tắc bắt buộc (validator sẽ reject nếu vi phạm):

1. Placeholder dạng ⟦TYPE_N⟧ phải xuất hiện trong bản dịch ĐÚNG SỐ LẦN như trong
   `source_text`, giữ nguyên ký tự — không dịch, không thêm bớt.
2. `target_runs` không rỗng; mỗi run có `role` thuộc `style_roles` của request;
   nếu request có role `label` thì response phải giữ role `label`.
3. Dùng `glossary_prefer` khi khớp ngữ cảnh. Không dịch nội dung trong placeholder.
4. Unicode: chữ tiếng Việt dạng precomposed (NFC).
5. Tôn trọng `length_guidance`: bản dịch dài quá container sẽ bị shrink/review —
   ưu tiên gọn, giữ nghĩa kỹ thuật chính xác, không làm nhẹ cảnh báo an toàn.
6. Số và đơn vị giữ định dạng nguồn (đã nằm trong placeholder MEAS/MODEL).
7. `\n` trong text của target run = explicit line break (xuống dòng cứng); dùng khi
   cần giữ cấu trúc dòng như label/value hoặc danh sách trong một cell.
8. **BẢN DỊCH PHẢI DO MODEL CỦA SESSION DỊCH TRỰC TIẾP, TỪNG REQUEST.** CẤM sinh
   `responses.jsonl` bằng script, dictionary tra cứu, hay find-replace — kể cả
   "để cho nhanh". Engine đo tỷ lệ region chưa dịch (target trùng source) và
   region sai ngôn ngữ đích: vượt 5% (config `translation.authenticity`) → P0 `TRANSLATION_COVERAGE_FAIL`,
   KHÔNG waive được, job không bao giờ release. Khối lượng lớn → dịch theo batch
   trong `batches.json`, nhiều turn; không được đi tắt.

## Domain context

{domain}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        if job.status() not in ("PREFLIGHTED", "NEEDS_REVIEW"):
            raise BlockingError(f"status {job.status()} — cần PREFLIGHTED (hoặc NEEDS_REVIEW re-prep)")
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            prep(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
