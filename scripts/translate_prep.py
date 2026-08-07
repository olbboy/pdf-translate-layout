"""Stage 3 — Translate-prep: action classifier, protected tokens, batch requests.

Spec §5.6, §6.5-6.6. Output: translation/requests.jsonl, translation/batches.json,
translation/AGENT_INSTRUCTIONS.md; cập nhật action vào model/regions.json.
Chạy: python3 translate_prep.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import math
import re

from _common import (RERUNNABLE_STATUSES, BlockingError, Job, append_jsonl, exit_blocking,
                     load_glossary, load_json, make_issue, nfc, save_json, spec_cell_text,
                     utc_now)

STAGE = "translate_prep"
PH = "⟦{}⟧"  # ⟦TOKEN⟧
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")
# Chữ số dính liền CHỮ CÁI ngay cạnh placeholder. Bản gốc đặt sai dấu cách trong một số đo
# thì `protect()` chỉ che được phần sau, phần chữ số đầu mắc lại trong từ bên cạnh và model
# không còn nhận ra nó thuộc con số. Ca thật: V16 manual p25 in `is1 5V` (đúng ra `is1.5V`)
# → masked thành `is1 ⟦MEAS_1⟧` → dịch ra "đạt 5V", mất chữ số 1. `NUMBER_DRIFT` bắt được
# nhưng ở stage 5, sau khi model đã dịch sai; ở đây cảnh báo đi thẳng vào request.
# Luật CHẶT (đòi chữ cái liền trước chữ số): đo trên 1243 vùng của 3 tài liệu — 1 đúng,
# 0 oan. Bỏ điều kiện chữ cái thì dính hết số mục kiểu `6.1 ⟦MODEL_1⟧`: 19 cảnh báo, 18 oan.
# CHỈ bắt chiều này. Chiều ngược (`⟦…⟧ 5V`) là dạng bình thường — placeholder rồi tới một số
# đo — nên thêm vào chỉ đẻ báo oan, không có ca thật nào biện minh.
PH_DIGIT_ADJ = re.compile(r"[A-Za-z]\d\s?⟦[A-Z]+_\d+⟧")

NUMERIC_RE = re.compile(r"^[\d\s.,:/×xX+\-±%()~]+$")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s⟦⟧]+")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# `UN` nằm trong danh sách vì mã vận chuyển UN (`UN38.3`, `UN3480`) là tên tiêu chuẩn, không
# phải model. Thiếu nó thì `MODEL_RE` chỉ ăn được `UN38` và bỏ lại `.3`, nên vùng chỉ chứa
# đúng dấu tiêu chuẩn ấy có residual `"3"` và bị xếp `translate` thay vì `keep` — engine vẽ
# lại một dấu vốn không cần dịch, và **mất luôn font gốc**: bản gốc dùng `Impact` (nét rất
# đậm) nhưng khai `bold=False`, nên nó map sang Noto Sans Regular và dấu thành chữ thường
# mảnh. Ca thật: trang bìa HV48100 và V5° datasheet.
# Đo trên 2666 vùng của 7 job: đổi đúng 11 vùng, tất cả là `UN38.3` (11) và `UN3480` (1),
# 0 khớp oan.
STD_RE = re.compile(r"\b(?:IEC|UL|EN|ISO|CE|FCC|RoHS|UN)\s?-?\d[\w.-]*\b")
MEAS_RE = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)?\s?(?:°C|°F|mm2|mm²|mm|cm|kWh|Wh|mAh|Ah|Hz|Nm|AWG|kg|kW|V|A|W|m|g|%))(?![\w])")
MODEL_RE = re.compile(r"\b(?:[A-Z]{1,4}\d+[A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|Ø\s?\d+(?:mm)?)\b")


def protect(text: str, keep_terms: list[str],
            mapping: dict | None = None, counters: dict | None = None) -> tuple[str, dict]:
    """Thay typed tokens bằng placeholder ⟦TYPE_N⟧ (spec §6.5). Trả (masked, map).

    `mapping`/`counters` dùng chung cho nhiều lần gọi liên tiếp: mask từng Ô của lưới thông
    số theo thứ tự đọc phải ra ĐÚNG số hiệu token như mask cả region một lượt, nếu không gợi
    ý trong `source_warnings` sẽ mang số hiệu khác `source_text` và model chép nhầm.
    Đúng được vì ô nằm theo thứ tự nguồn và ngăn nhau bằng khoảng trắng — không mẫu nào bị
    cắt ngang ranh giới ô, và bộ đếm mỗi loại vẫn tăng theo thứ tự xuất hiện.
    """
    mapping = {} if mapping is None else mapping
    counters = {} if counters is None else counters

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

    # Context graph (stage 2.5) — optional: job cũ dựng trước 1.6.0 không có, vẫn chạy được.
    graph = load_json(job.p("model", "context_graph.json"), {}) or {}
    chain_by_id = {c["chain_id"]: c for c in graph.get("chains", [])}
    under_heading = graph.get("under_heading", {})
    co_figure_of: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        if e["type"] == "co_figure":
            co_figure_of.setdefault(e["from"], []).append(e["to"])
            co_figure_of.setdefault(e["to"], []).append(e["from"])

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

        warnings = []
        m_adj = PH_DIGIT_ADJ.search(masked)
        if m_adj:
            warnings.append(
                f"Chuỗi {m_adj.group(0)!r}: chữ số dính chữ ngay cạnh placeholder. Bản gốc "
                "nhiều khả năng đặt sai dấu cách giữa một số đo — đọc ngữ cảnh, đối chiếu "
                "tài liệu cùng bộ nếu có, và giữ ĐỦ chữ số trong bản dịch.")
            issues.append(make_issue(
                "PH_DIGIT_ADJACENT", "P2", STAGE,
                f"chữ số dính placeholder: {m_adj.group(0)!r} — nguồn có thể đặt sai dấu "
                "cách trong một số đo",
                page=reg["page"], region_id=reg["region_id"]))
        n_blank = len(reg.get("fill_rules") or [])
        if n_blank:
            warnings.append(
                f"Region này có {n_blank} ô trống để người dùng ĐIỀN TAY (bản gốc vẽ bằng "
                "gạch chân). Bản dịch phải đặt lại đúng ngần ấy ô trống bằng một dãy dấu "
                "gạch dưới ('________') ở đúng chỗ cần điền — engine sẽ xoá gạch của bản "
                "gốc và để dãy gạch dưới của bạn chảy theo chữ. Thiếu ô trống thì biểu mẫu "
                "hết dùng được.")
        cells = reg.get("spec_cells") or []
        if cells:
            # Chữ của ô phải mang ĐÚNG số hiệu placeholder như `source_text`: mask lại từng ô
            # theo thứ tự đọc với bộ đếm dùng chung. Số hiệu lệch một chỗ thôi là model chép
            # nhầm token và stage 5 báo PLACEHOLDER_MISMATCH.
            cmap, ccnt, cmasked = {}, {}, []
            for c in cells:
                cmasked.append(protect(spec_cell_text(reg, c), keep_terms, cmap, ccnt)[0])
            if any(mapping.get(k) != v for k, v in cmap.items()):
                cmasked = []        # bất biến thứ tự hỏng → bỏ gợi ý, giữ phần đếm
            grid = ("\n".join(f"  {i + 1}. [{'trái' if c['col'] == 0 else 'phải'}] {t}"
                              for i, (c, t) in enumerate(zip(cells, cmasked)))
                    if cmasked else "  (không in được lưới — bám theo thứ tự dòng nguồn)")
            warnings.append(
                f"Region này là KHỐI HAI CỘT mà bản gốc căn bằng dãy space, engine "
                f"đã đo được lưới: {len(cells)} ô. Bản dịch phải có ĐÚNG {len(cells)} đoạn "
                f"ngăn bằng '\\n', theo thứ tự đọc trái→phải rồi xuống hàng, mỗi đoạn một ô — "
                f"engine đặt từng đoạn vào đúng cột của nó. Lưới nguồn:\n" + grid
                + "\nGộp hai ô vào một đoạn sẽ làm cả khối dồn về cột trái.")

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

        # Chuỗi từ context_graph: cho model thấy TRỌN câu/cụm mà region này là một mảnh.
        # Đây là thứ chữa gốc RC-A (câu bị xé theo dòng PDF) ở phía prompt — mỗi region vẫn
        # trả một target riêng để layout không đổi, nhưng model biết mình đang dịch mảnh nào
        # của cái gì nên đảo vế và chọn từ đúng ngữ cảnh.
        chain_src, chain_pos, chain_kind = "", "", ""
        cid = reg.get("chain_id")
        if cid and cid in chain_by_id:
            ch = chain_by_id[cid]
            chain_src = ch["source_joined"][:600]
            chain_pos = f"{ch['region_ids'].index(reg['region_id']) + 1}/{len(ch['region_ids'])}"
            chain_kind = ch["kind"]
        co_fig = [by_id[o]["source_text"][:60] for o in co_figure_of.get(reg["region_id"], [])
                  if o in by_id][:4]

        size = reg["runs"][0]["size"] if reg["runs"] else 10.0
        cw = reg["container"][2] - reg["container"][0]
        ch = reg["container"][3] - reg["container"][1]
        max_lines = max(1, math.floor(ch / (1.15 * size)))
        req = {
            "region_id": reg["region_id"], "page": reg["page"],
            "region_type": reg["region_type"],
            "source_text": masked,
            "source_warnings": warnings,
            "placeholders": sorted(mapping.keys()),
            "style_roles": sorted({r["role"] for r in reg["runs"]}),
            "context": {
                "heading": last_heading.get(reg["page"], "") or under_heading.get(reg["region_id"], ""),
                # 80 ký tự cắt đúng giữa câu nên hàng xóm thường vô nghĩa; 240 đủ trọn câu
                # cho hầu hết đoạn của tài liệu kỹ thuật.
                "prev": (prev_r or {}).get("source_text", "")[-240:],
                "next": (next_r or {}).get("source_text", "")[:240],
                "table_headers": table_headers,
                "continuation_prev": cont_prev[-120:] if cont_prev else "",
                "continuation_next": cont_next[:120] if cont_next else "",
                "chain_source": chain_src,
                "chain_position": chain_pos,
                "chain_kind": chain_kind,
                "co_figure": co_fig,
            },
            "glossary_prefer": [
                {"en": g["term"], "vi": g["target"]} for g in prefer
                if re.search(rf"(?i)(?<![a-z]){re.escape(g['term'])}(?![a-z])", src)],
            "length_guidance": {
                "container_w_pt": round(cw, 1), "container_h_pt": round(ch, 1),
                "font_size": size, "max_lines": max_lines,
                # Note cũ ("ưu tiên vừa container, không cần dịch sát từng chữ") đẻ ra văn
                # cụt kiểu điện tín và viết tắt tự chế — defect thật đã phải sửa tay.
                "note": "Dịch đủ nghĩa, tự nhiên. Vượt khung thì bỏ từ đệm, KHÔNG bỏ thông "
                        "tin; viết tắt chỉ dùng bộ đã duyệt trong glossary/domain context."},
        }
        append_jsonl(req_path, req)
        n_requests += 1
        if cur_page is not None and (reg["page"] != cur_page or len(cur_batch) >= max_batch):
            # Không cắt batch giữa chuỗi: cross-page (như cũ) VÀ same-page chain của graph —
            # cắt giữa chuỗi thì model mất đúng thứ chain_source vừa cho nó thấy.
            mid_chain = bool(cid) and chain_pos and not chain_pos.startswith("1/")
            if not reg.get("continuation_prev") and not mid_chain:
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
6b. **`source_warnings`** (nếu không rỗng) là cảnh báo nguồn có thể HỎNG ở chỗ đó — thường
   là dấu cách đặt sai làm vỡ một con số. ĐỌC nó trước khi dịch region đó, và đừng chép
   máy móc con số đã bị vỡ. Ca thật: bản gốc in `is1 5V` cho `1.5V`, dịch máy móc ra "5V"
   là sai một bậc 10 lần trong tài liệu kỹ thuật. Đối chiếu tài liệu cùng bộ nếu có.
6c. **Địa chỉ bưu chính giữ NGUYÊN như nguồn** — chỉ dịch nhãn (`Factory Address` →
   `Địa chỉ nhà máy`), không dịch thân địa chỉ. `No. 3492 Jinqian Road, Fengxian
   District, Shanghai` phải ra y như vậy, KHÔNG thành `Số 3492 Đường Jinqian, Quận
   Fengxian, Thượng Hải` — địa chỉ đã dịch thì không gửi thư tới được. Tên quốc gia đứng
   cuối được dịch bình thường. Vi phạm → P1 `CONSISTENCY_ENTITY`.
7. `\n` trong text của target run = explicit line break (xuống dòng cứng); dùng khi
   cần giữ cấu trúc dòng như label/value hoặc danh sách trong một cell.
7a. **Bảng thông số hai cột** — khi `source_warnings` báo region có lưới N ô, bản dịch phải
   có ĐÚNG N đoạn ngăn bằng `\n`, theo đúng thứ tự lưới in trong cảnh báo. Đây là hợp đồng
   đếm, không phải gợi ý: lệch số đoạn thì engine bỏ lưới và cả bảng dồn về một cột trái.
   Gộp nhiều run thì tổng số đoạn của các run cộng lại mới là N. Sai → P1 `SPEC_GRID_DROPPED`.
7b. **`context.chain_source`** (nếu có) là TRỌN câu/cụm mà region này chỉ là một mảnh —
   PDF xé chữ theo dòng chứ nội dung không đứt ở đó. Đọc hết chuỗi, dịch cả cụm trong
   đầu, rồi ghi phần thuộc về region đang xử lý (`chain_position` cho biết mảnh thứ mấy).
   Được phép đảo vế cho tự nhiên miễn là ghép các mảnh lại vẫn đủ và đúng thứ tự.
   `chain_kind: label_stack` = một nhãn chú thích nhiều dòng cạnh hình → dịch cả cụm theo
   trật tự tiếng Việt rồi chia dòng, KHÔNG dịch từng dòng máy móc.
   **Placeholder phải ở lại đúng region gốc của nó** — không chuyển ⟦TOKEN⟧ sang mảnh khác.
   `context.co_figure` là các nhãn anh em cùng hình: đọc để không gán nhầm nghĩa của nhau.
8. **MỌI bản dịch phải do model của session sinh ra, cho TỪNG request.** CẤM mọi
   logic dịch nằm trong code: dictionary/bảng tra cứu tự chế, find-replace, hay
   fallback copy-source. Script (nếu dùng) CHỈ được là phương tiện GHI các bản
   dịch model đã sinh sẵn — embedded verbatim, không biến đổi — và phải nằm trong
   job folder, KHÔNG nằm trong `scripts/` của skill package. Placeholder lệch →
   sửa bản dịch đó, không silently fallback. Engine đo authenticity (target trùng
   source / sai ngôn ngữ đích): vượt 5% (`translation.authenticity`) → P0
   `TRANSLATION_COVERAGE_FAIL`/`TARGET_LANG_FAIL`, KHÔNG waive được, không thể
   release. Khối lượng lớn → dịch theo batch trong `batches.json`, nhiều turn.

## Domain context

{domain}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        if job.status() not in RERUNNABLE_STATUSES:
            raise BlockingError(f"status {job.status()} — cần một trong "
                                f"{', '.join(RERUNNABLE_STATUSES)} (§11.5)")
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            prep(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
