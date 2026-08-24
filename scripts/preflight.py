"""Stage 1 — Preflight: tạo job folder, phân loại supported envelope, resource manifest.

Spec §6.2, §3.2. Output: model/preflight.json, model/resource_manifest.json.
Chạy: python3 preflight.py --pdf <path> [--out jobs] [--domain-context <text|path>]
       [--glossary <csv>] [--customer-facing] [--job <job_dir>]
       [--source-lang en] [--target-lang vi] [--provider-model <model_id>]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

import pymupdf

from _common import (ASSETS_DIR, ENGINE_VERSION, READABLE_RATIO_MIN,
                     BlockingError, Job, layout_model_for,
                     exit_blocking, load_default_config, make_issue, new_job_id, readable_ratio,
                     save_json, sha256_file, sha256_text, utc_now)

AXIS_DIRS = {(1, 0), (0, 1), (-1, 0), (0, -1)}
STAGE = "preflight"

# Bản in "-Q" nhà máy gửi thường đã convert font thành đường vector, nên trang không còn
# text object nào. Phân biệt được với trang sơ đồ thuần vì gần như MỌI path đều bé bằng
# một glyph: đo trên `V16 quick guide final-20251204-Q.pdf` là 105/113, 385/385, 2373/2373.
GLYPH_MAX_PT = 20.0            # một glyph vẽ ra nhỏ hơn ngần này ở cả hai chiều
OUTLINED_GLYPH_SHARE = 0.8     # tỉ lệ path cỡ glyph để kết luận là chữ outline
SIBLING_OPEN_MAX = 12          # số PDF ứng viên được mở ra kiểm, chặn chi phí quét thư mục
SIBLING_MIN_CHARS = 300        # bản thay thế phải có ngần này ký tự mới coi là còn text layer

_VI_OUTPUT = re.compile(r"_VI\.pdf$|-vi-[0-9a-f]{6,}\.pdf$", re.I)


def outlined_glyph_share(drawings: list) -> float:
    """Tỉ lệ path bé bằng một glyph. Cao = chữ đã convert-to-outline, thấp = sơ đồ thật.

    Đo trên corpus: cả 71 trang vector-suspect đều từ 0.90 trở lên, không có trang nào rơi
    vào khoảng giữa. Corpus KHÔNG có ca âm tính nào, nên nửa phân biệt của luật này được
    khoá bằng test tổng hợp trong selftest.py chứ không bằng dữ liệu thật.
    """
    if not drawings:
        return 0.0
    glyphs = sum(1 for dw in drawings
                 if dw["rect"].width < GLYPH_MAX_PT and dw["rect"].height < GLYPH_MAX_PT)
    return glyphs / len(drawings)


def _source_key(name: str) -> str:
    """Khoá so khớp hai bản của cùng một tài liệu, bỏ hậu tố phát hành.

    Bỏ chuỗi số dài (mã phát hành, timestamp), hậu tố `-Q` của bản in, và `(1)` của bản
    tải lại.
    """
    s = re.sub(r"[_\-\s]*\(?\d{6,}\)?", "", os.path.splitext(name)[0])
    s = re.sub(r"[-_\s]*\(?[Qq]\)?(?=$|[-_\s])", "", s)
    s = re.sub(r"[-_\s]*\(\d+\)$", "", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_editable_source(origin):
    """Bản PDF khác của cùng tài liệu mà vẫn còn text layer, hoặc None.

    Đo trên 6 file đã chặn job: trúng 1 (`V16 user manual-PYTES 1.0 20251204(1).pdf` thay cho
    bản `Q 20251021`). Tỉ lệ thấp, nhưng khi trúng thì chi phí xử lý bằng 0 nên vẫn đáng dò.

    Bỏ qua hai thứ dễ nhận nhầm thành nguồn: file `*_VI.pdf` là **đầu ra** đã dịch, và mọi
    thứ nằm dưới `translation/jobs/` là artifact của job chứ không phải tài liệu gốc.
    """
    if not origin or not os.path.isfile(origin):
        return None
    key = _source_key(os.path.basename(origin))
    if len(key) < 8:
        return None
    here = os.path.dirname(os.path.abspath(origin))
    bases = [here] + ([os.path.dirname(here)] if os.path.dirname(here) != here else [])
    opened, seen = 0, {os.path.abspath(origin)}
    for base in bases:
        for dirpath, dirnames, files in os.walk(base):
            if "translation/jobs" in dirpath.replace(os.sep, "/"):
                dirnames[:] = []
                continue
            if os.path.relpath(dirpath, base).count(os.sep) >= 2:
                dirnames[:] = []
            for fn in sorted(files):
                if not fn.lower().endswith(".pdf") or _VI_OUTPUT.search(fn):
                    continue
                full = os.path.abspath(os.path.join(dirpath, fn))
                if full in seen or not _source_key(fn).startswith(key[:12]):
                    continue
                seen.add(full)
                opened += 1
                if opened > SIBLING_OPEN_MAX:
                    return None
                try:
                    with pymupdf.open(full) as cand:
                        chars = sum(len(cand[i].get_text().strip())
                                    for i in range(min(len(cand), 6)))
                except Exception:
                    continue
                if chars >= SIBLING_MIN_CHARS:
                    return full
    return None



def merge_rects(rects: list, tol: float = 3.0, max_pass: int = 6) -> list:
    """Gộp các rect giao/kề nhau (mở rộng tol) thành cluster bboxes."""
    rs = [pymupdf.Rect(r) for r in rects if not pymupdf.Rect(r).is_empty]
    for _ in range(max_pass):
        merged, used, out = False, [False] * len(rs), []
        for i, a in enumerate(rs):
            if used[i]:
                continue
            acc = pymupdf.Rect(a)
            for j in range(i + 1, len(rs)):
                if used[j]:
                    continue
                grown = pymupdf.Rect(acc.x0 - tol, acc.y0 - tol, acc.x1 + tol, acc.y1 + tol)
                if grown.intersects(rs[j]):
                    acc |= rs[j]
                    used[j] = merged = True
            out.append(acc)
            used[i] = True
        rs = out
        if not merged:
            break
    return [[round(c, 2) for c in (r.x0, r.y0, r.x1, r.y1)] for r in rs]


def create_or_open_job(args) -> Job:
    if args.job:
        job = Job(args.job)
        if not os.path.exists(job.yaml_path):
            raise BlockingError(f"--job {args.job}: không có input/job.yaml")
        job.verify_fingerprint()
        return job

    if not args.pdf or not os.path.isfile(args.pdf):
        raise BlockingError(f"--pdf không tồn tại: {args.pdf}")
    src_sha = sha256_file(args.pdf)
    job = Job(os.path.join(args.out, new_job_id(args.pdf, src_sha)))
    job.ensure_dirs()
    shutil.copyfile(args.pdf, job.source_pdf)  # luôn copy, không symlink (SKILL.md §3)

    # Freeze domain context (merge CLI đè file — SKILL.md §5) + glossary.
    ctx_parts = []
    if args.domain_context:
        if os.path.isfile(args.domain_context):
            ctx_parts.append(("cli-file:" + os.path.basename(args.domain_context),
                              open(args.domain_context, encoding="utf-8").read()))
        else:
            ctx_parts.append(("cli-text", args.domain_context))
    ctx_path = job.p("input", "domain_context.md")
    if ctx_parts:
        with open(ctx_path, "w", encoding="utf-8") as f:
            f.write(f"<!-- frozen {utc_now()}; provenance: "
                    f"{', '.join(p[0] for p in ctx_parts)} -->\n\n")
            f.write("\n\n".join(p[1] for p in ctx_parts))
    if args.glossary:
        if not os.path.isfile(args.glossary):
            raise BlockingError(f"--glossary không tồn tại: {args.glossary}")
        shutil.copyfile(args.glossary, job.p("input", "glossary.csv"))

    cfg = load_default_config()
    if args.customer_facing:
        cfg["policy"]["require_domain_context"] = True
    # Override snapshot theo CLI (SKILL.md §2) — chỉ lúc tạo job; resume dùng config đã freeze.
    if args.source_lang:
        cfg["languages"]["source"] = args.source_lang
    if args.target_lang:
        cfg["languages"]["target"] = args.target_lang
    if args.provider_model:
        cfg["translation"]["provider_model_version"] = args.provider_model
    fonts_manifest = os.path.join(ASSETS_DIR, "fonts", "fonts_manifest.json")
    import json as _json
    meta = {
        "job_id": os.path.basename(job.root),
        "source_name": os.path.basename(args.pdf),
        # Đường dẫn gốc, KHÔNG nằm trong determinism tuple: chỉ dùng để dò bản
        # thay thế còn text layer khi nguồn hoá ra là bản in đã outline.
        "source_origin": os.path.abspath(args.pdf),
        "created_at": utc_now(),
        "status": "INGESTED",
        "page_count": 0,
        "customer_facing": bool(args.customer_facing),
        "config": cfg,
        # Determinism tuple — SKILL.md §2, spec §12.
        "determinism": {
            "source_sha256": src_sha,
            "domain_context_sha256": sha256_file(ctx_path) if os.path.exists(ctx_path) else None,
            "glossary_sha256": sha256_file(job.p("input", "glossary.csv"))
            if os.path.exists(job.p("input", "glossary.csv"))
            else sha256_file(os.path.join(ASSETS_DIR, "default_glossary.csv")),
            "engine_version": ENGINE_VERSION,
            "config_sha256": sha256_text(_json.dumps(cfg, sort_keys=True)),
            "font_pack": cfg["fonts"]["pack"],
            "font_pack_sha256": sha256_file(fonts_manifest) if os.path.exists(fonts_manifest) else None,
            "layout_model_version": layout_model_for(cfg),
            "provider_model_version": cfg["translation"]["provider_model_version"],
            "prompt_version": cfg["translation"]["prompt_version"],
            "pymupdf_version": pymupdf.version[0],
        },
        "stages": {},
        "status_history": [],
    }
    job.save(meta)
    job.log_event(STAGE, "info", "JOB_CREATED", f"job {meta['job_id']} từ {args.pdf}")
    return job


def meta_origin(job: Job):
    """Đường dẫn gốc ghi lúc tạo job. None với job cũ tạo trước khi trường này tồn tại."""
    try:
        return job.load().get("source_origin")
    except Exception:
        return None


def inspect(job: Job) -> tuple[str, dict, dict]:
    """Trả về (classification, preflight_report, resource_manifest)."""
    cfg = job.config
    issues: list[dict] = []
    doc = pymupdf.open(job.source_pdf)

    if doc.needs_pass:
        issues.append(make_issue("ENCRYPTED_PDF", "P0", STAGE, "PDF yêu cầu password — reject"))
        return "REJECTED", {"issues": issues, "pages": []}, {}
    if doc.is_encrypted:
        issues.append(make_issue("ENCRYPTED_OPENABLE", "P2", STAGE,
                                 "PDF encrypted nhưng mở được với empty password"))
    try:
        sig = doc.get_sigflags()
    except Exception:
        sig = -1
    if sig > 0:
        issues.append(make_issue("SIGNED_PDF", "P0", STAGE,
                                 "PDF có chữ ký số — không sửa; cần re-sign workflow riêng"))
        return "MANUAL_DTP_REQUIRED", {"issues": issues, "pages": []}, {}

    pages_report, manifest_pages = [], []
    fonts_agg: dict[tuple, dict] = {}
    n_scanned = n_vector_suspect = n_texty = n_outlined = 0
    text_sample: list[str] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        d = page.get_text("dict")
        spans = [s for b in d["blocks"] if b.get("type") == 0
                 for l in b["lines"] for s in l["spans"]]
        n_chars = sum(len(s["text"]) for s in spans)
        dirs = {tuple(round(c, 3) for c in l["dir"])
                for b in d["blocks"] if b.get("type") == 0 for l in b["lines"]}
        wmodes = {l.get("wmode", 0)
                  for b in d["blocks"] if b.get("type") == 0 for l in b["lines"]}

        imgs = page.get_image_info(hashes=True, xrefs=True)
        page_area = abs(page.rect)
        img_area = sum(abs(pymupdf.Rect(i["bbox"])) for i in imgs)
        drawings = page.get_drawings()
        draw_clusters = merge_rects([dw["rect"] for dw in drawings])
        links = page.get_links()
        annots = [{"type": a.type[1], "rect": list(a.rect)} for a in page.annots()] \
            if page.first_annot else []

        scanned = n_chars < 5 and page_area > 0 and img_area / page_area > 0.8
        vector_suspect = n_chars < 5 and not scanned and len(drawings) > 40
        # Chữ đã convert-to-outline nhận ra được vì gần như mọi path đều bé bằng một glyph.
        # Trang sơ đồ thuần cũng nhiều vector nhưng path của nó to — hai ca này có tính khả
        # thi trái ngược nhau nên không được gộp chung một mã lỗi.
        glyph_share = outlined_glyph_share(drawings)
        outlined = vector_suspect and glyph_share >= OUTLINED_GLYPH_SHARE
        if scanned:
            n_scanned += 1
            # Dứt khoát, không để người vận hành phải tự cân nhắc: fit_paint chạy mọi lượt
            # redaction với PDF_REDACT_IMAGE_NONE và không có đường nào sửa pixel ảnh, nên
            # chữ dịch sẽ vẽ ĐÈ lên chữ gốc còn nguyên trong ảnh.
            issues.append(make_issue("SCANNED_PAGE", "P1", STAGE,
                                     "trang chỉ có ảnh scan — engine không sửa pixel ảnh theo "
                                     "thiết kế, MANUAL_DTP là đúng", page=pno))
        elif outlined:
            n_outlined += 1
            issues.append(make_issue("OUTLINED_VECTOR_TEXT", "P1", STAGE,
                                     f"chữ đã convert-to-outline ({glyph_share:.0%} path cỡ "
                                     "glyph) — xin bản gốc từ nhà cung cấp", page=pno))
        elif vector_suspect:
            n_vector_suspect += 1
            issues.append(make_issue("TEXT_AS_VECTOR_SUSPECT", "P1", STAGE,
                                     "trang nhiều vector, không có text layer", page=pno))
        elif n_chars >= 5:
            n_texty += 1
            text_sample.append("".join(s["text"] for s in spans))

        odd_dirs = dirs - AXIS_DIRS
        if odd_dirs:
            issues.append(make_issue("ARBITRARY_ANGLE_TEXT", "P1", STAGE,
                                     f"text có góc bất kỳ {sorted(odd_dirs)[:3]} — needs review",
                                     page=pno))
        if wmodes - {0}:
            issues.append(make_issue("VERTICAL_WMODE", "P1", STAGE,
                                     "vertical writing mode — needs review", page=pno))

        for f in page.get_fonts(full=True):
            key = (f[3], f[1], f[2])  # basefont, ext, type
            fonts_agg.setdefault(key, {"basefont": f[3], "ext": f[1], "type": f[2],
                                       "embedded": f[1] != "n/a", "pages": []})
            fonts_agg[key]["pages"].append(pno)
            if f[1] == "n/a":
                pass  # không reuse font gốc trong v1 nên non-embedded chỉ ghi nhận

        pages_report.append({
            "page": pno, "chars": n_chars, "spans": len(spans),
            "images": len(imgs), "image_area_ratio": round(img_area / page_area, 3) if page_area else 0,
            "drawings": len(drawings), "draw_clusters": len(draw_clusters),
            "links": len(links), "annots": len(annots),
            "dirs": sorted(map(list, dirs)), "scanned": scanned, "vector_suspect": vector_suspect,
            "outlined": outlined,
        })
        manifest_pages.append({
            "page": pno,
            "mediabox": list(page.mediabox), "cropbox": list(page.cropbox),
            "rotation": page.rotation,
            "images": [{"xref": i.get("xref"), "bbox": [round(c, 2) for c in i["bbox"]],
                        "digest": (i.get("digest").hex() if isinstance(i.get("digest"), (bytes, bytearray))
                                   else str(i.get("digest")))} for i in imgs],
            "draw_clusters": draw_clusters,
            "links": [{k: (list(v) if isinstance(v, pymupdf.Rect) else v)
                       for k, v in ln.items() if k in ("kind", "uri", "page", "from")}
                      for ln in links],
            "annots": annots,
        })

    # ToUnicode hỏng: hỏi câu mà không stage nào hỏi — chữ trích ra có đọc được không.
    # Judged ở mức tài liệu chứ không từng trang: một trang hiếm khi đủ 200 từ Latin.
    # P1 chứ chưa P0 — mới có một ca dương tính làm bằng chứng, và P1 đã đủ đẩy job sang
    # SUPPORTED_WITH_REVIEW nên không có bản dịch nào tự phát hành trên nguồn hỏng.
    ratio = readable_ratio("\n".join(text_sample))
    if ratio is not None and ratio < READABLE_RATIO_MIN:
        issues.append(make_issue("MOJIBAKE_TOUNICODE", "P1", STAGE,
                                 f"text layer không đọc được (tỉ lệ hư từ {ratio}) — ToUnicode "
                                 "CMap hỏng, sửa nguồn trước khi dịch"))

    # Bản in đã outline thì thường vẫn còn bản gốc ở đâu đó; dò trước khi bắt người ta đi hỏi.
    if n_outlined:
        origin = meta_origin(job)
        alt = find_editable_source(origin)
        if alt:
            issues.append(make_issue("EDITABLE_SOURCE_FOUND", "P2", STAGE,
                                     f"có bản còn text layer, dùng bản này thay vì bản outline: {alt}"))

    # Domain context policy — SKILL.md §5.
    if not os.path.exists(job.p("input", "domain_context.md")):
        sev = "P1" if job.config["policy"]["require_domain_context"] else "P2"
        issues.append(make_issue("DOMAIN_CONTEXT_MISSING", sev, STAGE,
                                 "thiếu domain context; " +
                                 ("blocking (customer-facing)" if sev == "P1"
                                  else "warning — nên bổ sung để dịch đúng ngành")))

    if n_texty == 0:
        cls = "MANUAL_DTP_REQUIRED"
    elif job.config["policy"]["require_domain_context"] and \
            not os.path.exists(job.p("input", "domain_context.md")):
        cls = "SUPPORTED_WITH_REVIEW"  # P1 chặn translate ở stage sau
    elif any(i["severity"] in ("P0", "P1") for i in issues):
        cls = "SUPPORTED_WITH_REVIEW"
    else:
        cls = "SUPPORTED"

    report = {"classification": cls, "generated_at": utc_now(), "engine": ENGINE_VERSION,
              "page_count": doc.page_count, "issues": issues, "pages": pages_report,
              "fonts": list(fonts_agg.values())}
    manifest = {"generated_at": utc_now(), "pages": manifest_pages}
    meta = job.load()
    meta["page_count"] = doc.page_count
    job.save(meta)
    doc.close()
    return cls, report, manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf")
    ap.add_argument("--out", default="jobs")
    ap.add_argument("--domain-context")
    ap.add_argument("--glossary")
    ap.add_argument("--customer-facing", action="store_true")
    ap.add_argument("--job")
    ap.add_argument("--source-lang", help="override languages.source lúc tạo job (default: en)")
    ap.add_argument("--target-lang", help="override languages.target lúc tạo job (default: vi)")
    ap.add_argument("--provider-model",
                    help="model id thật của agent dịch stage 4, ghi vào determinism tuple "
                         "(vd claude-fable-5, gpt-5.2-codex, gemini-3-pro)")
    args = ap.parse_args()

    job = None
    try:
        job = create_or_open_job(args)
        with job.acquire_lock(STAGE):
            cls, report, manifest = inspect(job)
            save_json(job.p("model", "preflight.json"), report)
            if manifest:
                save_json(job.p("model", "resource_manifest.json"), manifest)
            job.mark_stage(STAGE)
            if job.status() == "INGESTED":
                job.set_status("PREFLIGHTED", f"classification={cls}")
            if cls == "REJECTED":
                job.set_status("REJECTED", "preflight reject")
                job.write_summary("Job bị reject ở preflight — xem issues trong preflight.json.")
            elif cls == "MANUAL_DTP_REQUIRED":
                job.set_status("MANUAL_DTP", "preflight: ngoài automatic envelope")
                job.write_summary("Tài liệu cần manual DTP — engine không tự xử lý.")
            else:
                job.write_summary("Chạy `extract_group.py --job <job>` để build layout model.")
            print(f"preflight: {cls} | job: {job.root}")
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
