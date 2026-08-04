# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [1.1.0] - 2026-08-04

Cross-agent portability release — one package, identical behavior in
Claude Code, OpenAI Codex, and Google Antigravity (Agent Skills standard).

### Added

- `scripts/setup.sh` — unified interpreter contract for every agent: resolves
  `$PDFTL_PYTHON` → local `.venv` → any system Python satisfying the pins,
  bootstraps a venv when needed, and always prints `PYTHON=<path>`
  (fail-closed validation of the PyMuPDF pin).
- `scripts/install.sh` — discovery registration: repo-level
  (`.agents/skills/` + `.claude/skills/`, relative symlinks safe to commit)
  and global (`~/.agents/skills`, `~/.claude/skills`,
  `~/.gemini/config/skills`); `--copy` fallback, `status` inspection.
- `preflight.py --source-lang / --target-lang` — language pair overrides
  recorded into the frozen job config (previously documented in SKILL.md §2
  but not implemented).
- `preflight.py --provider-model` — records the actual translating model id
  in the determinism tuple (e.g. `claude-fable-5`, `gpt-5.2-codex`,
  `gemini-3-pro`).
- SKILL.md frontmatter `license`, `compatibility`, `metadata.version` per the
  Agent Skills specification, plus a cross-agent operations section
  (discovery paths, invocation, parity rules, sandbox notes).

### Changed

- Engine version 1.1.0. Default `provider_model_version` is now agent-neutral
  `in-session` (was `claude-in-session`); the real model id comes from
  `--provider-model`.
- Environment docs no longer assume an agent-specific interpreter path;
  every stage runs through the `setup.sh` contract.

## [1.0.0] - 2026-08-04

First public release. Validated end-to-end on a real 15-page technical manual
(263 regions, 173 translated, all 7 quality gates passing).

### Added

- Eight-stage pipeline: preflight → extract/group → translate-prep → agent
  translation → validate → fit/paint → QA gates → human approval.
- Semantic-region layout graph with table cells (`find_tables`), heading /
  list / caption / diagram-label / header-footer classification, two-column
  reading order, label-cluster splitting by x-position, cross-page
  continuation linking, and stable region IDs (fingerprint + quantized
  geometry anchor).
- Typed protected tokens (`URL`, `EMAIL`, `BRAND`, `STD`, `MEAS`, `MODEL`)
  with 1:1 round-trip validation; NFC normalization and a versioned
  full-width punctuation allowlist.
- Constraint-based fitter: binary-search font sizing with 85% hard floor /
  95% review threshold, word-boundary wrapping, explicit `\n` hard breaks,
  alignment preservation, per-codepoint font fallback with sub-run splitting.
- Safe painting: text-only redaction with no-fill masks that never intersect
  kept text, small-glyph-heights mode, link restoration, native font
  subsetting, optimized save.
- Seven quality gates, including keep-region survival checks, tofu/NFC
  verification, geometry & collision checks, image/vector preservation with
  visible-area pixel proof (digest + geometric tolerance, tile-based
  meaningful-difference criterion), 300/600 DPI visual diff with mask
  exclusion, and structural validation.
- Fail-closed job state machine with append-only reviewer audit trail;
  `approve.py --waive CODE=REASON` for reviewer-approved P1 findings
  (P0 findings can never be waived).
- Bundled Noto Sans/Serif/Mono pack (10 static faces, SHA-256 pinned,
  full Vietnamese coverage verified including stacked diacritics).
- Pure-function self-test suite (`selftest.py`).
