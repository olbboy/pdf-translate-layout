"""Stage 2 — Extract + layout graph: rawdict spans/chars → semantic regions.

Spec §6.3-6.4, §5.3, §5.5. Output: model/regions.json, model/fonts.json,
model/regions_issues.json. Chạy: python3 extract_group.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import re
import statistics

import pymupdf

import build_context_graph as _cg
from _common import (RERUNNABLE_STATUSES, BlockingError, Job, exit_blocking, fill_in_rules,
                     horizontal_rules, layout_model_for, load_json, make_issue, nfc,
                     save_json, sha256_text, utc_now, vertical_rules)

STAGE = "extract_group"
DIR_TO_ROT = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}
LIST_RE = re.compile(r"^\s*(\d{1,2}[\.\)]|[a-z]\)|[•·▪–\-\*]\s|[①-⑳])")
# Chữ hai bên khe cột được phép chờm lên vạch: bản gốc V16 p11 để "Recovery*" kết thúc
# 0.45pt bên phải vạch 125.1. Nới quá thì khe từ thường sát mép ô cũng dính.
RULE_GAP_TOL_PT = 1.5
SENT_END = tuple(".!?:;…。")


def span_from_raw(rs: dict, line: dict) -> dict | None:
    chars = rs.get("chars") or []
    text = "".join(c.get("c", "") for c in chars)
    if not text:
        return None
    x0 = min(c["bbox"][0] for c in chars); y0 = min(c["bbox"][1] for c in chars)
    x1 = max(c["bbox"][2] for c in chars); y1 = max(c["bbox"][3] for c in chars)
    return {
        "text": text,
        "origin": [round(v, 2) for v in chars[0]["origin"]],
        "bbox": [round(v, 2) for v in (x0, y0, x1, y1)],
        "size": round(rs.get("size", 0), 2),
        "flags": rs.get("flags", 0),
        "font": rs.get("font", ""),
        "color": rs.get("color", 0),
        "chars": [{"c": c.get("c", ""), "origin": [round(v, 2) for v in c["origin"]],
                   "bbox": [round(v, 2) for v in c["bbox"]]} for c in chars],
    }


def style_of(span: dict) -> dict:
    f = span["flags"]
    return {"bold": bool(f & 16), "italic": bool(f & 2),
            "serif": bool(f & 4), "mono": bool(f & 8)}


def union(bs: list) -> list:
    return [round(min(b[0] for b in bs), 2), round(min(b[1] for b in bs), 2),
            round(max(b[2] for b in bs), 2), round(max(b[3] for b in bs), 2)]


def ink_bbox(spans: list) -> list | None:
    """bbox chỉ tính ký tự CÓ MỰC → None nếu cả line là khoảng trắng.

    Space ở đầu/cuối dòng có advance nhưng không vẽ gì. Tính chúng vào bbox thì
    container của ô bảng phình ra khỏi cột (`container = cell | bbox`), fitter wrap
    theo bề rộng không có thật, và dòng dịch vượt qua vạch kẻ dọc. Ca thật: ô ghi chú
    cột phải của V16 manual p26 thổi 7.5pt (3 space đuôi), Lite p30 thổi 2.5pt — mực
    nguồn dừng ở 380.4/380.2, vạch kẻ ở 380.9/380.8, nhưng khung nới tới 387.4/382.2.
    """
    bs = [c["bbox"] for s in spans for c in s["chars"] if not c["c"].isspace()]
    return union(bs) if bs else None


def build_lines(page: pymupdf.Page) -> tuple[list, list]:
    """→ (lines, block_ids). Mỗi line: bbox, dir, wmode, block, spans[]."""
    raw = page.get_text("rawdict")
    lines, blocks = [], []
    for bi, blk in enumerate(raw["blocks"]):
        if blk.get("type") != 0:
            continue
        blocks.append(bi)
        for ln in blk["lines"]:
            spans = [s for s in (span_from_raw(rs, ln) for rs in ln["spans"]) if s]
            if not spans or not "".join(s["text"] for s in spans).strip():
                continue
            bb = ink_bbox(spans)
            lines.append({"bbox": bb or [round(v, 2) for v in ln["bbox"]],
                          "dir": tuple(round(c, 3) for c in ln["dir"]),
                          "wmode": ln.get("wmode", 0), "block": bi, "spans": spans})
    return lines, blocks


def detect_tables(page: pymupdf.Page, issues: list, pno: int) -> list:
    """→ list of {bbox, cells:[rect]} đã sanity-check."""
    out = []
    try:
        tf = page.find_tables()
        for t in tf.tables:
            cells = [c for c in (t.cells or []) if c]
            if t.row_count >= 2 and t.col_count >= 2 and len(cells) >= 4:
                out.append({"bbox": [round(v, 2) for v in t.bbox],
                            "cells": [[round(v, 2) for v in c] for c in cells]})
    except Exception as e:  # find_tables lỗi không được chặn extraction
        issues.append(make_issue("TABLE_DETECT_ERROR", "P2", STAGE, str(e)[:120], page=pno))
    return out


def line_height(lines: list) -> float:
    hs = [l["bbox"][3] - l["bbox"][1] for l in lines]
    return statistics.median(hs) if hs else 12.0


def group_block_lines(blk_lines: list, lh: float) -> list[list]:
    """Tách lines trong một block thành paragraph theo gap dọc / size jump."""
    groups, cur = [], [blk_lines[0]]
    for prev, ln in zip(blk_lines, blk_lines[1:]):
        gap = ln["bbox"][1] - prev["bbox"][3]
        s_prev = prev["spans"][0]["size"]; s_cur = ln["spans"][0]["size"]
        jump = abs(s_cur - s_prev) > 0.2 * max(s_prev, s_cur)
        if gap > 0.85 * lh or jump:
            groups.append(cur); cur = [ln]
        else:
            cur.append(ln)
    groups.append(cur)
    return groups


def split_label_clusters(grp: list) -> list[list]:
    """Tách label cluster quanh hình: các dòng nhãn ngắn nằm ở x0 khác nhau
    trong cùng block (kể cả bị interleave theo y) → cụm theo x0.

    Guard: dòng dài (>32 chars), x0 thẳng hàng, center thẳng hàng (căn giữa)
    hoặc right thẳng hàng (căn phải) → giữ nguyên nhóm.
    """
    if len(grp) < 2:
        return [grp]
    texts = ["".join(s["text"] for s in l["spans"]).strip() for l in grp]
    if max(len(t) for t in texts) > 32:
        return [grp]
    x0s = [l["bbox"][0] for l in grp]
    x1s = [l["bbox"][2] for l in grp]
    ctrs = [(a + b) / 2 for a, b in zip(x0s, x1s)]
    for vals in (x0s, ctrs, x1s):
        if max(vals) - min(vals) <= 8:
            return [grp]
    clusters: list[list] = []
    for l in sorted(grp, key=lambda l: l["bbox"][0]):
        for c in clusters:
            if abs(c[0]["bbox"][0] - l["bbox"][0]) <= 8:
                c.append(l)
                break
        else:
            clusters.append([l])
    for c in clusters:
        c.sort(key=lambda l: l["bbox"][1])
    clusters.sort(key=lambda c: (c[0]["bbox"][1], c[0]["bbox"][0]))
    return clusters


def _agreement(vals: list, tol: float = 1.0) -> int:
    """Số dòng đông nhất cùng chia sẻ một mốc (±tol) — thống kê bền với dòng lạc."""
    return max(sum(1 for w in vals if abs(w - v) <= tol) for v in vals)


def infer_alignment(lines: list, container: list) -> str:
    if len(lines) >= 2:
        lefts = [l["bbox"][0] for l in lines]; rights = [l["bbox"][2] for l in lines]
        centers = [(a + b) / 2 for a, b in zip(lefts, rights)]
        # Biên độ max-min để MỘT dòng lạc quyết định cả khối. Ca thật V5 Series p15: đoạn
        # văn xuôi căn trái 8 dòng cùng mép trái 26.8, nhưng `merge_paragraph` gộp thêm chú
        # thích bảng đặt lệch phải ở dòng cuối — vl vọt lên 268.5 trong khi vr 176.8, nên
        # `min` chọn "right" và cả đoạn bị đẩy sang phải.
        # Đếm số dòng ĐỒNG THUẬN thì dòng lạc chỉ là 1 phiếu.
        al, ar, ac = (_agreement(v) for v in (lefts, rights, centers))
        if max(al, ar, ac) >= 2:
            if al >= ar and al >= ac:
                return "left"
            return "right" if ar > ac else "center"
        # Không mốc nào được hai dòng đồng thuận thì chưa có bằng chứng — giữ luật biên độ
        # cũ. Bỏ lối thoát này thì ô hai dòng căn giữa thật bị ép về trái: đo trên 5 job,
        # 4 ô kiểu "Charge: …\nDischarge: …" trong ô gộp bị phá.
        vl, vr, vc = (max(v) - min(v) for v in (lefts, rights, centers))
        m = min(vl, vr, vc)
        if m == vl:
            return "left"
        return "center" if m == vc else "right"
    x0, _, x1, _ = lines[0]["bbox"]
    cw = container[2] - container[0]
    if cw > 0:
        lgap = x0 - container[0]; rgap = container[2] - x1
        if abs(lgap - rgap) < 0.08 * cw and lgap > 2:
            return "center"
        if rgap < 0.4 * lgap:
            return "right"
    return "left"


MARK_MAX_PT = 8.0     # dấu gạch đầu dòng nhỏ hơn ngần này mỗi chiều
MARK_BAND_PT = 30.0   # và nằm trong ngần này kể từ mép trái vùng
MARK_LIFT_PT = 7.0    # tâm dấu nằm TRÊN baseline dòng nó đánh, không quá ngần này


def bullet_lines(reg: dict, drawings: list) -> list[int]:
    """Chỉ số các dòng được một dấu gạch đầu dòng đánh dấu.

    Vì sao cần: dấu `•` `◇` `∘` của bản gốc là **hình vẽ nhỏ**, không phải ký tự, nên không
    nằm trong `lines` của region. Chúng lại là bằng chứng CHẮC NHẤT về cấu trúc mục: mỗi dấu
    là một mục, không phải suy đoán. `paragraph_starts` chỉ đoán từ chỗ ngắt dòng và sai ở
    đúng những nguồn ngắt dòng cứng giữa câu — ca thật HV48100 p19 khối `CAUTION`: nó bỏ sót
    mục `Relative humidity` và nhận nhầm hai dòng nối tiếp thành mục mới, còn dãy dấu thì
    đếm đúng 9 mục.

    Dấu phải nằm ngoài vệt mực của mọi dòng — nếu chồng lên chữ thì đó là hình minh hoạ hay
    ký hiệu trong câu, không phải dấu gạch đầu dòng.

    Đo trên các job: 18 vùng có dấu; nơi số mục khớp số đoạn dịch thì **9 vùng trùng đúng
    luật cũ, 3 vùng luật cũ chịu thua, 0 vùng mâu thuẫn**.
    """
    b, ink = reg["bbox"], [l["bbox"] for l in reg["lines"]]
    base = [l["spans"][0]["origin"][1] for l in reg["lines"]]
    hit: set[int] = set()
    for d in drawings:
        r = d["rect"] if isinstance(d, dict) else pymupdf.Rect(d)
        if r.width > MARK_MAX_PT or r.height > MARK_MAX_PT:
            continue
        if not b[0] - 2 <= r.x0 <= b[0] + MARK_BAND_PT:
            continue
        cy = (r.y0 + r.y1) / 2
        if not b[1] - 4 <= cy <= b[3] + 4:
            continue
        if any(i[0] - 1 <= r.x0 <= i[2] and i[1] <= cy <= i[3] for i in ink):
            continue
        cand = [i for i, y in enumerate(base) if 0 <= y - cy <= MARK_LIFT_PT]
        if cand:
            hit.add(min(cand, key=lambda i: base[i] - cy))
    return sorted(hit)


COLUMN_MIN_CELLS = 4      # cột phải có ngần này ô một dòng mới đủ làm bằng chứng
COLUMN_MIN_AGREE = 0.75   # và ngần này phần đồng thuận


def column_consensus(regions: list) -> int:
    """Ô bảng MỘT DÒNG lấy alignment theo đồng thuận của cột. → số ô đã đổi.

    Vì sao cần: ô một dòng không có gì để đồng thuận nội bộ, nên `infer_alignment` phải đoán
    từ khe trái/khe phải. Dòng tiếng Anh gần đầy ô thì hai khe xấp xỉ nhau và luật dung sai
    đọc thành `center` — không phân biệt được với căn trái thật. Ca thật V5 p8:
    `Charge / Discharge over Current Protection` lấp gần kín ô (khe 3.2 / 10.9 trên bề rộng
    187.1) nên ra `center`, trong khi 7 ô còn lại cùng cột đều `left`; bản dịch ngắn hơn nên
    thụt hẳn vào giữa, lệch với cả cột.

    1.9.8 đã sửa ca nhiều dòng bằng cách đếm số dòng đồng thuận. Ở đây bằng chứng nằm ngoài
    ô: các ô CÙNG CỘT gần như luôn cùng một cách căn.

    Chỉ đụng ô một dòng — ô nhiều dòng có bằng chứng nội bộ thật, để nguyên. Ngưỡng đặt cao
    (>=4 ô, >=75%) vì cột trộn tiêu đề căn giữa với thân bài căn trái là chuyện thường: cột
    `Specifications` của chính trang đó chỉ có 3 ô một dòng (2 center, 1 left) và cả ba đều
    đang đúng — nới ngưỡng xuống là phá nó.
    """
    cols: dict[tuple, list] = {}
    for r in regions:
        if r["region_type"] != "table_cell" or len(r["lines"]) != 1:
            continue
        c = r["container"]
        cols.setdefault((round(c[0], 1), round(c[2], 1)), []).append(r)
    changed = 0
    for cells in cols.values():
        if len(cells) < COLUMN_MIN_CELLS:
            continue
        tally: dict[str, int] = {}
        for r in cells:
            tally[r["alignment"]] = tally.get(r["alignment"], 0) + 1
        win, n = max(tally.items(), key=lambda kv: kv[1])
        if n / len(cells) < COLUMN_MIN_AGREE:
            continue
        for r in cells:
            if r["alignment"] == win or not can_take(r, win):
                continue
            r["alignment"] = win
            changed += 1
    return changed


def can_take(reg: dict, win: str) -> bool:
    """Ô có được phép nhận `win` từ cột không.

    Chỉ chặn một chiều: đổi sang **left**. Text căn trái vẽ từ `base_x` — mép mực nguồn —
    nên ngân sách wrap chỉ còn `container.x1 - base_x`. Ô nào mực bắt đầu xa mép trái thì
    ngân sách đó hụt hẳn, và nếu ô ấy thật ra căn giữa thì ép sang trái vừa sai vừa làm chữ
    không fit nổi. Ca thật HV48100 p25: cột `OFF/ON` rộng 20.4pt, năm ô `OFF` lấp gần kín ô
    nên luật dung sai đọc nhầm thành `left` và thắng phiếu 5/6; ô `ON` (căn giữa THẬT, khe
    4.0/3.0) bị kéo theo, `Sáng` chỉ còn 16.4pt để wrap → `FIT_IMPOSSIBLE`.

    `center` và `right` neo vào khung nên không hụt ngân sách — không cần chặn.
    """
    if win != "left":
        return True
    c = reg["container"]
    return reg["bbox"][0] - c[0] <= max(2.0, 0.05 * (c[2] - c[0]))


def build_runs(all_spans: list) -> list:
    runs, cur = [], None
    for sp in all_spans:
        st = style_of(sp)
        key = (st["bold"], st["italic"], st["mono"], st["serif"],
               round(sp["size"], 1), sp["color"])
        if cur and cur["_key"] == key:
            cur["text"] += sp["text"]
        else:
            cur = {"_key": key, "text": sp["text"], **st,
                   "size": round(sp["size"], 1), "color": sp["color"], "font": sp["font"]}
            runs.append(cur)
    # Tiêu đề phụ in đậm MỞ ĐẦU region cũng là `emphasis`, không phải `body`.
    # Bản gốc hay gộp tiêu đề phụ in đậm ("Danger", "General Requirements", "Cleaning")
    # và cả đoạn văn xuôi theo sau vào MỘT block, nên chúng thành một region. Luật cũ chỉ
    # cho `emphasis` khi `i > 0`, nên run 0 in đậm rơi về `body`; `role_style()` của stage 6
    # lấy run ĐẦU TIÊN khớp role, tức run đậm đó, rồi vẽ CẢ VÙNG bằng chữ đậm.
    # Đo được trên HV48100 user manual: 59 region dính, chứa 46% tổng ký tự — bản dịch ra
    # 50% ký tự Noto Sans Bold trong khi bản đã phát hành trước đó chỉ 13%.
    # Điều kiện `lead_in`: run 0 in đậm VÀ còn ít nhất một run thường phía sau. Region đậm
    # toàn bộ (tiêu đề thật) không thoả, nên vẫn vẽ đậm nguyên như cũ.
    # Run thường theo sau phải có CHỮ THẬT. Bản gốc hay để một run toàn khoảng trắng ở
    # cuối; nhận nhầm nó thì tiêu đề in đậm nguyên dòng (dòng chương của mục lục) bị hạ
    # thành `emphasis` rồi `role_style("body")` trả về đúng run trắng đó — cả dòng mất đậm.
    lead_in = bool(runs) and runs[0]["bold"] and any(
        not r["bold"] and r["text"].strip() for r in runs[1:])
    for i, r in enumerate(runs):
        r.pop("_key")
        r["role"] = ("label" if i == 0 and r["bold"] and len(runs) > 1
                     and r["text"].rstrip().endswith(":")
                     else "emphasis" if r["bold"] and (i > 0 or lead_in) else "body")
    # Bất biến: luôn còn ít nhất một run `body` để `role_style()` có chỗ bám và để response
    # chỉ dùng `body` vẫn hợp lệ. Luật cũ ép cứng run 0 về `body` khi không có `label` —
    # chính chỗ đó vô hiệu hoá `emphasis` của tiêu đề phụ mở đầu.
    if runs and not any(r["role"] == "body" for r in runs):
        runs[0]["role"] = "body"
    return runs


SUP_MAX_CHARS = 6      # ký hiệu mũ dài hơn ngần này thì không phải chú thích
SUP_SIZE_FRAC = 0.75   # và cỡ chữ phải nhỏ hơn ngần này lần cỡ thân vùng


def fold_superscripts(lines: list) -> list:
    """Gộp dòng chỉ chứa ký hiệu mũ vào dòng mà nó viết nối tiếp.

    Vì sao cần: baseline của ký hiệu mũ cao hơn dòng thân nên PDF khai nó thành MỘT "line"
    riêng. Ca thật V5 p6, ô `Recommended Charge/ Discharge Current [1]` ra ba "dòng" với
    `[1]` nằm giữa: `source_text` thành ba đoạn, model dịch đúng ba đoạn theo hợp đồng, và
    bản vẽ đặt `[1]` thành một dòng riêng lơ lửng giữa hai dòng chữ.

    Chủ của ký hiệu là dòng kết thúc NGAY TRƯỚC nó theo chiều ngang và có baseline trong
    khoảng một dòng — tức dòng mà mắt người đọc thấy ký hiệu bám vào. Không tìm được chủ thì
    để nguyên: thà giữ dòng riêng còn hơn dán nhầm chỗ.
    """
    if len(lines) < 2:
        return lines
    sizes = [s["size"] for l in lines for s in l["spans"] for _ in s["text"]]
    if not sizes:
        return lines
    med = statistics.median(sizes)

    def is_sup(l):
        t = "".join(s["text"] for s in l["spans"]).strip()
        return (0 < len(t) <= SUP_MAX_CHARS and l["spans"]
                and max(s["size"] for s in l["spans"]) < SUP_SIZE_FRAC * med)

    def base_y(l):
        return l["spans"][0]["origin"][1]

    sup = {i for i, l in enumerate(lines) if is_sup(l)}
    if not sup or len(sup) == len(lines):
        return lines
    host_of: dict[int, int] = {}
    for i in sorted(sup):
        # Ký hiệu mũ được NÂNG lên, nên baseline của chủ luôn nằm THẤP HƠN nó một chút —
        # chưa tới một dòng. Không có vế này thì `[3]` của `Cycle Life` có thể dán ngược lên
        # `DC Breaker` ở hàng trên, vốn cách nó 16.5pt phía trên.
        cands = [j for j, l in enumerate(lines)
                 if j not in sup and l["bbox"][2] <= lines[i]["bbox"][0] + 1.0
                 and 0.0 <= base_y(l) - base_y(lines[i]) <= med]
        if cands:
            host_of[i] = min(cands, key=lambda j: base_y(lines[j]) - base_y(lines[i]))
    if not host_of:
        return lines
    out = []
    for j, l in enumerate(lines):
        if j in host_of:
            continue
        adds = [lines[i] for i, h in host_of.items() if h == j]
        if adds:
            l = {**l, "spans": l["spans"] + [s for a in adds for s in a["spans"]],
                 "bbox": union([l["bbox"]] + [a["bbox"] for a in adds])}
        out.append(l)
    return out


def make_region(page_no: int, rtype: str, lines: list, confidence: float) -> dict:
    lines = fold_superscripts(lines)
    spans = [s for l in lines for s in l["spans"]]
    text = "\n".join("".join(s["text"] for s in l["spans"]) for l in lines)
    d = lines[0]["dir"]
    return {
        "page": page_no, "region_type": rtype,
        "source_text": text, "source_hash": sha256_text(nfc(text)),
        "bbox": union([l["bbox"] for l in lines]),
        "direction": list(d), "rotation": DIR_TO_ROT.get(d, -1),
        "wmode": lines[0]["wmode"], "confidence": confidence,
        "lines": lines, "runs": build_runs(spans),
        "translation_action": "pending", "review_status": "pending",
    }


def merge_flow_regions(ordered: list, lh: float, pno: int) -> list:
    """Gộp các region là những dòng liên tiếp của CÙNG một đoạn thành một region.

    Vì sao cần: `group_block_lines` chỉ gộp trong một block rawdict, mà PDF hay đặt mỗi dòng
    vào một block riêng — thư ngỏ V16 user manual là 28 dòng thành 28 block, khe thật giữa
    chúng chỉ 2.72pt, thừa điều kiện gộp nếu chung block. Hệ quả: câu bị xé theo dòng, model
    dịch từng mảnh và tiếng Việt không đảo vế qua ranh giới region được (RC-A).

    Dùng CHUNG detector với context graph (`flow_link`) — một luật, hai mức áp dụng: graph
    chỉ đưa chuỗi vào context, còn ở đây gộp thật để fitter được wrap lại tự do. Mọi guard
    của graph (tiêu đề đánh số, mục lục, Table N, dòng nhãn-giá-trị, đầu chuỗi ≥4 từ) áp
    nguyên vào đây — không có chúng thì 9/10 lần gộp ngoài trang thư ngỏ là gộp sai.
    """
    out: list = []
    for reg in ordered:
        prev = out[-1] if out else None
        if (prev is not None and prev["rotation"] == 0 and reg["rotation"] == 0
                and "container" not in prev and "container" not in reg
                and _cg.flow_link(prev, reg, lh) is not None):
            out.pop()
            merged = make_region(pno, prev["region_type"],
                                 prev["lines"] + reg["lines"],
                                 min(prev["confidence"], reg["confidence"]))
            merged["merged_lines"] = prev.get("merged_lines", 1) + 1
            if prev.get("_hf_candidate") and reg.get("_hf_candidate"):
                merged["_hf_candidate"] = True
            out.append(merged)
        else:
            out.append(reg)
    return out


def fragment_row(line: dict, inner_edges: list) -> list:
    """Cắt line tại MỌI cụm space CÓ vạch cột nằm trong khe → list line con.

    Điều kiện "vạch cột nằm trong khe" là thứ phân biệt hàng bảng gõ liền bằng
    space với văn xuôi trong ô: khe giữa hai từ không có vạch nào nên không bao giờ
    bị cắt. Số lượng space thì KHÔNG phân biệt được — bản gốc V16 ngăn cột bằng một
    space đơn, và khe cột hẹp nhất đo được (1.33pt) còn mảnh hơn khe từ thường
    (2.50pt), nên chỉ hình học mới nói lên điều gì.
    """
    flat = [(ch, si) for si, sp in enumerate(line["spans"]) for ch in sp["chars"]]
    if not flat or any(len(ch["c"]) != 1 for ch, _ in flat):
        return [line]  # char nhiều ký tự → index lệch, không cắt
    text = "".join(ch["c"] for ch, _ in flat)

    cuts = []
    for m in re.finditer(r"\s+", text):
        a, b = m.span()
        if a == 0 or b >= len(flat):
            continue  # space rìa, không phải ranh giới cột
        lo, hi = flat[a - 1][0]["bbox"][2], flat[b][0]["bbox"][0]
        if any(lo - RULE_GAP_TOL_PT <= e <= hi + RULE_GAP_TOL_PT for e in inner_edges):
            cuts.append((a, b))
    if not cuts:
        return [line]

    segments, pos = [], 0
    for a, b in cuts:
        segments.append((pos, a))
        pos = b
    segments.append((pos, len(flat)))

    frags = []
    for a, b in segments:
        chunk = flat[a:b]
        while chunk and chunk[0][0]["c"].isspace():
            chunk.pop(0)
        while chunk and chunk[-1][0]["c"].isspace():
            chunk.pop()  # chỉ cắt trắng hai đầu — space đơn bên trong là một phần từ
        if not chunk:
            continue
        grouped: list[tuple[int, list]] = []
        for ch, si in chunk:
            if grouped and grouped[-1][0] == si:
                grouped[-1][1].append(ch)
            else:
                grouped.append((si, [ch]))
        spans = []
        for si, chars in grouped:
            src = line["spans"][si]
            spans.append({
                "text": "".join(c["c"] for c in chars),
                "origin": list(chars[0]["origin"]),
                "bbox": union([c["bbox"] for c in chars]),
                "size": src["size"], "flags": src["flags"],
                "font": src["font"], "color": src["color"], "chars": chars,
            })
        frags.append({"bbox": union([s["bbox"] for s in spans]), "dir": line["dir"],
                      "wmode": line["wmode"], "block": line["block"], "spans": spans})
    return frags or [line]


def split_multicol_rows(lines: list, tables: list, rules: list, issues: list, pno: int) -> list:
    """Hàng bảng gõ thành một dòng ngăn bằng space → tách theo vạch kẻ dọc.

    Không tách thì cả hàng rơi vào một cell (gán theo tâm line) và container
    phình qua nhiều cột, khiến bản dịch được vẽ đè lên vạch kẻ.

    Ranh giới lấy từ nét vẽ thật (`vertical_rules`) chứ không từ lưới logic của
    `find_tables`, và vạch phải cắt ngang đúng dải y của dòng mới tính: ô gộp không có
    nét ngăn, lưới logic vẫn báo có ranh giới ở đó và sẽ xé đôi một tiêu đề trải hết
    bảng. Đây cũng chính là danh sách Gate 4 dùng để chấm `G4_TABLE_RULE_CROSS`.
    """
    boxes = [pymupdf.Rect(t["bbox"]) for t in tables if t.get("cells")]
    if not boxes or not rules:
        return lines

    out, n_split = [], 0
    for line in lines:
        b = line["bbox"]
        centre = pymupdf.Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        frags = [line]
        if any(tb.contains(centre) for tb in boxes):
            inner = sorted({round(x, 1) for x, y0, y1 in rules
                            if y0 < b[3] - 0.5 and y1 > b[1] + 0.5
                            and b[0] + 1 < x < b[2] - 1})
            if inner:
                frags = fragment_row(line, inner)
        if len(frags) > 1:
            n_split += 1
        out.extend(frags)
    if n_split:
        issues.append(make_issue("TABLE_ROW_SPLIT", "P2", STAGE,
                                 f"tách {n_split} dòng bảng gõ liền theo lưới cột",
                                 page=pno))
    out.sort(key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    return out


def paint_origin_x(reg: dict) -> float:
    """x mà fitter THẬT SỰ bắt đầu vẽ. Phải khớp `fit_paint.ink_base_x`.

    Container phải bao được điểm này, nếu không mọi dòng thụt đầu — 19 dòng mục lục của
    Lite manual — thành `G4_OUT_OF_CONTAINER` phía trái dù chữ nằm đúng chỗ cũ.

    Nguyên bản trả thẳng origin của span đầu. Đúng cho tới 1.9.6/1.9.9: từ đó `ink_base_x`
    NÂNG base_x lên mép mực trái nhất, nên origin có đệm space không còn là nơi vẽ. Giữ công
    thức cũ thì container bị kéo sang trái đúng bằng bề rộng dãy space. Ca thật V5: ô `CANH`
    có 48 space đầu, container tụt về 134.2 trong khi cột CAN bắt đầu ở ~204 — ô căn giữa bị
    đọc thành `right` và bản dịch dính mép dải cam; ô trị số `Kích thước một khối` tụt về
    67.7, chồng lên ô nhãn `[29.0…121.2]` và tràn chữ sang đó.

    Stage 2 và stage 6 phải hiểu giống nhau về cùng một điểm — nên công thức lặp lại
    `ink_base_x`, không import chéo (stage 2 không phụ thuộc stage 6).
    """
    span_x = reg["lines"][0]["spans"][0]["origin"][0]
    return max(span_x, min(l["bbox"][0] for l in reg["lines"]))


def compute_container(reg: dict, obstacles: list, page_rect: list, lh: float) -> None:
    b = pymupdf.Rect(reg["bbox"])
    limit = pymupdf.Rect(page_rect) + (6, 6, -6, -6)
    inside = None
    for ob in obstacles:
        r = pymupdf.Rect(ob)
        if r.contains(b) and abs(r) < 0.7 * abs(pymupdf.Rect(page_rect)):
            inside = r if inside is None or abs(r) < abs(inside) else inside
    if inside is not None:  # text nằm trong border box → không vượt ra ngoài box
        limit = limit & (inside + (2, 2, -2, -2))
    # floor 20pt cho nhãn ngắn: EN→VI thường dài hơn; vẫn bị obstacle-clip
    # bên dưới nên không bao giờ chạm neighbor/protected zone (spec §8.4)
    max_dx = max(0.25 * b.width, 20.0) + 2
    max_dy = 0.7 * lh
    right = min(limit.x1, b.x1 + max_dx)
    left = max(limit.x0, b.x0 - (max_dx if reg.get("_align_hint") in ("center", "right") else 0))
    bottom = min(limit.y1, b.y1 + max_dy)
    for ob in obstacles:
        r = pymupdf.Rect(ob)
        if r.contains(b):
            continue  # box bao ngoài đã xử lý ở inside/limit
        # obstacle chắn ngang dải mở rộng phải/trái/dưới
        if r.y0 < b.y1 and r.y1 > b.y0:
            if b.x1 <= r.x0 < right:
                right = max(b.x1, r.x0 - 2)
            if left < r.x1 <= b.x0:
                left = min(b.x0, r.x1 + 2)
        if r.x0 < right and r.x1 > left and b.y1 <= r.y0 < bottom:
            bottom = max(b.y1, r.y0 - 2)
    left = min(left, paint_origin_x(reg))
    reg["container"] = [round(left, 2), round(b.y0, 2), round(right, 2), round(bottom, 2)]
    reg["expansion_log"] = {"dx_right": round(right - b.x1, 2),
                            "dx_left": round(b.x0 - left, 2),
                            "dy_bottom": round(bottom - b.y1, 2)}


def extract(job: Job) -> None:
    pf = load_json(job.p("model", "preflight.json"))
    if not pf:
        raise BlockingError("chưa có preflight.json — chạy preflight trước")
    skip_pages = {p["page"] for p in pf["pages"] if p["scanned"] or p["vector_suspect"]}
    manifest = load_json(job.p("model", "resource_manifest.json"), {"pages": []})
    issues: list[dict] = []
    doc = pymupdf.open(job.source_pdf)
    fp8 = job.load()["determinism"]["source_sha256"][:8]
    merge_paragraph = (job.config.get("layout") or {}).get("merge_paragraph", True)
    n_merged = 0

    pages_regions: list[list[dict]] = []
    for pno in range(doc.page_count):
        if pno in skip_pages:
            pages_regions.append([])
            continue
        page = doc[pno]
        lines, _ = build_lines(page)
        if not lines:
            pages_regions.append([])
            continue
        lh = line_height(lines)
        mpage = manifest["pages"][pno] if pno < len(manifest["pages"]) else {}
        img_boxes = [i["bbox"] for i in mpage.get("images", [])]
        draw_boxes = mpage.get("draw_clusters", [])

        sizes = [s["size"] for l in lines for s in l["spans"] for _ in s["text"]]
        body_med = statistics.median(sizes) if sizes else 10.0
        ph = page.rect.height

        tables = detect_tables(page, issues, pno)
        lines = split_multicol_rows(lines, tables, vertical_rules(page), issues, pno)
        regions: list[dict] = []
        used = [False] * len(lines)

        # 1) table cells
        for t in tables:
            for cell in t["cells"]:
                cr = pymupdf.Rect(cell)
                idxs = [i for i, l in enumerate(lines) if not used[i] and
                        cr.contains(pymupdf.Point((l["bbox"][0] + l["bbox"][2]) / 2,
                                                  (l["bbox"][1] + l["bbox"][3]) / 2))]
                if not idxs:
                    continue
                reg = make_region(pno, "table_cell", [lines[i] for i in idxs], 0.9)
                # nguồn có thể tràn nhẹ khỏi cell do find_tables — container theo thực tế
                cu = cr | pymupdf.Rect(reg["bbox"])
                reg["container"] = [round(min(cu.x0 + 0.5, paint_origin_x(reg)), 2),
                                    round(cu.y0 + 0.5, 2),
                                    round(cu.x1 - 0.5, 2), round(cu.y1 - 0.5, 2)]
                reg["expansion_log"] = {"cell": True}
                regions.append(reg)
                for i in idxs:
                    used[i] = True

        # 2) block → paragraph grouping cho lines còn lại
        by_block: dict[int, list] = {}
        for i, l in enumerate(lines):
            if not used[i]:
                by_block.setdefault(l["block"], []).append(l)
        for _, bls in sorted(by_block.items()):
            bls.sort(key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
            for grp in group_block_lines(bls, lh):
                subs = split_label_clusters(grp)
                for sub in subs:
                    regions.append(make_region(pno, "paragraph", sub,
                                               0.75 if len(subs) > 1 else 0.9))

        # 3) phân loại
        for reg in regions:
            if reg["region_type"] == "table_cell":
                continue
            t = reg["source_text"].strip()
            sz = reg["runs"][0]["size"] if reg["runs"] else body_med
            b = pymupdf.Rect(reg["bbox"])
            n_lines = len(reg["lines"])
            near_img = any(
                (b & (pymupdf.Rect(ib) + (-4, -lh * 1.2, 4, lh * 1.2))).is_valid and
                not (b & (pymupdf.Rect(ib) + (-4, -lh * 1.2, 4, lh * 1.2))).is_empty
                for ib in img_boxes)
            in_draw = any(pymupdf.Rect(db).contains(b) for db in draw_boxes)
            if reg["rotation"] != 0:
                reg["confidence"] = 0.7
            if b.y1 < 0.07 * ph or b.y0 > 0.93 * ph:
                reg["_hf_candidate"] = True
            if sz >= 1.25 * body_med and n_lines <= 2 and len(t) < 120:
                reg["region_type"] = "heading"
            elif LIST_RE.match(t):
                reg["region_type"] = "list_item"
            elif near_img and n_lines <= 3 and len(t) < 200:
                reg["region_type"] = "figure_caption"; reg["confidence"] = 0.7
            elif (near_img or in_draw) and len(t) <= 40 and sz <= 0.95 * body_med:
                reg["region_type"] = "diagram_label"; reg["confidence"] = 0.7
            elif b.y0 > 0.88 * ph and sz < 0.85 * body_med:
                reg["region_type"] = "footnote"

        # 4) reading order: 2 cột nếu có gutter rõ
        horiz = [r for r in regions if r["rotation"] == 0]
        rot = [r for r in regions if r["rotation"] != 0]
        pw = page.rect.width
        mids = sorted(r["bbox"][0] for r in horiz)
        two_col = False
        if len(horiz) >= 6:
            left_col = [r for r in horiz if (r["bbox"][0] + r["bbox"][2]) / 2 < pw / 2]
            right_col = [r for r in horiz if (r["bbox"][0] + r["bbox"][2]) / 2 >= pw / 2]
            if len(left_col) >= 2 and len(right_col) >= 2:
                lmax = max(r["bbox"][2] for r in left_col)
                rmin = min(r["bbox"][0] for r in right_col)
                two_col = rmin - lmax > 0.06 * pw
        if two_col:
            left_col.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
            right_col.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
            ordered = left_col + right_col
        else:
            ordered = sorted(horiz, key=lambda r: (round(r["bbox"][1] / 4), r["bbox"][0]))
        ordered += sorted(rot, key=lambda r: (r["rotation"], r["bbox"][1], r["bbox"][0]))

        # 4b) gộp dòng cùng đoạn (lg-basic-4). Phải chạy TRƯỚC bước 5 vì region_id sinh từ
        # container và chỉ số reading order — gộp sau khi gán id là đổi id của job đang chạy.
        if merge_paragraph:
            before = len(ordered)
            ordered = merge_flow_regions(ordered, lh, pno)
            if len(ordered) < before:
                n_merged += before - len(ordered)

        # 5) container + alignment + id
        obstacles_all = img_boxes + draw_boxes
        page_hrules = horizontal_rules(page)
        page_draw = page.get_drawings()
        for idx, reg in enumerate(ordered):
            if "container" not in reg:
                others = [r["bbox"] for r in ordered if r is not reg]
                compute_container(reg, others + obstacles_all, list(page.rect), lh)
            reg["alignment"] = infer_alignment(reg["lines"], reg["container"])
        column_consensus(ordered)
        for idx, reg in enumerate(ordered):
            # Ô trống điền tay — metadata thuần, KHÔNG đụng source_text/source_hash/region_id
            # nên job đã dịch chạy lại stage 2 không bị mồ côi response.
            fr = fill_in_rules(reg, page_hrules)
            if fr:
                reg["fill_rules"] = [[round(v, 2) for v in r] for r in fr]
            # Dòng nào có dấu gạch đầu dòng — metadata thuần như `fill_rules`, không đụng
            # source_text/source_hash/region_id nên job đã dịch chạy lại stage 2 không mồ côi.
            if len(reg["lines"]) > 1:
                bl = bullet_lines(reg, page_draw)
                if bl:
                    reg["bullet_lines"] = bl
            qx, qy = int(reg["container"][0] // 8), int(reg["container"][1] // 8)
            reg["region_id"] = f"{fp8}/p{pno}/{reg['region_type']}/{qx}_{qy}/{idx}"
            reg["reading_index"] = idx
            if reg["confidence"] < 0.8:
                issues.append(make_issue("REGION_CONFIDENCE_LOW", "P2", STAGE,
                                         f"{reg['region_type']} confidence={reg['confidence']}",
                                         page=pno, region_id=reg["region_id"]))
            if reg["rotation"] == -1:
                issues.append(make_issue("ARBITRARY_ANGLE_REGION", "P1", STAGE,
                                         f"dir={reg['direction']} không phải góc vuông",
                                         page=pno, region_id=reg["region_id"]))
        pages_regions.append(ordered)

    # 6) header/footer theo lặp lại cross-page
    from collections import Counter
    hf_norm = Counter()
    for regs in pages_regions:
        for r in regs:
            if r.get("_hf_candidate"):
                hf_norm[re.sub(r"\d+", "#", r["source_text"].strip())[:60]] += 1
    n_pages_with_text = sum(1 for regs in pages_regions if regs)
    for regs in pages_regions:
        for r in regs:
            if r.pop("_hf_candidate", False):
                key = re.sub(r"\d+", "#", r["source_text"].strip())[:60]
                if hf_norm[key] >= max(2, int(0.4 * n_pages_with_text)):
                    r["region_type"] = "header_footer"

    # 7) continuation qua page break (spec §6.4)
    flat = [r for regs in pages_regions for r in regs]
    for a, b_regs in zip(pages_regions, pages_regions[1:]):
        paras_a = [r for r in a if r["region_type"] in ("paragraph", "list_item")]
        paras_b = [r for r in b_regs if r["region_type"] in ("paragraph", "list_item")]
        if not paras_a or not paras_b:
            continue
        last, first = paras_a[-1], paras_b[0]
        ta, tb = last["source_text"].strip(), first["source_text"].strip()
        if (len(ta) > 25 and not ta.endswith(SENT_END)
                and tb and (tb[0].islower() or tb[0].isdigit() is False and tb[0].islower())):
            last["continuation_next"] = first["region_id"]
            first["continuation_prev"] = last["region_id"]
            issues.append(make_issue("CONTINUATION_LINKED", "P2", STAGE,
                                     "paragraph nối qua page break — context sẽ được stitch",
                                     page=last["page"], region_id=last["region_id"]))

    fonts_usage: dict[str, dict] = {}
    for r in flat:
        for run in r["runs"]:
            key = f"{run['font']}|b{int(run['bold'])}i{int(run['italic'])}"
            fonts_usage.setdefault(key, {"font": run["font"], "bold": run["bold"],
                                         "italic": run["italic"], "mono": run["mono"],
                                         "serif": run["serif"], "chars": 0})
            fonts_usage[key]["chars"] += len(run["text"])

    meta = job.load()
    # Chỉ layout model là việc của stage này; `engine_version` do `Job.mark_stage` đóng dấu
    # cho mọi stage (1.8.3).
    meta["determinism"]["layout_model_version"] = layout_model_for(job.config)
    job.save(meta)
    save_json(job.p("model", "regions.json"),
              {"generated_at": utc_now(), "layout_model": layout_model_for(job.config),
               "region_count": len(flat), "regions": flat})
    save_json(job.p("model", "fonts.json"), {"usage": list(fonts_usage.values())})
    save_json(job.p("model", "regions_issues.json"), issues)
    n_pages = doc.page_count
    doc.close()
    job.mark_stage(STAGE)
    job.log_event(STAGE, "info", "EXTRACTED", f"{len(flat)} regions / {n_pages} trang")
    job.write_summary("Chạy `translate_prep.py --job <job>` để build translation requests.")
    print(f"extract_group: {len(flat)} regions | issues: {len(issues)}")


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
            extract(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
