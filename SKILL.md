---
name: pdf-translate-layout
description: Dịch PDF có text layer (mặc định EN→VI) bảo toàn layout, ảnh, vector, bảng và typography theo PDF Translation Engine v1. Dùng khi user muốn dịch PDF giữ nguyên format ("translate PDF keep layout", dịch manual/datasheet/quick guide sang tiếng Việt), hoặc tiếp tục một translation job đã có. Fail-closed; output cuối chỉ phát hành khi quality gates pass và có human approval.
license: AGPL-3.0
compatibility: Agent-agnostic theo chuẩn Agent Skills — chạy trên Claude Code, OpenAI Codex, Google Antigravity (và agent tương thích SKILL.md khác). Cần shell macOS/Linux + Python >= 3.10; bootstrap deps một lần bằng `bash scripts/setup.sh` (cần network lúc cài); runtime offline, fonts đã bundle.
metadata:
  version: "1.2.1"
---

# pdf-translate-layout

> **Trạng thái:** RELEASED v1.2.1 — scripts Milestone 1-4 core hoạt động, đã E2E-test
> full trên tài liệu thật 15 trang (263 regions, 7/7 gates PASS). Portable đa agent
> (Claude Code / Codex / Antigravity — §9), có authenticity gates chống
> pseudo-translation (§1.6, §7). Giới hạn v1 ở §11.
> **Spec nguồn:** PDF Translation Engine v1 (rev 1.4) — tài liệu thiết kế nội bộ; kiến trúc tóm tắt trong [README](README.md)
> **License:** [AGPL-3.0](LICENSE) (cùng license với PyMuPDF — ADR-009); fonts Noto theo [OFL-1.1](assets/fonts/OFL.txt)

## 1. Nguyên Tắc Bắt Buộc

1. **Fail-closed:** input ngoài supported envelope tạo issue có mã; không silent fallback, không rasterize ngầm.
2. **Release rule:** `output/translated-approved.pdf` CHỈ được ghi khi **quality gates PASS VÀ human approval tường minh** (ghi vào `review/decisions.jsonl` kèm approver + timestamp). Agent không bao giờ tự approve — **enforce bằng code:** `approve.py --decision approve` yêu cầu terminal tương tác (TTY) + gõ chuỗi xác nhận `APPROVE <sha8>`; agent session headless trên mọi platform bị chặn, reviewer phải tự chạy lệnh trong terminal. Auto-QA pass chỉ tạo `render/draft.pdf`. Release sai có thể thu hồi: `approve.py --decision revoke` (không cần TTY) → status `REVOKED`, xoá output, cho phép re-run stage 4-8.
3. **Artifact là source of truth:** mọi run kết thúc bằng job folder trên disk, không chỉ chat text.
4. **Source immutable:** không bao giờ sửa PDF gốc; mỗi render ghi file mới.
5. Scripts đảm nhiệm phần deterministic (extract, fit, paint, QA); agent đảm nhiệm dịch và điều phối. Agent không tự đặt tọa độ text.
6. **Authenticity (enforce bằng code, không chỉ văn bản):** bản dịch stage 4 PHẢI do model của session sinh cho từng request — CẤM mọi logic dịch nằm trong code (dictionary/bảng tra cứu tự chế, find-replace, fallback copy-source). Script chỉ được là **phương tiện ghi** các bản dịch model đã sinh sẵn (embedded verbatim), đặt trong job folder — không đặt trong `scripts/` của skill. Validator + Gate 2 đo tỷ lệ region đáng dịch có target trùng source hoặc sai ngôn ngữ đích; vượt ngưỡng (`translation.authenticity`, default 5%) → **P0 `TRANSLATION_COVERAGE_FAIL` / `TARGET_LANG_FAIL` — không waive được, không thể release** (sự cố Antigravity 2026-08-04).

## 2. I/O Contract

**Input:**

