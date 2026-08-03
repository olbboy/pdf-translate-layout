"""Stage 6 — Fit + safe paint: font resolve, constraint fitting, redact, insert, save.

Spec §6.8-6.10, §7, §8, §9. Output: render/draft.pdf, render/render_manifest.json.
Chạy: python3 fit_paint.py --job <job_dir> [--pages 0,1,2] [--allow-partial]
"""

from __future__ import annotations

import argparse
import os
import re
import statistics

import pymupdf

from _common import (FONTS_DIR, BlockingError, Job, exit_blocking, load_json, make_issue,
                     save_json, utc_now)

STAGE = "fit_paint"
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")
SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
# Family quen thuộc — style-class mapping đáng tin; ngoài list = display font
# → review trigger theo spec §11.4.
KNOWN_FAMILIES = ("arial", "helvetica", "times", "courier", "noto", "roboto",
                  "calibri", "cambria", "georgia", "verdana", "tahoma", "segoe",
                  "songti", "adobesong", "liberation", "dejavu")


# ── font resolver (spec §7) ─────────────────────────────────────────────

class FontPack:
    def __init__(self):
        mf = load_json(os.path.join(FONTS_DIR, "fonts_manifest.json"))
        if not mf:
            raise BlockingError("fonts_manifest.json thiếu — font pack chưa bundle (spec §7.2)")
        self.entries = mf["fonts"]
        self._cache: dict[str, pymupdf.Font] = {}
        self._alias: dict[str, str] = {}

    def key_for(self, style: dict) -> tuple[str, list[dict]]:
        """→ (fontkey, issues). Map style class → bundle face, degrade có ghi nhận."""
        fam = "mono" if style.get("mono") else "serif" if style.get("serif") else "sans"
        variant = (("bolditalic" if style.get("italic") else "bold") if style.get("bold")
                   else ("italic" if style.get("italic") else "regular"))
        issues = []
        for cand in (f"{fam}-{variant}",
                     f"{fam}-bold" if "bold" in variant else f"{fam}-regular",
                     f"{fam}-regular", "sans-regular"):
            if cand in self.entries:
                if cand != f"{fam}-{variant}":
                    issues.append(("STYLE_DEGRADED", f"{fam}-{variant} → {cand}"))
                return cand, issues
        raise BlockingError(f"font pack không có face nào cho {fam}-{variant}")

    def font(self, key: str) -> pymupdf.Font:
        if key not in self._cache:
            self._cache[key] = pymupdf.Font(fontfile=self.path(key))
        return self._cache[key]

    def path(self, key: str) -> str:
        return os.path.join(FONTS_DIR, self.entries[key]["file"])

    def alias(self, key: str) -> str:
        if key not in self._alias:
            self._alias[key] = f"NF{len(self._alias)}"
        return self._alias[key]

    def cover(self, key: str, text: str) -> str | None:
        """Font đầu tiên trong chain phủ hết text; None nếu không có (→ blocking)."""
        chain = [key] + [k for k in ("sans-regular", "serif-regular", "mono-regular")
                         if k != key and k in self.entries]
        for k in chain:
            f = self.font(k)
            if all(ch in ("\n", "\t", " ") or f.has_glyph(ord(ch)) for ch in text):
                return k
        return None


# ── fitting (spec §6.8, §8) ─────────────────────────────────────────────

def tokenize(reg: dict) -> list[dict]:
    """target_runs (placeholder-form) → tokens atomic đã expand, giữ role.

    "\n" trong target = explicit line break (spec §11.2): token đầu của
    dòng sau mang br=True để fitter ép xuống dòng tại đó.
    """
    mapping = reg.get("placeholders", {})
    tokens = []
    for run in reg["target_runs"]:
        for li, seg in enumerate(run["text"].split("\n")):
            first = True
            for raw in seg.split(" "):
                if raw == "":
                    continue
                expanded = PH_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), raw)
                if expanded.strip():
                    tokens.append({"text": expanded, "role": run["role"],
                                   "br": li > 0 and first})
                    first = False
    return tokens


