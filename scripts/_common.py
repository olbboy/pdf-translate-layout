"""Shared job infrastructure for pdf-translate-layout engine scripts.

Spec: docs/system_design_pdf_translation_engine_v1_final.md (rev 1.3).
Job folder contract: SKILL.md §2. All stage scripts import from here.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata

import pymupdf
import yaml

ENGINE_VERSION = "1.9.15"
# Mốc trước: lg-basic-3 tách hàng bảng gõ liền theo lưới cột logic; lg-basic-4 thêm gộp
# cross-block các dòng cùng đoạn.
# lg-basic-5: bbox của line chỉ tính ký tự CÓ MỰC, và hàng đa cột được tách tại MỌI khe
# space có vạch kẻ dọc thật nằm trong khe (không còn đòi ≥2 space, không còn dùng lưới
# logic của find_tables).
LAYOUT_MODEL_VERSION = "lg-basic-5"
# lg-basic-6: lg-basic-5 + gộp CROSS-BLOCK các dòng cùng một đoạn. PDF hay đặt mỗi dòng vào
# một block rawdict riêng (thư ngỏ V16: 28 dòng = 28 block), mà `group_block_lines` chỉ gộp
# trong một block, nên câu bị xé theo dòng và bản dịch không đảo vế qua ranh giới được.
LAYOUT_MODEL_MERGED = "lg-basic-6"


def layout_model_for(cfg: dict) -> str:
    """Layout model thực tế phụ thuộc cờ gộp đoạn — regions.json của cùng một source khác
    hẳn nhau giữa hai chế độ, nên determinism tuple phải phân biệt được."""
    return (LAYOUT_MODEL_MERGED
            if (cfg.get("layout") or {}).get("merge_paragraph", True)
            else LAYOUT_MODEL_VERSION)

# Dung sai container — fit_paint (được phép dôi ra) và qa_gates (chấp nhận phần
# dôi đó) PHẢI đọc cùng con số, nếu không fitter tạo layout mà gate tự báo lỗi.
# Config `qa.container_tol_*` override; hằng này là default cho job cũ thiếu key.
CONTAINER_TOL_PT_DEFAULT = 1.5
CONTAINER_TOL_Y_EM_DEFAULT = 0.6


def vertical_rules(page: pymupdf.Page, tol: float = 0.8) -> list:
    """Nét kẻ dọc THỰC SỰ vẽ trên trang → [(x, y0, y1)].

    Dùng nét vẽ chứ không dùng lưới logic của `find_tables`: ô gộp không có nét
    ngăn nên tiêu đề trải hết bảng là hợp lệ, trong khi lưới logic vẫn báo có
    ranh giới cột ở đó và sinh false positive.

    Đặt ở đây vì hai stage phải đọc CÙNG một danh sách: stage 2 cắt hàng đa cột tại
    các vạch này, stage 7 lấy chính chúng làm chuẩn cho `G4_TABLE_RULE_CROSS`. Hai
    định nghĩa lệch nhau thì fitter tạo layout mà gate tự báo lỗi.
    """
    out = []
    for d in page.get_drawings():
        stroked = d.get("type") in ("s", "fs")
        for it in d["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.x - q.x) <= tol and abs(p.y - q.y) > 2:
                    out.append(((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height <= 2:
                    continue
                if r.width <= 1.5:      # thanh mảnh dùng làm vạch kẻ
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif stroked:           # khung có viền → hai cạnh dọc
                    out.append((r.x0, r.y0, r.y1))
                    out.append((r.x1, r.y0, r.y1))
    return out


# Ô trống điền tay: nét ngang mảnh, đủ dài để viết lên.
FILL_RULE_MAX_H = 1.5
FILL_RULE_MIN_W = 10.0
# Gạch trải gần hết khung region là nét kẻ bảng, không phải chỗ điền.
FILL_RULE_MAX_W_RATIO = 0.9
FILL_RULE_Y_SLACK = 2.0    # gạch nằm ở hoặc ngay dưới baseline
FILL_RULE_ROW_TOL = 2.5    # hai dòng cùng một hàng khi baseline lệch dưới ngần này
FILL_RULE_GAP_TOL = 8.0    # khe cho phép giữa mép chữ và mép gạch


def horizontal_rules(page) -> list:
    """Nét kẻ ngang mảnh trên trang → [(x0, y0, x1, y1)]."""
    return [(d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1)
            for d in page.get_drawings()
            if d["rect"].height <= FILL_RULE_MAX_H and d["rect"].width >= FILL_RULE_MIN_W]


def fill_in_rules(reg: dict, page_rules: list) -> list:
    """Nét gạch chân dành cho người điền tay, nằm GIỮA chữ của region → [[x0,y0,x1,y1]].

    Biểu mẫu (Terms of Warranty, thoả thuận đại lý) chừa chỗ điền bằng một nét vẽ vector.
    Mask cố ý không xoá line-art nên nét đó sống qua paint, trong khi `tokenize` gộp mọi
    khoảng trắng thành một dấu cách — bản dịch không tạo lại được khe, chữ chạy đè lên gạch
    và ô trống hết dùng được.

    Điều kiện quyết định là **có chữ ở CẢ HAI phía trên cùng một hàng**. Luật lỏng hơn (chỉ
    đòi gạch nằm trong dải mực của một dòng) đo trên 5 tài liệu cho 6 đúng / **11 oan** —
    toàn bộ 11 ca oan là nhãn chú thích hình có đường dẫn ngang (`Handle`, `Drill template`,
    `Battery side wall-mounted bracket` của Lite quick guide), nơi chữ chỉ nằm một bên.
    Thêm điều kiện hai phía: **6 đúng / 0 oan** trên cùng tập đo.
    """
    c = reg["container"]
    cw = c[2] - c[0]
    hits = []
    for x0, y0, x1, y1 in page_rules:
        if x1 - x0 > FILL_RULE_MAX_W_RATIO * cw:
            continue
        band = [ln for ln in reg["lines"]
                if ln["bbox"][1] <= y0 <= ln["bbox"][3] + FILL_RULE_Y_SLACK]
        if not band:
            continue
        ybase = min(l["spans"][0]["origin"][1] for l in band)
        row = [ln for ln in reg["lines"]
               if abs(ln["spans"][0]["origin"][1] - ybase) <= FILL_RULE_ROW_TOL]
        left = any(abs(ln["bbox"][2] - x0) <= FILL_RULE_GAP_TOL for ln in row)
        right = any(abs(ln["bbox"][0] - x1) <= FILL_RULE_GAP_TOL for ln in row)
        if left and right:
            hits.append([x0, y0, x1, y1])
    return hits


SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_ROOT, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

# State machine — spec §11.5. Value: các trạng thái được phép chuyển đến.
STATUS_TRANSITIONS = {
    "INGESTED": {"PREFLIGHTED", "CANCELLED"},
    "PREFLIGHTED": {"TRANSLATED", "MANUAL_DTP", "REJECTED", "CANCELLED"},
    "TRANSLATED": {"RENDERED", "CANCELLED"},
    "RENDERED": {"NEEDS_REVIEW", "AUTO_QA_PASS", "CANCELLED"},
    "NEEDS_REVIEW": {"TRANSLATED", "HUMAN_APPROVED", "MANUAL_DTP", "REJECTED", "CANCELLED"},
    "AUTO_QA_PASS": {"HUMAN_APPROVED", "CANCELLED"},
    "HUMAN_APPROVED": {"RELEASED", "CANCELLED"},
    "RELEASED": {"REVOKED"},           # thu hồi release (approve.py --decision revoke)
    "REVOKED": {"TRANSLATED", "CANCELLED"},  # re-run stage 4-8 sau khi thu hồi
    "MANUAL_DTP": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}

# Status mà stage 2/3/5 chạy lại được. `REVOKED` có trong danh sách vì thu hồi tồn tại để
# sửa lỗi của bản đã phát hành — kể cả lỗi LAYOUT, mà sửa layout thì bắt buộc re-run từ
# stage 2. Trước 1.8.0 chỉ `validate_responses` nhận REVOKED, hai stage kia thì không, nên
# thu hồi xong là bế tắc. Mọi status ở đây phải đi tới được TRANSLATED (xem selftest).
RERUNNABLE_STATUSES = ("PREFLIGHTED", "NEEDS_REVIEW", "REVOKED")

SEVERITIES = ("P0", "P1", "P2")


class BlockingError(Exception):
    """Fail-closed: lỗi chặn stage; caller thoát exit code 2."""


def refuse_if_released(job, stage: str) -> None:
    """Chặn stage render/QA chạy trên job đã RELEASED.

    Vì sao: `approve.py` **copy** `render/draft.pdf` sang `output/translated-approved.pdf`.
    Chạy lại `fit_paint` sau đó làm draft đổi mà file trong `output/` giữ nguyên — job vẫn
    ghi RELEASED trong khi file mang nhãn "approved" là bản cũ. Sự cố thật 2026-08-06: bản
    phát hành thiếu đúng ba sửa đổi vừa được yêu cầu, chỉ phát hiện nhờ so sha256 bằng tay.

    Muốn sửa tiếp thì `approve.py --decision revoke` trước — revoke tự đổi tên output thành
    `REVOKED-<ts>.pdf` nên dấu vết luôn khớp trạng thái. Muốn thử engine mới trên bản đã phát
    hành thì chạy trên BẢN SAO của job.
    """
    if job.status() == "RELEASED":
        raise BlockingError(
            f"{stage}: job đang RELEASED — chạy lại sẽ làm render/draft.pdf lệch khỏi "
            "output/translated-approved.pdf đã duyệt. Thu hồi trước "
            "(`approve.py --decision revoke`), hoặc thử nghiệm trên bản sao của job.")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def slug(stem: str, max_len: int = 60) -> str:
    s = stem.lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] or "pdf"


def new_job_id(pdf_path: str, source_sha256: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{slug(stem)}__{source_sha256[:8]}__{ts}"


def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def append_jsonl(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_default_config() -> dict:
    with open(os.path.join(ASSETS_DIR, "engine_config_default.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Translation authenticity (chống pseudo-translation / copy-through) ──
# Sự cố 2026-08-04: agent thay stage 4 bằng script dictionary → 76% target trùng
# source. Các heuristic dưới đây là input cho P0 gate không waive được.
_AUTH_PH_RE = re.compile(r"⟦[A-Z]+_\d+⟧")
# [^\W\d_] = unicode letter thuần — KHÔNG dùng dải À-ỹ vì nó chứa cả ký hiệu ×, ÷
_AUTH_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_AUTH_LETTER_RE = re.compile(r"[^\W\d_]")
_AUTH_VI_RE = re.compile(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọ"
                         r"ốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", re.IGNORECASE)


def authenticity_check(source: str, target: str, target_lang: str = "vi",
                       min_words: int = 4, keep_terms=()) -> str | None:
    """Phân loại một cặp source/target của translate-region.

    Trả về:
      None           — không có dấu hiệu bất thường (hoặc region quá ngắn để xét)
      "identical"    — region đáng dịch nhưng target trùng source (chưa dịch)
      "lang_suspect" — target dài nhưng gần như không có chữ tiếng Việt
                       (chỉ xét khi target_lang == "vi")
      "truncated"    — target mất khối lượng nội dung so với source. Hai mức:
                       (a) source >=6 từ mà target <45% — sự cố 2026-08-04 #3
                           (mục an toàn 147→29 từ) và 2026-08-05 (câu miễn trừ
                           trách nhiệm 11 từ bị ghi đè bằng tiêu đề 3 từ — sàn
                           cũ 12 từ để lọt đúng vì thiếu 1 từ);
                       (b) source >=12 từ mà target <60% — audit bản Lite đã
                           RELEASED tìm thấy 9 region mất nguyên câu an toàn
                           (cấm ngắn mạch, cấm nối tiếp, tiếp địa, Bước 1 lắp
                           đặt) đều nằm ở ratio 0.45–0.59, trong khi mọi cột
                           dịch đạt không có cặp nào dưới 0.60. Bản dịch VI
                           chuẩn của tài liệu này giữ >=75% số từ EN.
    """
    src = _AUTH_PH_RE.sub(" ", source)
    tgt = _AUTH_PH_RE.sub(" ", target)
    # Region mà source CHỈ gồm thuật ngữ `keep` của glossary thì giữ nguyên là đúng, không
    # phải "chưa dịch". Ca thật: `Shanghai PYTES Energy Co., Ltd.` — glossary ghi rõ keep vì
    # là tên pháp nhân, nhưng Gate 2 vẫn báo TRANSLATION_IDENTICAL và làm gate đỏ.
    # Chỉ bỏ qua khi KHÔNG còn từ nào ngoài các term đó; region lẫn văn xuôi vẫn được xét.
    if keep_terms:
        residue = src
        for term in sorted(keep_terms, key=len, reverse=True):
            if term:
                residue = re.sub(rf"(?i)(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
                                 " ", residue)
        if not _AUTH_WORD_RE.findall(residue):
            return None
    # URL/email là nội dung không dịch — loại khỏi phép đo để không làm nhiễu
    # word-count lẫn tỷ lệ dấu tiếng Việt (edge: gate2 đo trên text đã restore
    # placeholder nên URL thật xuất hiện trong target).
    _noise = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\S+")
    src = _noise.sub(" ", src)
    tgt = _noise.sub(" ", tgt)
    if len(_AUTH_WORD_RE.findall(src)) < min_words:
        return None  # label/số/địa chỉ ngắn — identical hợp lệ
    src_c = re.sub(r"\s+", " ", src).strip().lower()
    tgt_c = re.sub(r"\s+", " ", tgt).strip().lower()
    if src_c == tgt_c:
        return "identical"
    src_w = len(_AUTH_WORD_RE.findall(src))
    tgt_w = len(_AUTH_WORD_RE.findall(tgt))
    if src_w >= 6 and tgt_w < 0.45 * src_w:
        return "truncated"
    if src_w >= 12 and tgt_w < 0.60 * src_w:
        return "truncated"
    if target_lang == "vi":
        alpha = _AUTH_LETTER_RE.findall(tgt)
        if len(alpha) >= 20 and len(_AUTH_VI_RE.findall(tgt)) / len(alpha) < 0.05:
            return "lang_suspect"
    return None


def authenticity_cfg(cfg: dict) -> dict:
    """Ngưỡng authenticity từ engine config, default an toàn cho job cũ."""
    a = cfg.get("translation", {}).get("authenticity", {})
    return {"identical_ratio_max": a.get("identical_ratio_max", 0.05),
            "lang_suspect_ratio_max": a.get("lang_suspect_ratio_max", 0.05),
            "min_words": a.get("min_words", 4)}


def make_issue(code: str, severity: str, stage: str, detail: str,
               page: int | None = None, region_id: str | None = None) -> dict:
    assert severity in SEVERITIES, severity
    return {"code": code, "severity": severity, "stage": stage, "detail": detail,
            "page": page, "region_id": region_id, "ts": utc_now()}


class Job:
    """Một PDF = một job directory (SKILL.md §2-3)."""

    SUBDIRS = ("input", "model", "translation", "render", "qa/page_png", "qa/diffs",
               "review", "output", "logs")

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    # ── paths ──
    def p(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    @property
    def yaml_path(self) -> str:
        return self.p("input", "job.yaml")

    @property
    def source_pdf(self) -> str:
        return self.p("input", "source.pdf")

    def ensure_dirs(self) -> None:
        for d in self.SUBDIRS:
            os.makedirs(self.p(d), exist_ok=True)

    # ── job.yaml ──
    def load(self) -> dict:
        with open(self.yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save(self, meta: dict) -> None:
        tmp = self.yaml_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, self.yaml_path)

    @property
    def config(self) -> dict:
        return self.load()["config"]

    # ── fingerprint (SKILL.md §3: resume phải re-verify) ──
    def verify_fingerprint(self) -> None:
        meta = self.load()
        actual = sha256_file(self.source_pdf)
        if actual != meta["determinism"]["source_sha256"]:
            raise BlockingError(
                f"source fingerprint mismatch: job.yaml={meta['determinism']['source_sha256'][:12]} "
                f"actual={actual[:12]} — source đã thay đổi, tạo job mới thay vì resume")

    # ── status ──
    def status(self) -> str:
        return self.load()["status"]

    def set_status(self, new: str, note: str = "") -> None:
        meta = self.load()
        cur = meta["status"]
        if new == cur:
            return
        if new not in STATUS_TRANSITIONS.get(cur, set()):
            raise BlockingError(f"illegal status transition {cur} -> {new}")
        meta["status"] = new
        meta.setdefault("status_history", []).append(
            {"from": cur, "to": new, "ts": utc_now(), "note": note})
        self.save(meta)
        self.log_event("status", "info", "STATUS", f"{cur} -> {new} {note}".strip())

    def mark_stage(self, stage: str, state: str = "done") -> None:
        meta = self.load()
        meta.setdefault("stages", {})[stage] = {"state": state, "ts": utc_now()}
        # Đóng dấu engine ở MỌI stage. 1.8.0 mới chỉ cho `extract_group` làm mới, nên job
        # chạy tiếp fit_paint/qa/approve bằng engine mới hơn vẫn khai engine của lần extract
        # cuối — đo được 2026-08-06: ba job khai 1.8.0 trong khi render và QA do 1.8.1/1.8.2
        # sinh ra. Tuple determinism phải tả đúng engine đã chạm vào job lần cuối, nếu không
        # người tái lập job sẽ checkout nhầm phiên bản.
        meta.setdefault("determinism", {})["engine_version"] = ENGINE_VERSION
        self.save(meta)

    # ── structured log (spec §16) ──
    def log_event(self, stage: str, level: str, code: str, msg: str,
                  page: int | None = None, region_id: str | None = None) -> None:
        append_jsonl(self.p("logs", "events.jsonl"),
                     {"ts": utc_now(), "stage": stage, "level": level, "code": code,
                      "msg": msg, "page": page, "region_id": region_id})

    # ── lock (SKILL.md §3: single-writer) ──
    def acquire_lock(self, stage: str):
        return _JobLock(self, stage)

    # ── issues gộp từ mọi artifact (cho summary/qa) ──
    def collect_issues(self) -> list:
        issues = []
        pf = load_json(self.p("model", "preflight.json"))
        if pf:
            issues += pf.get("issues", [])
        for name in ("regions_issues", "validate_issues"):
            issues += load_json(self.p("model", f"{name}.json"), [])
        rm = load_json(self.p("render", "render_manifest.json"))
        if rm:
            issues += rm.get("issues", [])
        qa = load_json(self.p("qa", "report.json"))
        if qa:
            issues += qa.get("issues", [])
        return issues

    def severity_counts(self, issues: list | None = None) -> dict:
        issues = self.collect_issues() if issues is None else issues
        out = {s: 0 for s in SEVERITIES}
        for i in issues:
            out[i["severity"]] = out.get(i["severity"], 0) + 1
        return out

    # ── JOB_SUMMARY.md ──
    def write_summary(self, next_action: str) -> None:
        meta = self.load()
        issues = self.collect_issues()
        sev = self.severity_counts(issues)
        lines = [
            f"# JOB SUMMARY — {meta['job_id']}",
            "",
            f"- **Status:** {meta['status']}",
            f"- **Source:** `{os.path.basename(meta['source_name'])}` "
            f"(sha256 `{meta['determinism']['source_sha256'][:12]}…`, {meta['page_count']} trang)",
            f"- **Ngôn ngữ:** {meta['config']['languages']['source']} → {meta['config']['languages']['target']}",
            f"- **Issues:** P0={sev['P0']}  P1={sev['P1']}  P2={sev['P2']}",
            f"- **Cập nhật:** {utc_now()}",
            "",
            "## Stages",
            "",
            "| Stage | Trạng thái |",
            "|---|---|",
        ]
        for st in ("preflight", "extract_group", "translate_prep", "translate",
                   "validate", "fit_paint", "qa", "approve"):
            info = meta.get("stages", {}).get(st)
            lines.append(f"| {st} | {info['state'] + ' ' + info['ts'] if info else 'pending'} |")
        if issues:
            lines += ["", "## Issues (mới nhất 30)", "",
                      "| Severity | Code | Page | Region | Detail |", "|---|---|---|---|---|"]
            for i in issues[-30:]:
                lines.append(f"| {i['severity']} | {i['code']} | {i.get('page','')} | "
                             f"{(i.get('region_id') or '')[:24]} | {i['detail'][:90]} |")
        lines += ["", "## Next action", "", next_action, ""]
        with open(self.p("JOB_SUMMARY.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


class _JobLock:
    def __init__(self, job: Job, stage: str):
        self.job, self.stage = job, stage
        self.path = job.p(".lock")

    def __enter__(self):
        # Mọi stage đều vào qua đây, nên đây là chỗ duy nhất bảo đảm được cây thư mục job.
        # `ensure_dirs()` trước 1.9.2 chỉ chạy MỘT LẦN ở preflight, nên job nào thiếu thư
        # mục thì mọi stage sau đổ ngay tại lệnh ghi: `Job.p()` chỉ ghép chuỗi, không tạo
        # thư mục. Hai ca thật đều cùng gốc này: 2026-08-06 `output/` không có nên
        # `copyfile` của approve ném FileNotFoundError (vá cục bộ ở 1.8.2), và
        # `qa_gates` lưu PNG vào `qa/page_png/` cũng đổ y hệt khi thư mục vắng.
        # Thư mục RỖNG biến mất qua git/zip/rsync và job dựng bằng engine cũ có SUBDIRS
        # ngắn hơn — nên không thể coi "preflight đã tạo rồi" là bảo đảm.
        self.job.ensure_dirs()
        if os.path.exists(self.path):
            try:
                old = json.load(open(self.path, encoding="utf-8"))
                os.kill(old["pid"], 0)  # raises nếu pid chết
                raise BlockingError(f"job đang bị lock bởi pid {old['pid']} (stage {old['stage']})")
            except (ProcessLookupError, PermissionError, ValueError, KeyError, json.JSONDecodeError):
                pass  # stale lock → takeover
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "stage": self.stage, "ts": utc_now()}, f)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        return False


def load_glossary(job: Job) -> list[dict]:
    """Glossary đã freeze trong input/, fallback default của skill."""
    import csv
    path = job.p("input", "glossary.csv")
    if not os.path.exists(path):
        path = os.path.join(ASSETS_DIR, "default_glossary.csv")
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("term"):
                out.append({"term": row["term"].strip(), "type": row.get("type", "keep").strip(),
                            "target": (row.get("target") or "").strip()})
    return out


def exit_blocking(job: Job | None, stage: str, err: BlockingError) -> None:
    msg = str(err)
    if job is not None:
        job.log_event(stage, "error", "BLOCKING", msg)
        try:
            job.write_summary(f"BLOCKED tại stage `{stage}`: {msg}")
        except Exception:
            pass
    print(f"BLOCKING [{stage}]: {msg}", file=sys.stderr)
    sys.exit(2)