```text
required:
  --pdf <path>            # hoặc input folder chứa source.pdf
optional:
  --out <root>            # default: ./jobs
  --domain-context <text|path>   # xem mục 5
  --glossary <csv>
  --customer-facing       # bật chế độ nghiêm ngặt (mục 5)
  --job <job_id>          # resume job đã có
  --source-lang en --target-lang vi   # default en→vi
  --provider-model <id>   # model id thật của agent dịch stage 4 — ghi vào determinism
                          # tuple (vd claude-fable-5, gpt-5.2-codex, gemini-3-pro)
```

**Output (luôn ghi, kể cả khi preflight REJECTED/MANUAL_DTP_REQUIRED):**

```text
jobs/<job_id>/
├── input/                      # frozen sau khi tạo job; read-only
│   ├── source.pdf              # luôn COPY, không symlink
│   ├── domain_context.md       # effective merged (file + CLI), kèm provenance header
│   ├── glossary.csv            # nếu có
│   └── job.yaml                # effective config snapshot + determinism tuple
├── model/
│   ├── preflight.json
│   ├── resource_manifest.json  # before-snapshot cho Gate 5 (images/drawings/links/boxes)
│   ├── regions.json            # layout + semantic model, latest
│   └── fonts.json
├── translation/
│   ├── requests.jsonl
│   ├── responses.jsonl         # schema-validated
│   └── tm_hits.jsonl           # optional
├── render/
│   ├── draft.pdf
│   └── render_manifest.json
├── qa/
│   ├── report.json
│   ├── page_png/               # 300 DPI, flagged 600 DPI
│   └── diffs/
├── review/
│   └── decisions.jsonl         # append-only; approver + timestamp
├── output/
│   └── translated-approved.pdf # chỉ khi thỏa Release rule (mục 1.2)
└── JOB_SUMMARY.md              # status theo state machine + issues + next action
```

**job.yaml determinism tuple (bắt buộc đủ):** `source_sha256`, `domain_context_sha256`, `glossary_version`, `engine_version`, `config_version`, `font_pack_version`, `layout_model_version`, `provider_model_version`, `prompt_version`, `pymupdf_version`.

## 3. Job Identity

```text
job_id = <slug(pdf_stem)>__<source_sha8>__<UTC yyyymmddThhmmss>
# ví dụ: v16_lite_quick_guide__a1b2c3d4__20260804T153012
```

- `slug()`: thay ký tự ngoài `[A-Za-z0-9_-]` bằng `_`, gộp `_` lặp, lowercase, tối đa 60 ký tự.
- Chạy lại cùng PDF → job mới; `--job <id>` → resume.
- **Resume phải re-verify `source_sha256` khớp job.yaml; lệch → hard error** (source đã đổi).
- Single-writer: tạo `.lock` trong job folder khi chạy; job đang lock không cho session khác ghi.

## 4. Pipeline Stages

| # | Stage | Thực thi | Output chính |
|---|---|---|---|
| 1 | preflight | `scripts/preflight.py` | `model/preflight.json`, `model/resource_manifest.json` |
| 2 | extract + group | `scripts/extract_group.py` | `model/regions.json`, `model/fonts.json` |
| 3 | translate-prep | `scripts/translate_prep.py` | `translation/requests.jsonl` |
| 4 | translate | **agent (in-session)** | `translation/responses.jsonl` |
| 5 | validate | `scripts/validate_responses.py` | reject sai schema/placeholder → agent sửa |
| 6 | fit + paint | `scripts/fit_paint.py` | `render/draft.pdf`, `render_manifest.json` |
| 7 | qa | `scripts/qa_gates.py` | `qa/report.json`, PNG, diffs, cập nhật JOB_SUMMARY |
| 8 | approve | `scripts/approve.py --approver <name>` | `decisions.jsonl`, promote `output/` |

- Mỗi stage idempotent; resume = chạy stage kế tiếp còn thiếu; mọi stage mở đầu bằng verify fingerprint.
- **Stage 4 chạy bởi chính agent của session** (Claude Code / Codex / Antigravity) bằng model của session — không gọi API ngoài, không cần API key riêng. Agent truyền model id thật qua `--provider-model` khi tạo job (mục 2). Dịch thật từng request theo batch — mọi lối tắt script/dictionary bị chặn P0 (mục 1.6).
- **Batching stage 4:** mỗi batch chứa region theo reading order kèm type/neighbors/container hint; **không cắt batch giữa cross-page continuation group**; không nhét cả PDF vào một turn.
- **Explicit line break:** `\n` trong text của target run = hard break (giữ cấu trúc label/value); fitter tôn trọng, validator/QA so sánh sau khi collapse whitespace.
- Translation memory: chỉ seed TM từ jobs đã **approved**.

