"""Stage 7 — Quality gates 1-7: chứng minh translation/layout/resource invariants.

Spec §10. Output: qa/report.json, qa/page_png/*, qa/diffs/*. Cập nhật status
RENDERED → NEEDS_REVIEW | AUTO_QA_PASS. Chạy: python3 qa_gates.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import unicodedata

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

from _common import (BlockingError, Job, authenticity_cfg, authenticity_check,
                     exit_blocking, load_json, make_issue, save_json, utc_now)
from preflight import merge_rects

STAGE = "qa"
WS_RE = re.compile(r"\s+")


def norm(s: str) -> str:
    return WS_RE.sub(" ", unicodedata.normalize("NFC", s)).strip()


def rect_of(fr_line: dict, size: float) -> pymupdf.Rect:
    x0 = min(s["x"] for s in fr_line["segments"])
    x1 = max(s["x"] + s["width"] for s in fr_line["segments"])
    return pymupdf.Rect(x0, fr_line["y"] - 0.85 * size, x1, fr_line["y"] + 0.3 * size)


def run_gates(job: Job) -> None:
    cfg = job.config
    model = load_json(job.p("model", "regions.json"))
    manifest = load_json(job.p("render", "render_manifest.json"))
    resource = load_json(job.p("model", "resource_manifest.json"))
    if not (model and manifest and resource):
        raise BlockingError("thiếu regions/render_manifest/resource_manifest — chạy các stage trước")
    regions = {r["region_id"]: r for r in model["regions"]}
    painted = manifest["regions"]
    painted_pages = sorted({r["page"] for r in painted})

    src = pymupdf.open(job.source_pdf)
    draft = pymupdf.open(job.p("render", "draft.pdf"))
    qa_cfg = cfg["qa"]
    issues: list[dict] = []
    gates: dict[str, dict] = {}

    def gi(code, sev, detail, page=None, region_id=None):
        issues.append(make_issue(code, sev, STAGE, detail, page=page, region_id=region_id))

    # ── Gate 1: decision coverage (spec §10.1) ──
    n_pending = sum(1 for r in regions.values() if r["translation_action"] == "pending")
    n_manual = sum(1 for r in regions.values() if r["translation_action"] == "manual")
    n_untranslated = sum(1 for r in regions.values()
                         if r["translation_action"] == "translate" and not r.get("target_runs"))
    if n_pending:
        gi("G1_PENDING_ACTION", "P1", f"{n_pending} regions chưa có action")
    if n_untranslated:
        gi("G1_MISSING_TARGET", "P1", f"{n_untranslated} translate-regions chưa có bản dịch")
    if n_manual:
        gi("G1_MANUAL_UNRESOLVED", "P1", f"{n_manual} manual regions chưa xử lý")
    gates["g1_decision"] = {"pass": not (n_pending or n_untranslated or n_manual),
                            "pending": n_pending, "untranslated": n_untranslated,
                            "manual": n_manual}

    # ── Gate 2: translation integrity (spec §10.2) + authenticity ──
    v_issues = load_json(job.p("model", "validate_issues.json"), [])
    v_p1 = [i for i in v_issues if i["severity"] in ("P0", "P1")]
    # Defense-in-depth với validator: đo lại trực tiếp trên regions.json —
    # region đáng dịch mà target trùng source / không phải target-lang.
    auth = authenticity_cfg(cfg)
    target_lang = cfg["languages"]["target"]
    translated = [r for r in regions.values()
                  if r["translation_action"] == "translate" and r.get("target_text")]
    same, lang_bad = [], []
    for r in translated:
        flag = authenticity_check(r["source_text"], r["target_text"],
                                  target_lang, auth["min_words"])
        if flag == "identical":
            same.append(r)
        elif flag == "lang_suspect":
            lang_bad.append(r)
    for r in same[:20]:
        gi("TRANSLATION_IDENTICAL", "P1", "region đáng dịch nhưng target trùng source",
           page=r["page"], region_id=r["region_id"])
    for r in lang_bad[:20]:
        gi("TARGET_LANG_SUSPECT", "P1", f"target không phải tiếng {target_lang}",
           page=r["page"], region_id=r["region_id"])
    n_tr = max(1, len(translated))
    cover_fail = len(same) / n_tr > auth["identical_ratio_max"] \
        or len(lang_bad) / n_tr > auth["lang_suspect_ratio_max"]
    if cover_fail:
        gi("TRANSLATION_COVERAGE_FAIL", "P0",
           f"pseudo-translation: identical={len(same)}/{n_tr} "
           f"lang_suspect={len(lang_bad)}/{n_tr} vượt ngưỡng "
           f"{auth['identical_ratio_max']:.0%} — stage 4 phải do model dịch thật, "
           "P0 không waive được")
    gates["g2_translation"] = {"pass": not v_p1 and not cover_fail,
                               "validate_p1": len(v_p1), "identical": len(same),
                               "lang_suspect": len(lang_bad)}

    # ── Gate 3: rendered-text coverage (spec §10.3) ──
    g3_fail = 0
    for pr in painted:
        reg = regions[pr["region_id"]]
        clip = pymupdf.Rect(reg["container"]) + (-2, -2, 2, 2)
        got = norm(draft[reg["page"]].get_text("text", clip=clip))
        want = norm(reg["target_text"])
        if want and want not in got:
            g3_fail += 1
            gi("G3_TARGET_NOT_FOUND", "P0", f"target không thấy trong output: {want[:60]!r}",
               page=reg["page"], region_id=reg["region_id"])
    for r in regions.values():
        if r["translation_action"] == "keep" and r["page"] in painted_pages \
                and r["source_text"].strip():
            clip = pymupdf.Rect(r["container"]) + (-2, -2, 2, 2)
            got = norm(draft[r["page"]].get_text("text", clip=clip))
            if norm(r["source_text"]) not in got:
                g3_fail += 1
                gi("G3_KEEP_LOST", "P0", f"keep-region mất text: {r['source_text'][:50]!r}",
                   page=r["page"], region_id=r["region_id"])
    for pno in painted_pages:
        ptxt = draft[pno].get_text("text")
        if "�" in ptxt:
            g3_fail += 1
            gi("G3_TOFU", "P0", "phát hiện U+FFFD trong output", page=pno)
        if unicodedata.normalize("NFC", ptxt) != ptxt:
            gi("G3_NOT_NFC", "P1", "text output không ở NFC", page=pno)
    src_fonts = {f[3] for p in range(src.page_count) for f in src.get_page_fonts(p)}
    for pno in painted_pages:
        for f in draft.get_page_fonts(pno):
            if f[3] not in src_fonts and f[1] == "n/a":
                g3_fail += 1
                gi("G3_FONT_NOT_EMBEDDED", "P0", f"font mới {f[3]} không embed", page=pno)
    gates["g3_rendered_text"] = {"pass": g3_fail == 0, "checked": len(painted)}

    # ── Gate 4: geometry & collision (spec §10.4) ──
    g4_fail = 0
    if src.page_count != draft.page_count:
        g4_fail += 1
        gi("G4_PAGE_COUNT", "P0", f"{src.page_count} → {draft.page_count}")
    for pno in range(min(src.page_count, draft.page_count)):
        a, b = src[pno], draft[pno]
        if list(a.mediabox) != list(b.mediabox) or a.rotation != b.rotation:
            g4_fail += 1
            gi("G4_PAGE_BOX", "P0", "mediabox/rotation thay đổi", page=pno)
    floor = cfg["fonts"]["minimum_ratio"]
    for pr in painted:
        if pr["ratio"] < floor - 1e-6:
            g4_fail += 1
            gi("G4_RATIO_FLOOR", "P0", f"ratio {pr['ratio']:.2%} dưới hard floor",
               page=pr["page"], region_id=pr["region_id"])
        reg = regions[pr["region_id"]]
        fr = reg.get("fit_result") or {}
        cont = pymupdf.Rect(reg["container"]) + (-1.5, -1.5, 1.5, 1.5)
        for line in fr.get("lines", []):
            lr = rect_of(line, fr["size"])
            if reg["rotation"] == 0 and not cont.contains(lr):
                g4_fail += 1
                gi("G4_OUT_OF_CONTAINER", "P1", f"line vượt container {list(lr)}",
                   page=pr["page"], region_id=pr["region_id"])
    for pno in painted_pages:
        line_rects = []
        for pr in [p for p in painted if p["page"] == pno]:
            fr = regions[pr["region_id"]].get("fit_result") or {}
            line_rects += [(pr["region_id"], rect_of(l, fr["size"])) for l in fr.get("lines", [])]
        other = [(r["region_id"], span_r) for r in model["regions"]
                 if r["page"] == pno and not (r["translation_action"] == "translate"
                                              and r.get("fit_result"))
                 for ln in r["lines"] for span_r in [pymupdf.Rect(
                     [c for c in ln["bbox"]])]]
        for rid, lr in line_rects:
            for oid, orect in other:
                inter = lr & orect
                if not inter.is_empty and abs(inter) > 1.0 and regions[rid]["rotation"] == 0:
                    g4_fail += 1
                    gi("G4_COLLISION", "P1", f"đè lên region giữ nguyên {oid[:24]}",
                       page=pno, region_id=rid)
                    break
    gates["g4_geometry"] = {"pass": g4_fail == 0}

    # ── Gate 5: image/vector/link preservation (spec §10.5) ──
    g5_fail = 0
    for pno in range(draft.page_count):
        want_imgs = [(i["digest"], i["bbox"]) for i in resource["pages"][pno]["images"]]
        have_imgs = [((i.get("digest").hex() if isinstance(i.get("digest"), (bytes, bytearray))
                       else str(i.get("digest"))), list(i["bbox"]))
                     for i in draft[pno].get_image_info(hashes=True, xrefs=True)]
        # match theo digest + bbox tolerance 1pt — đẳng thức int flaky tại biên .5
        used = [False] * len(have_imgs)
        missing_fatal = 0
        for wd, wb in want_imgs:
            hit = next((k for k, (hd, hb) in enumerate(have_imgs)
                        if not used[k] and hd == wd
                        and max(abs(a - b) for a, b in zip(wb, hb)) <= 1.0), None)
            if hit is not None:
                used[hit] = True
                continue
            # Placement mất theo inventory — phán quyết bằng visible-pixel proof:
            # apply_redactions rewrite content có thể cull placement ngoài vùng
            # nhìn thấy; spec Gate 5 bảo vệ "visible images", không phải xref.
            vis = pymupdf.Rect(wb) & draft[pno].rect
            if vis.is_empty or abs(vis) < 4:
                gi("G5_OFFPAGE_PLACEMENT_CULLED", "P2",
                   f"placement ngoài trang bị cull khi rewrite: {[round(v) for v in wb]}",
                   page=pno)
                continue
            # cùng DPI với Gate 6 — downsample khuếch đại nhiễu rìa re-encode
            proof_dpi = qa_cfg["render_dpi"]
            ps = src[pno].get_pixmap(clip=vis, dpi=proof_dpi, alpha=False)
            pd = draft[pno].get_pixmap(clip=vis, dpi=proof_dpi, alpha=False)
            if (ps.width, ps.height) == (pd.width, pd.height):
                a = np.frombuffer(ps.samples, np.uint8).reshape(ps.height, ps.width, ps.n)
                b = np.frombuffer(pd.samples, np.uint8).reshape(pd.height, pd.width, pd.n)
                dmask = (np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
                         > qa_cfg["diff_pixel_delta"])
                # exclude text/mask zones như G6 — spec Gate 5: "ngoài text masks"
                pinfo = manifest["pages"].get(str(pno), {})
                sc = proof_dpi / 72.0
                halo_px = qa_cfg["mask_halo_pt"] * sc
                for rect in pinfo.get("mask_rects", []) + pinfo.get("text_rects", []):
                    rx0 = (rect[0] - vis.x0) * sc - halo_px
                    ry0 = (rect[1] - vis.y0) * sc - halo_px
                    rx1 = (rect[2] - vis.x0) * sc + halo_px
                    ry1 = (rect[3] - vis.y0) * sc + halo_px
                    dmask[max(0, int(ry0)):max(0, int(ry1) + 1),
                          max(0, int(rx0)):max(0, int(rx1) + 1)] = False
                # cùng meaningful criterion với Gate 6: tile-fraction, không phải
                # any-pixel — re-encode ảnh gây nhiễu rìa thưa dưới ngưỡng thị giác
                t = qa_cfg["diff_tile_px"]
                visually_same = True
                for ty in range(dmask.shape[0] // t + 1):
                    for tx in range(dmask.shape[1] // t + 1):
                        blk = dmask[ty * t:(ty + 1) * t, tx * t:(tx + 1) * t]
                        if blk.size and blk.mean() > qa_cfg["diff_tile_fraction"]:
                            visually_same = False
                            break
                    if not visually_same:
                        break
            else:
                visually_same = False
            if visually_same:
                gi("G5_PLACEMENT_DROPPED_INVISIBLE", "P2",
                   f"placement mất nhưng vùng nhìn thấy không đổi: {[round(v) for v in wb]}",
                   page=pno)
            else:
                missing_fatal += 1
        if missing_fatal:
            g5_fail += 1
            gi("G5_IMAGE_CHANGED", "P0", f"{missing_fatal} ảnh mất/đổi vị trí", page=pno)
        want_dc = resource["pages"][pno]["draw_clusters"]
        have_dc = merge_rects([d["rect"] for d in draft[pno].get_drawings()])
        if len(want_dc) != len(have_dc):
            g5_fail += 1
            gi("G5_VECTOR_CLUSTERS", "P1",
               f"draw clusters {len(want_dc)} → {len(have_dc)}", page=pno)
        want_links = {(l.get("kind"), str(l.get("uri", l.get("page"))))
                      for l in resource["pages"][pno]["links"]}
        have_links = {(l.get("kind"), str(l.get("uri", l.get("page"))))
                      for l in draft[pno].get_links()}
        if want_links - have_links:
            g5_fail += 1
            gi("G5_LINK_LOST", "P1", f"mất link: {want_links - have_links}", page=pno)
    gates["g5_resources"] = {"pass": g5_fail == 0}

    # ── Gate 6: visual verification (spec §10.6) ──
    dpi = qa_cfg["render_dpi"]
    scale = dpi / 72.0
    tile = qa_cfg["diff_tile_px"]
    halo = qa_cfg["mask_halo_pt"] * scale
    g6_fail = 0
    for pno in range(draft.page_count):
        sp = src[pno].get_pixmap(dpi=dpi, alpha=False)
        dp = draft[pno].get_pixmap(dpi=dpi, alpha=False)
        if pno not in painted_pages:
            # md5 fast-path; nếu lệch, chỉ flag khi vượt ngưỡng "meaningful"
            # (render noise delta≤1 do cache state không phải corruption)
            if hashlib.md5(sp.samples).digest() != hashlib.md5(dp.samples).digest():
                a = np.frombuffer(sp.samples, np.uint8).reshape(sp.height, sp.width, sp.n)
                b = np.frombuffer(dp.samples, np.uint8).reshape(dp.height, dp.width, dp.n)
                if a.shape != b.shape or (np.abs(a.astype(np.int16) - b.astype(np.int16))
                                          .max(axis=2) > qa_cfg["diff_pixel_delta"]).any():
                    g6_fail += 1
                    gi("G6_UNEXPECTED_DIFF", "P1",
                       "trang không paint nhưng pixel khác vượt ngưỡng", page=pno)
            continue
        sa = np.frombuffer(sp.samples, np.uint8).reshape(sp.height, sp.width, sp.n)
        da = np.frombuffer(dp.samples, np.uint8).reshape(dp.height, dp.width, dp.n)
        if sa.shape != da.shape:
            g6_fail += 1
            gi("G6_SIZE_MISMATCH", "P0", f"pixmap {sa.shape} vs {da.shape}", page=pno)
            continue
        diff = (np.abs(sa.astype(np.int16) - da.astype(np.int16)).max(axis=2)
                > qa_cfg["diff_pixel_delta"])
        excl = np.zeros(diff.shape, bool)
        pinfo = manifest["pages"].get(str(pno), {})
        for rect in pinfo.get("mask_rects", []) + pinfo.get("text_rects", []):
            x0, y0, x1, y1 = [v * scale for v in rect]
            excl[max(0, int(y0 - halo)):int(y1 + halo) + 1,
                 max(0, int(x0 - halo)):int(x1 + halo) + 1] = True
        flag = diff & ~excl
        th, tw = flag.shape[0] // tile + 1, flag.shape[1] // tile + 1
        bad_tiles = []
        for ty in range(th):
            for tx in range(tw):
                blk = flag[ty * tile:(ty + 1) * tile, tx * tile:(tx + 1) * tile]
                if blk.size and blk.mean() > qa_cfg["diff_tile_fraction"]:
                    bad_tiles.append((tx, ty))
        sp.save(job.p("qa", "page_png", f"source_p{pno:02d}.png"))
        dp.save(job.p("qa", "page_png", f"draft_p{pno:02d}.png"))
        img = Image.frombytes("RGB", (dp.width, dp.height), dp.samples).convert("RGB")
        dr = ImageDraw.Draw(img)
        clusters = merge_rects([[tx * tile, ty * tile, (tx + 1) * tile, (ty + 1) * tile]
                                for tx, ty in bad_tiles], tol=2)
        for cb in clusters[:20]:
            dr.rectangle(cb, outline=(255, 0, 0), width=4)
        img.save(job.p("qa", "diffs", f"diff_p{pno:02d}.png"))
        for cb in clusters[:8]:
            g6_fail += 1
            gi("G6_DIFF_OUTSIDE_MASK", "P1",
               f"pixel diff ngoài mask tại px{[round(v) for v in cb]}", page=pno)
        # small text → render thêm 600 DPI cho reviewer (spec §10.6)
        min_size = min((s["size"] for r in model["regions"] if r["page"] == pno
                        for l in r["lines"] for s in l["spans"]), default=99)
        if min_size < qa_cfg["small_text_pt"] or clusters:
            draft[pno].get_pixmap(dpi=qa_cfg["flagged_render_dpi"], alpha=False).save(
                job.p("qa", "page_png", f"draft600_p{pno:02d}.png"))
    gates["g6_visual"] = {"pass": g6_fail == 0, "dpi": dpi}

    # ── Gate 7: structural validation (spec §10.7) ──
    g7_fail = 0
    if draft.is_encrypted:
        g7_fail += 1
        gi("G7_ENCRYPTED", "P0", "output bị encrypted ngoài dự kiến")
    for pno in range(draft.page_count):
        for a in draft[pno].annots() or []:
            if a.type[0] == pymupdf.PDF_ANNOT_REDACT:
                g7_fail += 1
                gi("G7_REDACT_LEFTOVER", "P0", "còn redact annot chưa apply", page=pno)
    size_ratio = os.path.getsize(job.p("render", "draft.pdf")) / os.path.getsize(job.source_pdf)
    if size_ratio > qa_cfg["output_size_budget_ratio"]:
        gi("G7_SIZE_BUDGET", "P2", f"output/source = {size_ratio:.2f}x vượt budget")
    gates["g7_structural"] = {"pass": g7_fail == 0, "size_ratio": round(size_ratio, 2)}

    src.close(); draft.close()

    # ── aggregate & verdict (spec §10.8) ──
    prior = []
    for name, path in (("preflight", "model/preflight.json"),):
        d = load_json(job.p(*path.split("/")))
        prior += (d or {}).get("issues", [])
    prior += load_json(job.p("model", "regions_issues.json"), [])
    prior += load_json(job.p("model", "validate_issues.json"), [])
    prior += (load_json(job.p("render", "render_manifest.json")) or {}).get("issues", [])
    all_issues = prior + issues
    sev = {s: sum(1 for i in all_issues if i["severity"] == s) for s in ("P0", "P1", "P2")}
    partial = manifest.get("partial", False)
    result = "AUTO_QA_PASS" if (sev["P0"] == 0 and sev["P1"] == 0 and not partial) \
        else "NEEDS_REVIEW"
    save_json(job.p("qa", "report.json"),
              {"generated_at": utc_now(), "gates": gates, "issues": issues,
               "severity_all": sev, "partial": partial, "result": result})
    job.mark_stage(STAGE)
    if job.status() == "RENDERED":
        job.set_status(result, f"P0={sev['P0']} P1={sev['P1']} P2={sev['P2']}")
    nxt = ("`approve.py --job <job> --approver <tên>` (bắt buộc human approval)"
           if result == "AUTO_QA_PASS" else
           "Reviewer xem qa/page_png + qa/diffs + issues; sửa bản dịch qua responses.jsonl "
           "→ validate → fit_paint → qa lại. KHÔNG thể approve khi còn P0/P1.")
    job.write_summary(nxt)
    print(f"qa_gates: {result} | P0={sev['P0']} P1={sev['P1']} P2={sev['P2']} | "
          f"gates: {', '.join(k for k, v in gates.items() if not v['pass']) or 'all pass'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            run_gates(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
