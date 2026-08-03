"""Stage 2 — Extract + layout graph: rawdict spans/chars → semantic regions.

Spec §6.3-6.4, §5.3, §5.5. Output: model/regions.json, model/fonts.json,
model/regions_issues.json. Chạy: python3 extract_group.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import re
import statistics

import pymupdf

from _common import (LAYOUT_MODEL_VERSION, BlockingError, Job, exit_blocking, load_json,
                     make_issue, nfc, save_json, sha256_text, utc_now)

STAGE = "extract_group"
DIR_TO_ROT = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}
LIST_RE = re.compile(r"^\s*(\d{1,2}[\.\)]|[a-z]\)|[•·▪–\-\*]\s|[①-⑳])")
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
            lines.append({"bbox": [round(v, 2) for v in ln["bbox"]],
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


def infer_alignment(lines: list, container: list) -> str:
    if len(lines) >= 2:
        lefts = [l["bbox"][0] for l in lines]; rights = [l["bbox"][2] for l in lines]
        centers = [(a + b) / 2 for a, b in zip(lefts, rights)]
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
    for i, r in enumerate(runs):
        r.pop("_key")
        r["role"] = ("label" if i == 0 and r["bold"] and len(runs) > 1
                     and r["text"].rstrip().endswith(":")
                     else "emphasis" if r["bold"] and i > 0 else "body")
    if runs and not any(r["role"] == "label" for r in runs):
        runs[0]["role"] = "body"
    return runs


def make_region(page_no: int, rtype: str, lines: list, confidence: float) -> dict:
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
                reg["container"] = [round(cu.x0 + 0.5, 2), round(cu.y0 + 0.5, 2),
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

        # 5) container + alignment + id
        obstacles_all = img_boxes + draw_boxes
        for idx, reg in enumerate(ordered):
            if "container" not in reg:
                others = [r["bbox"] for r in ordered if r is not reg]
                compute_container(reg, others + obstacles_all, list(page.rect), lh)
            reg["alignment"] = infer_alignment(reg["lines"], reg["container"])
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
    meta["determinism"]["layout_model_version"] = LAYOUT_MODEL_VERSION
    job.save(meta)
    save_json(job.p("model", "regions.json"),
              {"generated_at": utc_now(), "layout_model": LAYOUT_MODEL_VERSION,
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
        if job.status() not in ("PREFLIGHTED", "NEEDS_REVIEW"):
            raise BlockingError(f"status {job.status()} — cần PREFLIGHTED "
                                "(hoặc NEEDS_REVIEW cho edit-and-rerender loop §11.5)")
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            extract(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