## 5. Domain Context Policy

- Nguồn: `--domain-context` (text hoặc path) và/hoặc `input/domain_context.md` trong input folder. Merge CLI đè lên file, **kết quả merge được freeze vào `input/domain_context.md`** kèm provenance marker.
- Template: [assets/domain_context.template.md](assets/domain_context.template.md).
- **Default:** thiếu context → preflight issue `DOMAIN_CONTEXT_MISSING` mức **P2 (warning)**, pipeline vẫn chạy, JOB_SUMMARY nhắc.
- **`--customer-facing`:** issue thành **P1 (blocking)** — dừng trước translate cho đến khi có context.
- **Advisory-only.** Precedence: `protected tokens > glossary > domain_context > model choice`. Hard policy (number format, font-size thresholds, protected classes, gates) chỉ đổi qua `job.yaml` có cấu trúc — free-text context không override được, và gates enforce bằng code nên context không thể mở khóa release.

## 6. Data & Privacy

> **Disclosure (bắt buộc giữ trong README khi publish):** text content của PDF được gửi tới LLM provider của session đang chạy để dịch. Người dùng tự chịu trách nhiệm data policy đối với tài liệu của họ. Nội bộ Pytes: đã approve dịch tài liệu nội bộ qua Claude API (ADR-009).

- Không log toàn bộ nội dung tài liệu ra ngoài job folder.
- Job folder có thể chứa nội dung nhạy cảm — đặt `--out` vào storage có kiểm soát.

## 7. Quality Gates (tóm tắt — chi tiết ở spec §10)

Gate 1 decision coverage → Gate 2 translation integrity (placeholder round-trip, glossary, **authenticity: identical-target + target-language ratio, P0 khi vượt ngưỡng — mục 1.6**) → Gate 3 rendered-text coverage (translated + `keep` regions nguyên vẹn, NFC, tofu, color tolerance, htmlbox scale trong policy) → Gate 4 geometry/collision → Gate 5 image/vector preservation (so với `resource_manifest.json`) → Gate 6 visual diff 300/600 DPI → Gate 7 structural validation. Release cần: không còn P0/P1 unresolved **và** human approval.

So sánh resource/visual dùng **content digest + geometric tolerance (~1pt)** và **meaningful-diff threshold** — không dùng bit-exact/md5 equality: tọa độ round-int flaky tại biên `.5`, renderer lệch ±1/255 theo cache state (spec §9.5, §20.1).

## 8. Environment

- **Resolve interpreter — một lệnh, mọi agent, mọi máy:**

  ```bash
  bash scripts/setup.sh          # in `PYTHON=<path>`; tự tạo .venv trong skill folder nếu cần
  bash scripts/setup.sh --check  # chỉ kiểm tra, không cài (exit 3 nếu thiếu env)
  ```

  Thứ tự ưu tiên: `$PDFTL_PYTHON` → `<skill>/.venv/bin/python3` → python3 hệ thống thỏa pin.
  Agent PHẢI dùng đúng `$PYTHON` này cho mọi stage script — không hardcode đường dẫn
  interpreter của riêng agent nào.
- Deps trong [requirements.txt](requirements.txt) — Python >= 3.10; `pymupdf==1.27.2.3` pin cứng
  (đổi pymupdf phải chạy lại golden tests; dep phụ dùng floor version, setup.sh chỉ enforce pin pymupdf).
- **Runtime offline:** network chỉ cần một lần lúc `setup.sh` cài deps.
- `assets/fonts/`: Noto pack **đã bundle** — 10 static faces (Sans/Serif/Mono × Regular/Bold/Italic/BoldItalic), SHA-256 pinned trong `fonts_manifest.json`, full Vietnamese coverage đã test kể cả dấu chồng (spec §7.2).

## 9. Chạy Đa Agent (Claude Code / Codex / Antigravity)

