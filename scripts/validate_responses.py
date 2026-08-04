"""Stage 5 — Validate agent responses: schema, placeholder round-trip, NFC, glossary.

Spec §6.6 (reject rules), Gate 2 inputs. Cập nhật target vào model/regions.json.
Chạy: python3 validate_responses.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import re

from _common import (BlockingError, Job, authenticity_cfg, authenticity_check,
                     exit_blocking, load_glossary, load_json, make_issue, nfc,
                     read_jsonl, save_json)

STAGE = "validate"
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")


def apply_punct_map(text: str, pmap: dict) -> tuple[str, bool]:
    """Punctuation allowlist — áp trên dạng placeholder nên token không bị chạm."""
    out = text
    for k, v in pmap.items():
        out = out.replace(k, v)
    out = re.sub(r"  +", " ", out)
    return out, out != text


def validate(job: Job) -> None:
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json")
    regions = {r["region_id"]: r for r in model["regions"]}
    requests = {r["region_id"]: r for r in read_jsonl(job.p("translation", "requests.jsonl"))}
    responses = read_jsonl(job.p("translation", "responses.jsonl"))
    if not responses:
        raise BlockingError("translation/responses.jsonl trống — agent chưa dịch")

    # Append-workflow: chỉ validate DÒNG CUỐI của mỗi region — dòng cũ bị ghi đè
    # là lịch sử, không phát issue/fail cho chúng (ghi nhận P2 DUPLICATE_RESPONSE).
    latest: dict[str, dict] = {}
    n_dup = 0
    for resp in responses:
        rid = resp.get("region_id", "")
        if rid in latest:
            n_dup += 1
        latest[rid] = resp
    responses = list(latest.values())

    cfg = job.config
    pmap = cfg["unicode"]["punctuation_map"]
    locked = [g for g in load_glossary(job) if g["type"] == "locked"]
    auth = authenticity_cfg(cfg)
    target_lang = cfg["languages"]["target"]
    issues: list[dict] = []
    n_ok = n_fail = 0
    seen: set[str] = set()
    # Authenticity theo TRẠNG THÁI CUỐI của từng region — không đếm theo dòng.
    # Workflow chuẩn cho phép append bản sửa (bản sau ghi đè bản trước): dòng cũ
    # identical không được tính nữa khi đã có bản sửa hợp lệ phía sau.
    auth_flags: dict[str, tuple[str | None, int | None]] = {}

    for resp in responses:
        rid = resp.get("region_id", "")
        reg = regions.get(rid)
        req = requests.get(rid)

        def fail(code: str, detail: str, sev: str = "P1"):
            issues.append(make_issue(code, sev, STAGE, detail,
                                     page=(reg or {}).get("page"), region_id=rid))

        if reg is None or req is None:
            # orphan từ layout version cũ — warning, không chặn khi mọi region
            # hiện hành đều có bản dịch hợp lệ
            issues.append(make_issue("ORPHAN_RESPONSE", "P2", STAGE,
                                     "response cho region không còn tồn tại (layout cũ)",
                                     region_id=rid))
            continue
        seen.add(rid)

        runs = resp.get("target_runs")
        if not isinstance(runs, list) or not runs or \
                not all(isinstance(r, dict) and r.get("role") and isinstance(r.get("text"), str)
                        for r in runs):
            fail("SCHEMA_INVALID", "target_runs sai schema"); n_fail += 1; continue

        target_pl = "".join(r["text"] for r in runs)
        if not target_pl.strip():
            fail("EMPTY_TARGET", "target rỗng — chỉ reviewer được quyết định delete (spec §5.6)")
            n_fail += 1; continue

        req_roles = set(req["style_roles"])
        resp_roles = {r["role"] for r in runs}
        if not resp_roles <= req_roles:
            fail("UNKNOWN_ROLE", f"role lạ: {sorted(resp_roles - req_roles)}"); n_fail += 1; continue
        if "label" in req_roles and "label" not in resp_roles:
            fail("MISSING_STYLE_ROLE", "request có label nhưng response mất role label")
            n_fail += 1; continue

        # placeholder round-trip 1:1 theo multiset (spec Gate 2)
        src_counts: dict[str, int] = {}
        for m in PH_RE.finditer(req["source_text"]):
            src_counts[m.group(1)] = src_counts.get(m.group(1), 0) + 1
        tgt_counts: dict[str, int] = {}
        for m in PH_RE.finditer(target_pl):
            tgt_counts[m.group(1)] = tgt_counts.get(m.group(1), 0) + 1
        if src_counts != tgt_counts:
            missing = {k: v for k, v in src_counts.items() if tgt_counts.get(k) != v}
            extra = {k: v for k, v in tgt_counts.items() if src_counts.get(k) != v}
            fail("PLACEHOLDER_MISMATCH", f"thiếu/lệch {missing} thừa {extra}")
            n_fail += 1; continue

        # NFC + punctuation allowlist (áp trước khi restore → token nguyên vẹn)
        norm_runs = []
        punct_applied = False
        for r in runs:
            t = nfc(r["text"])
            t, changed = apply_punct_map(t, pmap)
            punct_applied |= changed
            norm_runs.append({"role": r["role"], "text": t})
        target_pl = "".join(r["text"] for r in norm_runs)

        for g in locked:
            if re.search(rf"(?i)(?<![a-z]){re.escape(g['term'])}(?![a-z])",
                         req["source_text"]) and g["target"] not in target_pl:
                fail("GLOSSARY_LOCKED_VIOLATION", f"thiếu thuật ngữ khóa: {g['term']} → {g['target']}")
                n_fail += 1
                break
        else:
            # Authenticity (chống copy-through — sự cố 2026-08-04): ghi flag theo
            # region, dòng sau ghi đè dòng trước; phát issue sau vòng lặp.
            auth_flags[rid] = (authenticity_check(req["source_text"], target_pl,
                                                  target_lang, auth["min_words"]),
                               reg.get("page"))
            mapping = reg.get("placeholders", {})
            reg["target_runs"] = norm_runs
            reg["target_text"] = nfc(PH_RE.sub(
                lambda m: mapping.get(m.group(1), m.group(0)), target_pl))
            reg["translation_meta"] = {
                "provider": cfg["translation"]["provider_model_version"],
                "prompt_version": cfg["translation"]["prompt_version"],
                "punctuation_normalized": punct_applied,
                "notes": resp.get("notes", []),
            }
            n_ok += 1

    # Phát per-region authenticity issue theo trạng thái cuối (sau mọi ghi đè).
    n_ident = n_lang = 0
    for rid, (flag, page) in auth_flags.items():
        if flag == "identical":
            n_ident += 1
            issues.append(make_issue("TRANSLATION_IDENTICAL", "P1", STAGE,
                                     "region đáng dịch nhưng target trùng source (chưa dịch)",
                                     page=page, region_id=rid))
        elif flag == "lang_suspect":
            n_lang += 1
            issues.append(make_issue("TARGET_LANG_SUSPECT", "P1", STAGE,
                                     f"target gần như không có chữ tiếng {target_lang} — "
                                     "nghi chưa dịch/dịch máy lỗi", page=page, region_id=rid))
        elif flag == "truncated":
            issues.append(make_issue("TRANSLATION_TRUNCATED", "P1", STAGE,
                                     "target mất khối lượng nội dung so với source (<45% số từ) "
                                     "— nghi dịch nuốt ý; dịch lại ĐẦY ĐỦ region này",
                                     page=page, region_id=rid))

    # Job-level authenticity gate — P0, KHÔNG waive được (approve.py chặn mọi P0).
    n_resp = max(1, len(seen))
    ident_ratio, lang_ratio = n_ident / n_resp, n_lang / n_resp
    auth_block = None
    if ident_ratio > auth["identical_ratio_max"]:
        auth_block = (f"TRANSLATION_COVERAGE_FAIL: {n_ident}/{n_resp} regions "
                      f"({ident_ratio:.0%}) target trùng source — vượt ngưỡng "
                      f"{auth['identical_ratio_max']:.0%}. Bản dịch phải do model của session "
                      "sinh ra cho TỪNG region; cấm script/dictionary/find-replace.")
        issues.append(make_issue("TRANSLATION_COVERAGE_FAIL", "P0", STAGE, auth_block))
    if lang_ratio > auth["lang_suspect_ratio_max"]:
        detail = (f"TARGET_LANG_FAIL: {n_lang}/{n_resp} regions ({lang_ratio:.0%}) "
                  f"không phải tiếng {target_lang} — vượt ngưỡng "
                  f"{auth['lang_suspect_ratio_max']:.0%}.")
        issues.append(make_issue("TARGET_LANG_FAIL", "P0", STAGE, detail))
        auth_block = auth_block or detail

    if n_dup:
        issues.append(make_issue("DUPLICATE_RESPONSE", "P2", STAGE,
                                 f"{n_dup} dòng cũ bị ghi đè bởi bản mới hơn (append-workflow)"))
    pending = [rid for rid, r in regions.items()
               if r["translation_action"] == "translate" and "target_text" not in r]
    save_json(job.p("model", "regions.json"), model)
    save_json(job.p("model", "validate_issues.json"), issues)
    job.mark_stage("translate", "done" if not pending else f"partial:{len(pending)}")
    if auth_block:
        job.mark_stage(STAGE, f"failed:authenticity ident={n_ident} lang={n_lang}")
        raise BlockingError(auth_block)
    job.mark_stage(STAGE, "done" if n_fail == 0 else f"failed:{n_fail}")
    if not pending and n_fail == 0 and job.status() in ("PREFLIGHTED", "NEEDS_REVIEW", "REVOKED"):
        job.set_status("TRANSLATED", "100% translate-regions có target hợp lệ")
        job.write_summary("Chạy `fit_paint.py --job <job>` để render draft.")
    else:
        job.write_summary(
            f"Validate: {n_ok} OK, {n_fail} fail, {len(pending)} region chưa dịch. "
            "Agent bổ sung/sửa responses.jsonl rồi chạy lại validate_responses.py.")
    print(f"validate: ok={n_ok} fail={n_fail} pending={len(pending)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            validate(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
