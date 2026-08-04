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

import yaml

ENGINE_VERSION = "1.1.0"
LAYOUT_MODEL_VERSION = "lg-basic-2"

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
    "RELEASED": set(),
    "MANUAL_DTP": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}

SEVERITIES = ("P0", "P1", "P2")


class BlockingError(Exception):
    """Fail-closed: lỗi chặn stage; caller thoát exit code 2."""


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
