"""Stage 8 — Human approval: ghi decision, promote output khi gates xanh.

Release rule (SKILL.md §1.2): output CHỈ khi gates PASS VÀ human approval tường minh.
Chạy: python3 approve.py --job <job_dir> --approver <tên> --decision approve|reject [--note ...]
"""

from __future__ import annotations

import argparse
import os
import shutil

from _common import (BlockingError, Job, append_jsonl, exit_blocking, load_json,
                     sha256_file, utc_now)

STAGE = "approve"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    ap.add_argument("--approver", required=True)
    ap.add_argument("--decision", choices=("approve", "reject", "revoke"), required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--waive", action="append", default=[], metavar="CODE=REASON",
                    help="reviewer chấp nhận toàn bộ P1 của một issue code kèm lý do "
                         "(spec §10.8 'resolved/approved'); P0 không waive được")
    args = ap.parse_args()
    waivers: dict[str, str] = {}
    for w in args.waive:
        if "=" not in w:
            raise SystemExit(f"--waive cần dạng CODE=REASON: {w}")
        code, reason = w.split("=", 1)
        waivers[code] = reason
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            qa = load_json(job.p("qa", "report.json"))
            if not qa:
                raise BlockingError("chưa có qa/report.json — chạy qa_gates trước")
            decision = {"ts": utc_now(), "approver": args.approver,
                        "decision": args.decision, "note": args.note,
                        "waivers": waivers,
                        "qa_result": qa["result"], "severity": qa["severity_all"]}
            append_jsonl(job.p("review", "decisions.jsonl"), decision)

            if args.decision == "reject":
                job.set_status("REJECTED", f"reviewer {args.approver} reject")
                job.write_summary(f"Bị reject bởi {args.approver}: {args.note or '(no note)'}")
                print("rejected — đã ghi decisions.jsonl")
                return

            if args.decision == "revoke":
                # Thu hồi release đã phát hành (vd: approval giả mạo, lỗi phát hiện muộn).
                if job.status() != "RELEASED":
                    raise BlockingError(f"revoke chỉ áp dụng cho job RELEASED (hiện: {job.status()})")
                job.set_status("REVOKED", f"reviewer {args.approver} revoke: {args.note or '(no note)'}")
                out = job.p("output", "translated-approved.pdf")
                if os.path.exists(out):
                    draft = job.p("render", "draft.pdf")
                    if os.path.exists(draft) and sha256_file(out) == sha256_file(draft):
                        os.remove(out)  # bản copy y hệt draft — xoá an toàn, draft giữ nguyên
                    else:
                        os.replace(out, job.p("output",
                                              f"REVOKED-{utc_now().replace(':', '')}.pdf"))
                job.write_summary(
                    f"REVOKED bởi {args.approver}: {args.note or '(no note)'} — output đã thu hồi. "
                    "Re-run: sửa translation/responses.jsonl → validate → fit_paint → qa → approve.")
                print("revoked — output đã thu hồi, đã ghi decisions.jsonl")
                return

            if qa.get("partial"):
                raise BlockingError("bản render là partial (dev run) — không thể release")
            issues = job.collect_issues()
            p0 = [i for i in issues if i["severity"] == "P0"]
            p1_left = sorted({i["code"] for i in issues
                              if i["severity"] == "P1" and i["code"] not in waivers})
            if p0:
                raise BlockingError(f"còn {len(p0)} P0 — không waive được, không thể release")
            if p1_left:
                raise BlockingError(
                    f"còn P1 chưa resolved/waived: {p1_left} — reviewer phải xử lý "
                    "hoặc --waive CODE=REASON (spec §10.8)")
            if job.status() in ("AUTO_QA_PASS", "NEEDS_REVIEW"):
                job.set_status("HUMAN_APPROVED",
                               f"approver={args.approver} waived={sorted(waivers)}")
                job.set_status("RELEASED")
            else:
                raise BlockingError(f"status {job.status()} không thể approve")
            out = job.p("output", "translated-approved.pdf")
            shutil.copyfile(job.p("render", "draft.pdf"), out)
            job.mark_stage(STAGE)
            job.write_summary(f"RELEASED — output: `output/translated-approved.pdf` "
                              f"(approver {args.approver}, {utc_now()})")
            print(f"released → {out}")
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