def wrap_lines(widths: list[float], space_w: float, max_w: float) -> list[list[int]] | None:
    """Greedy wrap token indices theo width; None nếu một token > max_w."""
    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(widths):
        if w > max_w + 0.1:
            return None
        add = w if not cur else w + space_w
        if cur and cur_w + add > max_w + 0.1:
            lines.append(cur)
            cur, cur_w = [i], w
        else:
            cur.append(i)
            cur_w += add
    if cur:
        lines.append(cur)
    return lines


def role_style(reg: dict, role: str) -> dict:
    for r in reg["runs"]:
        if r["role"] == role:
            return r
    return reg["runs"][0]


def fit_region(reg: dict, pack: FontPack, cfg: dict) -> tuple[dict | None, list]:
    """→ (fit_result, issues). None nếu không có layout hợp lệ (fail-closed)."""
    issues = []
    tokens = tokenize(reg)
    if not tokens:
        return None, [("EMPTY_TOKENS", "P1", "target không có token")]

    for fname in {SUBSET_PREFIX_RE.sub("", r["font"]) for r in reg["runs"]}:
        if fname and not any(k in fname.lower() for k in KNOWN_FAMILIES):
            issues.append(("FONT_DISPLAY_FALLBACK", "P1",
                           f"display font {fname!r} map sang bundle theo style class — "
                           "reviewer xác nhận (spec §11.4)"))
            break

    src_sizes = [r["size"] for r in reg["runs"] for _ in r["text"]]
    src_size = statistics.median(src_sizes) if src_sizes else reg["runs"][0]["size"]
    floor = src_size * cfg["fonts"]["minimum_ratio"]
    c = reg["container"]
    cw, chh = c[2] - c[0], c[3] - c[1]
    if reg["rotation"] in (90, 270):
        cw, chh = chh, cw  # reading-direction extent

    # resolve font/coverage per token
    tok_font: list[str] = []
    for t in tokens:
        base_key, deg = pack.key_for(role_style(reg, t["role"]))
        for code, det in deg:
            issues.append((code, "P2", det))
        k = pack.cover(base_key, t["text"])
        if k is None:
            bad = [ch for ch in t["text"] if pack.cover("sans-regular", ch) is None][:5]
            return None, issues + [("FONT_GLYPH_MISSING", "P1",
                                    f"không font nào trong pack có glyph: {bad!r}")]
        if k != base_key:
            issues.append(("FONT_FALLBACK_SUBRUN", "P2", f"{t['text'][:12]!r}: {base_key}→{k}"))
        tok_font.append(k)

    # leading nguồn (baseline-to-baseline) nếu multi-line
    origins = [l["spans"][0]["origin"][1] for l in reg["lines"]]
    if len(origins) >= 2:
        deltas = [b - a for a, b in zip(origins, origins[1:]) if b - a > 1]
        leading_ratio = (statistics.median(deltas) / src_size) if deltas else 1.15
    else:
        leading_ratio = 1.15
    leading_ratio = max(1.02, leading_ratio)
    single_line_src = len(reg["lines"]) == 1

    def layout_at(s: float):
        widths = [pack.font(k).text_length(t["text"], fontsize=s)
                  for t, k in zip(tokens, tok_font)]
        space_w = pack.font(tok_font[0]).text_length(" ", fontsize=s)
        # wrap từng đoạn giữa các explicit break rồi ghép
        segments, cur = [], []
        for i, t in enumerate(tokens):
            if t.get("br") and cur:
                segments.append(cur)
                cur = []
            cur.append(i)
        segments.append(cur)
        lines = []
        for seg in segments:
            sub = wrap_lines([widths[i] for i in seg], space_w, cw)
            if sub is None:
                return None
            lines += [[seg[j] for j in line] for line in sub]
        n = len(lines)
        max_lines = max(1, int(chh // (leading_ratio * s)))
        if single_line_src and n > max_lines:
            return None
        if n * leading_ratio * s > chh + 0.6 * s:  # descent tolerance
            return None
        return {"lines": lines, "widths": widths, "space_w": space_w}

    lo, hi, best = floor, src_size, None
    if layout_at(hi):
        best, s_fit = layout_at(hi), hi
    else:
        s_fit = None
        for _ in range(24):  # binary search max size thỏa constraints (spec §6.8)
            mid = (lo + hi) / 2
            if layout_at(mid):
                lo, best, s_fit = mid, layout_at(mid), mid
            else:
                hi = mid
            if hi - lo < 0.05:
                break
    if best is None:
        return None, issues + [("FIT_IMPOSSIBLE", "P1",
                                f"không fit được trong container ngay tại floor "
                                f"{cfg['fonts']['minimum_ratio']:.0%} (src {src_size}pt)")]

    ratio = s_fit / src_size
    if ratio < cfg["fonts"]["review_below_ratio"]:
        code = "FONT_RATIO_HARD" if ratio < 0.90 else "FONT_RATIO_REVIEW"
        issues.append((code, "P1", f"ratio={ratio:.2%} (src {src_size}pt → {s_fit:.2f}pt)"))

    # dựng line segments với alignment + sub-run theo font
    base_x, base_y = reg["lines"][0]["spans"][0]["origin"]
    leading = leading_ratio * s_fit
    out_lines = []
    for li, idxs in enumerate(best["lines"]):
        lw = sum(best["widths"][i] for i in idxs) + best["space_w"] * (len(idxs) - 1)
        if reg["alignment"] == "center":
            x = c[0] + (cw - lw) / 2 if reg["rotation"] == 0 else base_x
        elif reg["alignment"] == "right":
            x = c[2] - lw if reg["rotation"] == 0 else base_x
        else:
            x = base_x if reg["rotation"] == 0 else base_x
        y = base_y + li * leading
        segs, cx = [], x
        cur = None
        for i in idxs:
            t, k, w = tokens[i], tok_font[i], best["widths"][i]
            color = role_style(reg, t["role"])["color"]
            if cur and cur["font"] == k and cur["color"] == color:
                cur["text"] += " " + t["text"]
                cur["width"] += best["space_w"] + w
            else:
                cur = {"x": cx, "text": t["text"], "font": k, "color": color, "width": w}
                segs.append(cur)
            cx = cur["x"] + cur["width"] + best["space_w"]
        out_lines.append({"y": round(y, 2), "x": round(x, 2), "width": round(lw, 2),
                          "segments": [{k2: (round(v, 2) if isinstance(v, float) else v)
                                        for k2, v in s2.items()} for s2 in segs]})
    if reg["rotation"] in (90, 270) and len(out_lines) > 1:
        return None, issues + [("ROTATED_MULTILINE", "P1",
                                "text xoay nhiều dòng chưa hỗ trợ v1 — needs review")]
    return {"size": round(s_fit, 2), "src_size": round(src_size, 2),
            "ratio": round(ratio, 4), "leading": round(leading, 2),
            "alignment": reg["alignment"], "rotation": reg["rotation"],
            "lines": out_lines}, issues


# ── safe painting (spec §9) ─────────────────────────────────────────────

def span_mask(span: dict, pad: float) -> pymupdf.Rect:
    b = span["bbox"]
    return pymupdf.Rect(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)


def build_masks(reg: dict, protected: list[pymupdf.Rect], cfg: dict) -> tuple[list, list]:
    """Mask cho từng span; pad co dần nếu chạm text được giữ (spec §9.1)."""
    issues, rects = [], []
    rc = cfg["render"]
    for line in reg["lines"]:
        for span in line["spans"]:
            pad0 = min(max(rc["mask_pad_ratio"] * span["size"], rc["mask_pad_min_pt"]),
                       rc["mask_pad_max_pt"])
            rect = None
            for pad in (pad0, pad0 / 2, 0.05, 0.0):
                cand = span_mask(span, pad)
                if not any(cand.intersects(p) for p in protected):
                    rect = cand
                    break
            if rect is None:
                # char-level: bỏ các char giao vùng bảo vệ khỏi mask → conflict
                issues.append(("MASK_CONFLICT", "P1",
                               f"mask span {span['text'][:16]!r} chạm text giữ nguyên"))
                return [], issues
            rects.append(rect)
    return rects, issues


def paint(job: Job, pages_filter: set[int] | None, allow_partial: bool) -> None:
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json")
    regions = model["regions"]
    cfg = job.config
    pack = FontPack()
    pymupdf.TOOLS.set_small_glyph_heights(True)  # giảm bbox glyph khi redact (spec §9.1)

    paintable = [r for r in regions if r["translation_action"] == "translate"
                 and r.get("target_runs")
                 and (pages_filter is None or r["page"] in pages_filter)]
    pending = [r for r in regions if r["translation_action"] == "translate"
               and not r.get("target_runs")]
    if not paintable:
        raise BlockingError("không có region nào đủ điều kiện paint (target_runs trống)")
    if pending and not allow_partial:
        raise BlockingError(f"{len(pending)} region chưa có bản dịch — dùng --allow-partial "
                            "cho dev run (job sẽ không thể release)")

    issues: list[dict] = []
    manifest = {"generated_at": utc_now(), "partial": bool(pending or pages_filter),
                "pages": {}, "regions": [], "skipped": [], "issues": issues}

    doc = pymupdf.open(job.source_pdf)
    by_page: dict[int, list[dict]] = {}
    for r in paintable:
        by_page.setdefault(r["page"], []).append(r)

    for pno, regs in sorted(by_page.items()):
        page = doc[pno]
        links_before = page.get_links()

        fitted: list[tuple[dict, dict]] = []
        for reg in regs:
            fr, fissues = fit_region(reg, pack, cfg)
            for code, sev, det in fissues:
                issues.append(make_issue(code, sev, STAGE, det,
                                         page=pno, region_id=reg["region_id"]))
            if fr is None:
                manifest["skipped"].append({"region_id": reg["region_id"],
                                            "reason": fissues[-1][0] if fissues else "?"})
                continue
            reg["fit_result"] = fr
            fitted.append((reg, fr))
        if not fitted:
            continue

        painted_ids = {reg["region_id"] for reg, _ in fitted}
        protected = [span_mask(s, 0.0) for r in regions
                     if r["page"] == pno and r["region_id"] not in painted_ids
                     for l in r["lines"] for s in l["spans"]]

        page_masks: list[pymupdf.Rect] = []
        ok_regions: list[tuple[dict, dict]] = []
        for reg, fr in fitted:
            rects, missues = build_masks(reg, protected, cfg)
            for code, sev, det in missues:
                issues.append(make_issue(code, sev, STAGE, det,
                                         page=pno, region_id=reg["region_id"]))
            if not rects:
                manifest["skipped"].append({"region_id": reg["region_id"],
                                            "reason": "MASK_CONFLICT"})
                continue
            page_masks += rects
            ok_regions.append((reg, fr))
        if not ok_regions:
            continue

        for rect in page_masks:
            page.add_redact_annot(rect, fill=False)  # no-fill: giữ background (spec §9.2)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)

        for reg, fr in ok_regions:
            for line in fr["lines"]:
                for seg in line["segments"]:
                    col = seg["color"]
                    rgb = (((col >> 16) & 255) / 255, ((col >> 8) & 255) / 255, (col & 255) / 255)
                    try:
                        rv = page.insert_text(
                            pymupdf.Point(seg["x"], line["y"]), seg["text"],
                            fontsize=fr["size"], fontname=pack.alias(seg["font"]),
                            fontfile=pack.path(seg["font"]), color=rgb,
                            rotate=fr["rotation"])
                        if isinstance(rv, (int, float)) and rv < 0:
                            raise RuntimeError(f"insert_text rv={rv}")
                    except Exception as e:  # mọi insertion failure là blocking (spec §9.3)
                        issues.append(make_issue("INSERTION_FAILED", "P0", STAGE,
                                                 f"{e}", page=pno, region_id=reg["region_id"]))
            manifest["regions"].append({
                "region_id": reg["region_id"], "page": pno, **{k: fr[k] for k in
                ("size", "src_size", "ratio", "alignment", "rotation")},
                "line_count": len(fr["lines"]),
                "fonts": sorted({s["font"] for l in fr["lines"] for s in l["segments"]}),
            })

        # link preservation (spec §9.4)
        if cfg["render"]["preserve_links"]:
            after = page.get_links()
            def lkey(l):
                fr_ = l.get("from")
                return (l.get("kind"), l.get("uri", l.get("page")),
                        tuple(round(v) for v in (fr_.x0, fr_.y0, fr_.x1, fr_.y1)) if fr_ else ())
            have = {lkey(l) for l in after}
            restored = 0
            for l in links_before:
                if lkey(l) not in have:
                    try:
                        page.insert_link(l)
                        restored += 1
                    except Exception as e:
                        issues.append(make_issue("LINK_RESTORE_FAILED", "P1", STAGE,
                                                 str(e), page=pno))
            if restored:
                issues.append(make_issue("LINKS_RESTORED", "P2", STAGE,
                                         f"khôi phục {restored} link sau redaction", page=pno))

        manifest["pages"][str(pno)] = {
            "painted_regions": len(ok_regions),
            "mask_rects": [[round(v, 2) for v in (m.x0, m.y0, m.x1, m.y1)]
                           for m in page_masks],
            # 1.3/0.45 em: bao cả dấu chồng tiếng Việt (Ầ, Ễ) và descender
            "text_rects": [[round(v, 2) for v in (
                min(s["x"] for s in l["segments"]),
                l["y"] - 1.3 * fr2["size"],
                max(s["x"] + s["width"] for s in l["segments"]),
                l["y"] + 0.45 * fr2["size"])]
                for _, fr2 in ok_regions for l in fr2["lines"]],
        }

    # optimized save (spec §6.10) — native subsetting, không cần fontTools
    try:
        doc.subset_fonts(fallback=False)
    except Exception as e:
        issues.append(make_issue("SUBSET_FAILED", "P1", STAGE, str(e)))
    draft = job.p("render", "draft.pdf")
    doc.save(draft, garbage=4, deflate=True, use_objstms=1)
    doc.close()
    check = pymupdf.open(draft)
    if check.page_count != job.load()["page_count"]:
        issues.append(make_issue("PAGE_COUNT_CHANGED", "P0", STAGE,
                                 f"{check.page_count} != {job.load()['page_count']}"))
    check.close()

    save_json(job.p("model", "regions.json"), model)
    save_json(job.p("render", "render_manifest.json"), manifest)
    job.mark_stage(STAGE, "done" if not manifest["partial"] else "partial")
    if job.status() == "TRANSLATED":
        job.set_status("RENDERED")
    n_painted = len(manifest["regions"])
    job.log_event(STAGE, "info", "PAINTED",
                  f"painted={n_painted} skipped={len(manifest['skipped'])}")
    job.write_summary("Chạy `qa_gates.py --job <job>` để chấm quality gates.")
    print(f"fit_paint: painted={n_painted} skipped={len(manifest['skipped'])} "
          f"issues={len(issues)} → {draft}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    ap.add_argument("--pages", help="dev: chỉ paint các trang này, vd 0,1,2")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        pages = set(int(p) for p in args.pages.split(",")) if args.pages else None
        with job.acquire_lock(STAGE):
            paint(job, pages, args.allow_partial)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
