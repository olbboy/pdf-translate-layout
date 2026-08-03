"""Stage 1 — Preflight: tạo job folder, phân loại supported envelope, resource manifest.

Spec §6.2, §3.2. Output: model/preflight.json, model/resource_manifest.json.
Chạy: python3 preflight.py --pdf <path> [--out jobs] [--domain-context <text|path>]
       [--glossary <csv>] [--customer-facing] [--job <job_dir>]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

import pymupdf

from _common import (ASSETS_DIR, ENGINE_VERSION, LAYOUT_MODEL_VERSION, BlockingError, Job,
                     exit_blocking, load_default_config, make_issue, new_job_id, save_json,
                     sha256_file, sha256_text, utc_now)

AXIS_DIRS = {(1, 0), (0, 1), (-1, 0), (0, -1)}
STAGE = "preflight"


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
    fonts_manifest = os.path.join(ASSETS_DIR, "fonts", "fonts_manifest.json")
    import json as _json
    meta = {
        "job_id": os.path.basename(job.root),
        "source_name": os.path.basename(args.pdf),
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
            "layout_model_version": LAYOUT_MODEL_VERSION,
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
    n_scanned = n_vector_suspect = n_texty = 0

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
        if scanned:
            n_scanned += 1
            issues.append(make_issue("SCANNED_PAGE", "P1", STAGE,
                                     "trang chỉ có ảnh scan, không có text layer", page=pno))
        elif vector_suspect:
            n_vector_suspect += 1
            issues.append(make_issue("TEXT_AS_VECTOR_SUSPECT", "P1", STAGE,
                                     "trang nhiều vector, không có text layer", page=pno))
        elif n_chars >= 5:
            n_texty += 1

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
