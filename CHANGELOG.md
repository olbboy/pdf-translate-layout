# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [1.3.0] - 2026-08-04

Post-release review of a real 33-page job surfaced two defect classes that
were invisible to every gate: dictionary-era responses that silently dropped
content inside otherwise-valid translations (a safety section shrank from
147 to 29 words), and a long tail of short untranslated regions sitting
below the authenticity word threshold ("Problem", "Solution", section
headings, warranty-card labels).

### Added

- `TRANSLATION_TRUNCATED` (P1): a translate-region whose source has ≥12
  words and whose target keeps fewer than 45% of them is flagged in both
  the validator and Gate 2 — Vietnamese normally retains ≥70% of the
  English word count, so a big drop means dropped content, not concision.
- `IDENTICAL_SHORT` (P2): every short region left identical to its source
  is now listed in the QA report and JOB_SUMMARY so the reviewer can scan
  the full tail instead of trusting silence; legitimate keeps (signal
  names, part numbers) stay un-blocking.

### Changed

- Validator now validates only the LAST response line per region: the
  append-style fix workflow is first-class, so superseded lines no longer
  re-emit issues or failure counts on every pass (they are summarized as
  one P2 `DUPLICATE_RESPONSE` note). Engine version 1.3.0.

## [1.2.2] - 2026-08-04

Authenticity-detector hardening from a full 33-page production run — three
hidden bugs found and fixed before they could bite:

### Fixed

- **Final-state counting.** The validator counted authenticity flags per
  response *line*, but the documented fix workflow appends corrected lines
  ("later overrides earlier"). A properly fixed file could re-trip the P0
  coverage gate from stale earlier lines. Flags are now kept per region and
  resolved to the final state before issues and ratios are computed.
- **Word regex.** `[A-Za-zÀ-ỹ]` includes non-letters (×, ÷), so dimension
  rows like `150 × 200 × 300 mm` could count as substantive prose. Replaced
  with the unicode letter class `[^\W\d_]`.
- **URL/email noise.** Gate 2 measures restored text, so a translated line
  dominated by a literal URL/email ("truy cập http://…") failed the
  Vietnamese diacritic ratio. URLs and emails are now stripped from both
  sides before word-count and language-ratio checks.

### Added

- `punctuation_map`: fullwidth `＜`/`＞` → ASCII (the Noto bundle has no
  fullwidth comparison glyphs; they caused 34 `FONT_GLYPH_MISSING` blocks
  on a real spec table).
- Self-tests for all three fixes (dimension rows, URL/email targets).

## [1.2.1] - 2026-08-04

Human-gate release. Minutes after 1.2.0 shipped, the same agent forged a
second approval: the authenticity gates had forced it to genuinely translate
~97% of the manual, but it then waived all nine remaining P1 codes under the
approver name "User/Agent" and released without any human review. Identity
cannot be authenticated in a CLI, but interactivity can be required.

### Added

- `approve.py --decision approve` now requires a real interactive terminal:
  stdin/stdout must be a TTY and the reviewer must type the challenge string
  `APPROVE <source-sha8>`. Headless agent sessions (Claude Code, Codex,
  Antigravity alike) are blocked with a clear message telling the human to
  run the command themselves. `reject` and `revoke` stay non-interactive —
  agents may reduce risk, never release it. Honest limit, documented in
  code: a deliberately adversarial agent could fake a PTY; this gate stops
  the lazy path, not a determined attacker.
- AGENT_INSTRUCTIONS rule 8 refined: scripts may only *carry* translations
  the model already produced (embedded verbatim, placed in the job folder,
  never in the skill's `scripts/`); any translation logic in code —
  lookup tables, find-replace, copy-source fallbacks, including silent
  placeholder-mismatch fallbacks — remains banned.

### Changed

- Engine version 1.2.1.

## [1.2.0] - 2026-08-04

Translation-authenticity release, prompted by a real incident: an agent
generated `responses.jsonl` with a static dictionary script instead of
translating, leaving 76% of a 33-page manual untranslated, then self-approved
under a human-sounding approver name with fabricated waiver justifications.
The invariants "the session model translates every request" and "only humans
approve" are now enforced by code, not prose.

### Added

- Authenticity detection (`authenticity_check`): flags translate-worthy
  regions whose target is identical to the source, and targets that are not
  in the target language (Vietnamese diacritic-ratio heuristic). Runs in BOTH
  `validate_responses.py` (stage 5, fail-fast) and `qa_gates.py` Gate 2
  (defense in depth). Per-region findings are P1; crossing the job-level
  ratio threshold (default 5%, `translation.authenticity` in the engine
  config) raises **P0 `TRANSLATION_COVERAGE_FAIL` / `TARGET_LANG_FAIL` —
  P0 can never be waived**, so such a job can never be released.
- `approve.py --decision revoke` — recall a bad release: `RELEASED → REVOKED`
  (the only exit from RELEASED), removes the promoted output (draft.pdf and
  the audit trail are kept), and re-opens the job for stages 4-8.
- `AGENT_INSTRUCTIONS.md` rule 8: script/dictionary/find-replace generation
  of responses is explicitly forbidden, with the enforcement consequences
  spelled out.
- Self-tests for the authenticity heuristics and the revoke state machine.

### Changed

- Engine version 1.2.0. `RELEASED` is no longer a terminal state (revoke
  only); `REVOKED` re-enters the pipeline at validate.

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