Skill theo chuẩn mở [Agent Skills](https://agentskills.io) — cùng một folder, hành vi
đồng nhất trên cả ba agent. Không cấu hình gì thêm ngoài đăng ký discovery:

| Agent | Discovery trong repo này | Cài global (mọi workspace) | Gọi skill |
|---|---|---|---|
| Claude Code | `<git root>/.claude/skills/` và `.agents/skills/` (symlink sẵn) | `~/.claude/skills/` | auto theo description hoặc `/pdf-translate-layout` |
| Codex CLI/IDE | `<git root>/.agents/skills/` (tìm từ cwd → repo root) | `~/.agents/skills/` | `/skills`, gõ `$pdf-translate-layout`, hoặc auto |
| Antigravity | `<workspace root>/.agents/skills/` | `~/.gemini/config/skills/` | auto theo description hoặc mention tên skill |

- Đăng ký: `bash scripts/install.sh repo` (symlink tại git root — đã chạy sẵn cho repo này),
  `bash scripts/install.sh global`, `bash scripts/install.sh status`. Tool không theo
  symlink → thêm `--copy`.
- Antigravity mở **subfolder** làm workspace (vd `V16 Battery/`) sẽ không thấy
  `.agents/` ở git root — dùng bản global.
- **Quy tắc parity:** agent nào cũng chạy đúng các stage script §4 qua shell với `$PYTHON`
  từ `setup.sh`; stage 4 agent tự dịch in-session và ghi model id qua `--provider-model`;
  không agent nào được tự approve (mục 1.2 — enforce: approve đòi TTY người thật),
  tự đặt tọa độ text (mục 1.5), hay sinh bản dịch bằng script/dictionary
  (mục 1.6 — P0 không waive được).
- Codex sandbox: scripts chỉ đọc/ghi trong workspace và job folder — không cần escalation;
  chỉ `setup.sh` lần đầu cần network approval.

## 10. Package Layout

```text
pdf-translate-layout/
├── SKILL.md
├── README.md
├── CHANGELOG.md
├── LICENSE                     # AGPL-3.0
├── requirements.txt            # deps (pymupdf pin cứng; Python >= 3.10)
├── .gitignore                  # .venv/, __pycache__/, *.lock
├── scripts/
│   ├── setup.sh                # resolve/bootstrap interpreter (§8)
│   ├── install.sh              # đăng ký discovery đa agent (§9)
│   ├── _common.py              # job infra: identity, lock, status machine, summary
│   ├── preflight.py            # stage 1
│   ├── extract_group.py        # stage 2
│   ├── translate_prep.py       # stage 3
│   ├── validate_responses.py   # stage 5
│   ├── fit_paint.py            # stage 6
│   ├── qa_gates.py             # stage 7 (gates 1-7)
│   ├── approve.py              # stage 8
│   └── selftest.py             # pure-function tests
└── assets/
    ├── fonts/                  # Noto pack 10 faces + fonts_manifest.json (SHA-256) + OFL.txt
    ├── engine_config_default.yaml
    ├── default_glossary.csv
    └── domain_context.template.md
```

## 11. Giới Hạn v1 (đã chủ ý, theo supported envelope của spec)

- Painting qua `insert_text` per-segment (không dùng `insert_htmlbox`); justified
  alignment chưa hỗ trợ — map về left/center/right.
- Rotation: 0/90/180/270; rotated **multi-line** → P1 review, không tự paint.
- `reuse_source_font: false` — luôn map sang Noto bundle (nhánh conservative §7.3);
  display font → P1 `FONT_DISPLAY_FALLBACK` cho reviewer xác nhận.
- Symbol/CJK fallback families chưa bundle — codepoint ngoài coverage → blocking
  `FONT_GLYPH_MISSING` (fail-closed, không tofu).
- Table detection theo `find_tables` (bordered); bảng không kẻ khung có thể được
  group như paragraph.
- Continuation qua page break: heuristic cơ bản (câu chưa kết + chữ thường đầu trang).
- Review = chat + `qa/page_png` + `qa/diffs` (internal/pilot tier — M4 UI để sau).
