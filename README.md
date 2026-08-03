# pdf-translate-layout

**Layout-preserving PDF translation skill for Claude Code (English → Vietnamese).**

Translates technical PDFs — manuals, datasheets, quick guides — while keeping the
original layout intact: images, vector graphics, tables, typography, colors, and
page geometry are preserved and *proven* preserved by automated quality gates.
Releases are fail-closed: nothing ships without gates passing **and** explicit
human approval.

Built as a [Claude Code](https://claude.com/claude-code) skill: deterministic
Python scripts handle extraction, fitting, painting, and QA, while the agent in
your session acts as the translation provider.

> Validated end-to-end on a real 15-page battery installation manual:
> 263 semantic regions, 173 translated, all 7 quality gates passing, output
> within +6% of source file size.

## How it works

The engine never translates raw PDF spans. It works on **semantic regions**
(paragraphs, table cells, captions, labels), fits translations into the original
containers under constraints, and paints styled runs back at exact baselines.

| # | Stage | Runs as | Output |
|---|-------|---------|--------|
| 1 | `preflight.py` | script | Supported-envelope classification, resource manifest |
| 2 | `extract_group.py` | script | Layout graph: regions, reading order, containers, stable IDs |
| 3 | `translate_prep.py` | script | Protected tokens, context, batched translation requests |
| 4 | translate | **agent** | `responses.jsonl` (schema-validated translations) |
| 5 | `validate_responses.py` | script | Placeholder round-trip, NFC, glossary enforcement |
| 6 | `fit_paint.py` | script | Constraint fitting (binary-search sizing), safe redaction, painting |
| 7 | `qa_gates.py` | script | 7 quality gates incl. 300/600 DPI visual diff |
| 8 | `approve.py` | human | Release to `output/` — only after gates pass + approval |

Key properties:

- **Protected tokens** — brands, model numbers, measurements, URLs, standards
  are masked as typed placeholders and round-trip verified 1:1.
- **Constraint-based fitting** — binary-search font sizing with a hard floor
  (85% of source size by default), word-boundary line breaking, explicit `\n`
  hard breaks, alignment preservation.
- **Safe painting** — text-only redaction (`PDF_REDACT_IMAGE_NONE` /
  `LINE_ART_NONE`), no-fill masks that never touch kept text, link restoration,
  native font subsetting.
- **7 quality gates** — decision coverage, translation integrity, rendered-text
  coverage (translated *and* kept regions re-extracted from output), geometry &
  collision, image/vector preservation with pixel proof, tile-based visual diff,
  structural validation.
- **Fail-closed state machine** — `PREFLIGHTED → TRANSLATED → RENDERED →
  NEEDS_REVIEW/AUTO_QA_PASS → HUMAN_APPROVED → RELEASED`. There is no path to
  `RELEASED` that skips human approval. P0 issues can never be waived.
- **Reproducible jobs** — one PDF = one job folder with frozen inputs, the full
  determinism tuple (source/config/font/glossary/prompt fingerprints), and an
  append-only audit trail of reviewer decisions.

## Requirements

- Python ≥ 3.10
- Dependencies: `pip install -r requirements.txt`
  (PyMuPDF is pinned — redaction/subsetting behavior is version-tested)
- Fonts: a Noto pack (Sans/Serif/Mono × Regular/Bold/Italic/BoldItalic) is
  bundled in `assets/fonts/` with pinned SHA-256 manifest and full Vietnamese
  coverage, including stacked diacritics.

## Usage

### As a Claude Code skill

Copy this folder to `~/.claude/skills/pdf-translate-layout` (personal) or
`.claude/skills/` inside a project, then ask Claude to translate a PDF
preserving layout. The agent orchestrates the stages and performs the
translation step itself, following `SKILL.md` and the generated
`AGENT_INSTRUCTIONS.md`.

### Manually (agent-less)

Every deterministic stage is a standalone CLI:

```bash
python3 scripts/preflight.py --pdf manual.pdf --out jobs \
  --domain-context "LFP battery ESS installation; keep brands; imperative safety tone"
python3 scripts/extract_group.py    --job jobs/<job_id>
python3 scripts/translate_prep.py   --job jobs/<job_id>
# fill translation/responses.jsonl (by hand, or any MT system) per AGENT_INSTRUCTIONS.md
python3 scripts/validate_responses.py --job jobs/<job_id>
python3 scripts/fit_paint.py        --job jobs/<job_id>
python3 scripts/qa_gates.py         --job jobs/<job_id>
# review qa/page_png + qa/diffs + JOB_SUMMARY.md, then:
python3 scripts/approve.py --job jobs/<job_id> --approver you --decision approve
```

`selftest.py` runs the pure-function test suite.

### Job folder

```text
jobs/<pdf-slug>__<sha8>__<timestamp>/
├── input/          # frozen: source.pdf (always copied), domain_context.md,
│                   # glossary.csv, job.yaml (full determinism tuple)
├── model/          # preflight, resource manifest, regions.json, fonts
├── translation/    # requests.jsonl, responses.jsonl, AGENT_INSTRUCTIONS.md
├── render/         # draft.pdf + render manifest
├── qa/             # gate report, 300/600 DPI page renders, diff overlays
├── review/         # decisions.jsonl (approver identity + timestamps)
├── output/         # translated-approved.pdf — only after approval
└── JOB_SUMMARY.md  # live status, issues, next action
```

## Data & privacy

**When used as a Claude Code skill, the text content of your PDF is sent to the
LLM provider of your session for translation.** You are responsible for your
own data policy. For sensitive documents, run the manual flow with a private
translation source instead.

Job folders contain document content — they are gitignored by default and
should live on controlled storage.

## Limitations (v1)

- English → Vietnamese is the tested pair; other targets need a font-coverage
  and line-breaking review.
- Text rotation 0/90/180/270° only; rotated multi-line regions are routed to
  review instead of painted.
- Bordered tables only (`find_tables`); borderless tables group as paragraphs.
- Source fonts are never reused — everything maps to the Noto bundle (display
  fonts raise a reviewer flag).
- No OCR: scanned pages are detected and routed to manual DTP, never guessed.
- Code points outside the bundle raise a blocking issue rather than tofu.

## License

- Code: [GNU AGPL-3.0](LICENSE) — chosen to match
  [PyMuPDF](https://github.com/pymupdf/PyMuPDF)'s license, which this project
  depends on.
- Bundled Noto fonts: [SIL Open Font License 1.1](assets/fonts/OFL.txt),
  © The Noto Project Authors.

## Contributing

Issues and PRs are welcome. Please keep the fail-closed invariants intact:
no silent fallbacks, no release paths that bypass gates or human approval, and
every comparator change needs a pixel-proof rationale. Run
`python3 scripts/selftest.py` before submitting.

## Acknowledgments

- [PyMuPDF / MuPDF](https://mupdf.com/) — PDF engine
- [Noto fonts](https://notofonts.github.io/) — typography with full Vietnamese coverage
