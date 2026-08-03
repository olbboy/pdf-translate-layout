"""Stage 5 — Validate agent responses: schema, placeholder round-trip, NFC, glossary.

Spec §6.6 (reject rules), Gate 2 inputs. Cập nhật target vào model/regions.json.
Chạy: python3 validate_responses.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import re

from _common import (BlockingError, Job, exit_blocking, load_glossary, load_json,
                     make_issue, nfc, read_jsonl, save_json)

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

    cfg = job.config
    pmap = cfg["unicode"]["punctuation_map"]
    locked = [g for g in load_glossary(job) if g["type"] == "locked"]
    issues: list[dict] = []
    n_ok = n_fail = 0
    seen: set[str] = set()

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
        if rid in seen:  # bản sau ghi đè bản trước (agent sửa) — chỉ ghi nhận
            issues.append(make_issue("DUPLICATE_RESPONSE", "P2", STAGE,
                                     "response bị ghi đè bởi bản mới hơn", region_id=rid))
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

    pending = [rid for rid, r in regions.items()
               if r["translation_action"] == "translate" and "target_text" not in r]
    save_json(job.p("model", "regions.json"), model)
    save_json(job.p("model", "validate_issues.json"), issues)
    job.mark_stage("translate", "done" if not pending else f"partial:{len(pending)}")
    job.mark_stage(STAGE, "done" if n_fail == 0 else f"failed:{n_fail}")
    if not pending and n_fail == 0 and job.status() in ("PREFLIGHTED", "NEEDS_REVIEW"):
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
