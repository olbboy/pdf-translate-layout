"""Stage 8 — Human approval: ghi decision, promote output khi gates xanh.

Release rule (SKILL.md §1.2): output CHỈ khi gates PASS VÀ human approval tường minh.
Chạy: python3 approve.py --job <job_dir> --approver <tên> --decision approve|reject [--note ...]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from _common import (BlockingError, Job, append_jsonl, exit_blocking, load_json,
                     sha256_file, utc_now)

STAGE = "approve"


def stage_release_copy(draft: str, out: str) -> str:
    """Copy draft → `<out>.part`, tự tạo thư mục đích nếu chưa có. Trả về đường dẫn tạm.

    `Job.p()` chỉ ghép chuỗi đường dẫn, không tạo thư mục. Job chưa từng phát hành thì
    `output/` chưa tồn tại và `shutil.copyfile` ném `FileNotFoundError` — sự cố thật
    2026-08-06 trên hai job Lite, trong khi job V16 lại chạy được vì đã có `output/` từ
    lần phát hành trước, nên lỗi ẩn suốt.

    Ghi vào tên tạm để bước đổi tên cuối cùng là thao tác nguyên tử: `output/` không bao
    giờ chứa `translated-approved.pdf` trước khi trạng thái thật sự là RELEASED.
    """
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    shutil.copyfile(draft, tmp)
    return tmp


def require_human_terminal(job: Job) -> None:
    """Human-gate cho approve (SKILL.md §1.2) — enforce bằng code, mọi platform.

    Sự cố 2026-08-04 (2 lần): agent tự approve với tên người ("User", "User/Agent")
    và waive hàng loạt. Code không thể xác thực danh tính, nhưng có thể yêu cầu
    một terminal tương tác + gõ chuỗi thử thách — điều agent session headless
    (Claude Code / Codex / Antigravity) không có. Giới hạn thành thật: một agent
    chủ đích vẫn có thể giả PTY; hàng rào này chặn agent "tiện tay", không thay
    được kỷ luật vận hành.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise BlockingError(
            "approve yêu cầu CON NGƯỜI chạy trực tiếp trong terminal (stdin/stdout "
            "không phải TTY — đây là agent session). Agent không bao giờ được approve "
            "(SKILL.md §1.2). Reviewer mở terminal và tự chạy lệnh approve.")
    sha8 = job.load()["determinism"]["source_sha256"][:8]
    challenge = f"APPROVE {sha8}"
    print(f"Xác nhận human approval — gõ đúng chuỗi: {challenge}")
    if input("> ").strip() != challenge:
        raise BlockingError("chuỗi xác nhận không khớp — approve hủy")


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
            decision = {"approver": args.approver,
                        "decision": args.decision, "note": args.note,
                        "waivers": waivers,
                        "qa_result": qa["result"], "severity": qa["severity_all"]}

            def record() -> None:
                """Ghi decisions.jsonl — gọi CHỈ khi quyết định đã thực sự có hiệu lực.

                `decisions.jsonl` là append-only và là hồ sơ kiểm toán "ai duyệt cái gì"
                (SKILL.md §1.2), nên một dòng ở đây phải đồng nghĩa với một thay đổi trạng
                thái đã xảy ra. Thứ tự cũ ghi ngay khi vào lệnh, TRƯỚC cả `require_human_terminal`
                và các chốt P0/P1 — sự cố thật 2026-08-06 trên job HV48100: reviewer gõ sai
                chuỗi xác nhận, release bị chặn đúng (job giữ NEEDS_REVIEW, không có bản phát
                hành nào), nhưng nhật ký vẫn còn dòng "Leo approved" mãi mãi vì file
                append-only không xoá được. Nhật ký nói sai sự thật là hỏng đúng thứ nó tồn
                tại để bảo vệ.

                Đặt ngay TRƯỚC `set_status` chứ không phải sau: Release rule đòi bản phát
                hành phải có decision kèm approver + timestamp, nên trạng thái RELEASED mà
                thiếu dòng ghi còn tệ hơn chiều ngược lại.
                """
                append_jsonl(job.p("review", "decisions.jsonl"),
                             {"ts": utc_now(), **decision})

            if args.decision == "reject":
                record()
                job.set_status("REJECTED", f"reviewer {args.approver} reject")
                job.write_summary(f"Bị reject bởi {args.approver}: {args.note or '(no note)'}")
                print("rejected — đã ghi decisions.jsonl")
                return

            if args.decision == "revoke":
                # Thu hồi release đã phát hành (vd: approval giả mạo, lỗi phát hiện muộn).
                if job.status() != "RELEASED":
                    raise BlockingError(f"revoke chỉ áp dụng cho job RELEASED (hiện: {job.status()})")
                record()
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

            require_human_terminal(job)  # reject/revoke không cần — chỉ approve mới release
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
            if job.status() not in ("AUTO_QA_PASS", "NEEDS_REVIEW"):
                raise BlockingError(
                    f"status {job.status()} không thể approve — cần NEEDS_REVIEW/AUTO_QA_PASS. "
                    "Nếu vừa chạy lại validate: chạy tiếp fit_paint.py rồi qa_gates.py "
                    "(validate luôn hạ về TRANSLATED vì render cũ không còn được đảm bảo khớp).")
            # Ghi artifact TRƯỚC, lật trạng thái SAU, rồi mới đổi tên vào chỗ chính thức.
            # Thứ tự cũ (lật trạng thái trước, copy sau) fail-OPEN: 2026-08-06 copyfile ném
            # FileNotFoundError vì `output/` chưa tồn tại, và hai job đã kịp mang trạng thái
            # RELEASED mà không có bản phát hành nào — đúng thứ không bao giờ được phép xảy ra.
            out = job.p("output", "translated-approved.pdf")
            tmp = stage_release_copy(job.p("render", "draft.pdf"), out)
            record()
            job.set_status("HUMAN_APPROVED",
                           f"approver={args.approver} waived={sorted(waivers)}")
            job.set_status("RELEASED")
            os.replace(tmp, out)
            job.mark_stage(STAGE)
            job.write_summary(f"RELEASED — output: `output/translated-approved.pdf` "
                              f"(approver {args.approver}, {utc_now()})")
            print(f"released → {out}")
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
