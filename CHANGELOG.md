# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [1.8.4] - 2026-08-06

### Added

- `CONSISTENCY_ENTITY` (P1, stage 5): a postal address in the source must
  survive verbatim in the target — only the label is translated. A released
  Vietnamese manual carried `Số 3492 Đường Jinqian, Quận Fengxian` on one page
  while page 1 of the *same* document kept the English address: two different
  addresses in one printed manual, and the translated one is undeliverable.
  `CONSISTENCY_DRIFT` could not see it because it only compares regions whose
  source matches exactly, and the two sources differ. URLs, e-mails and standard
  codes are already masked as placeholders, so postal addresses were the one
  entity class left unguarded. The rule covers exactly that one class: a broader
  entity-grouping design measured 0 true / 3 false positives. Over 1947 regions
  of three documents it fires on 5 — all genuine factory addresses, zero false
  positives — and catches the known-bad translation with 4 missing tokens.
  Labels and country names are deliberately not checked.
- Rule 6c in the generated `AGENT_INSTRUCTIONS.md` so the model is told before
  translating, not corrected after.

## [1.8.3] - 2026-08-06

### Fixed

- `engine_version` in the determinism tuple is now stamped by every stage
  (`Job.mark_stage`), not only by `extract_group`. A job carried on with a newer
  engine still declared the engine of its last extract, so anyone reproducing it
  from that stamp would check out the wrong version. `layout_model_version`
  remains stage-2's to stamp.

## [1.8.2] - 2026-08-06

### Fixed

- Fail-open release gate. `approve.py` flipped the status to RELEASED *before*
  copying `render/draft.pdf` into `output/`, and `Job.p()` only joins paths — a
  job that had never released had no `output/` directory, `copyfile` raised, and
  the job sat at RELEASED **with no released artifact**. Release now writes to
  `<out>.part` first, flips the status after, then renames atomically; failure at
  any step is fail-closed.

## [1.8.1] - 2026-08-06

### Added

- `PH_DIGIT_ADJACENT` (P2, stage 3): warns when the masked source has a digit
  glued to a letter next to a placeholder, and routes the warning into the
  request so the model can resolve it while translating. Real defect: the source
  printed `is1 5V` for `1.5V`, `protect()` masked `5V` and the `1` stayed stuck
  in `is1`, so the translation said "5V" — off by a factor of ten in a
  troubleshooting step. Requiring the adjacent letter is what makes it usable:
  1 hit / 0 false positives over 1243 regions, versus 19 hits / 18 false
  positives without it.

## [1.8.0] - 2026-08-06

### Changed

- Layout model `lg-basic-6` (`lg-basic-5` with paragraph merging off), clearing
  `G4_TABLE_RULE_CROSS` from two independent causes: line bounding boxes counted
  leading/trailing spaces, which have advance but paint nothing, inflating table
  cell containers by up to 7.5pt (`build_lines` now measures the ink box); and
  column splitting required two spaces to call something a column boundary, while
  the source separates columns with a single space — narrowest measured column
  gap 1.33pt, thinner than an ordinary word gap. Splitting now happens at any
  space gap that contains a real vertical rule (1.5pt tolerance). Measured: one
  document 26 → 26 splits (unchanged), the other 26 → 39, all 13 added splits on
  genuine multi-column rows, 0 wrong splits in cell prose.

## [1.7.3] - 2026-08-06

### Changed

- Container expansion now also covers figure captions, diagram labels and short
  labels misfiled as paragraphs, not only headings. Added a fallback expansion
  direction: figure labels usually have a leader line blocking the right side and
  plenty of room on the left, so expanding leftward while anchoring the right edge
  keeps the leader-line attachment point and beats shrinking the text.
  Right-aligned text is expanded leftward for the same reason.

## [1.7.2] - 2026-08-06

### Fixed

- Stages 6 and 7 now refuse to run on a RELEASED job. `approve.py` copies
  `render/draft.pdf` into `output/`; re-running `fit_paint` afterwards changed the
  draft while the released file stayed behind, so the job read RELEASED while the
  approved artifact was stale. Blocking beats detecting: detection depends on
  someone happening to re-run the right stage.

## [1.7.1] - 2026-08-06

### Fixed

- Redaction masks are clipped instead of dropping the whole region. When a mask
  touched a kept-text area the engine dropped the region, which left the original
  English on the page — a table-of-contents line shipped untranslated because its
  dot leader touched the page-number cell. Masks are now clipped horizontally
  (`MASK_CLIPPED`, P2); the region is only dropped if clipping cannot resolve the
  overlap.
- Heading expansion now also triggers when the heading merely shrank below the
  review ratio, not only on outright fit failure, and the expanded container is
  accepted only if the font size actually improves.

## [1.7.0] - 2026-08-05

### Changed

- Layout model `lg-basic-4`: lines of one paragraph are merged **across** rawdict
  blocks (`layout.merge_paragraph`, on by default; off → `lg-basic-3`). PDFs
  routinely put every line in its own block — a 28-line letter was 28 blocks with
  real gaps of 2.72pt — so sentences were torn across regions and Vietnamese
  could not reorder across the boundary. Uses the same detector as the context
  graph. Measured: 833 → 818 regions, 9 merges, 10/10 correct.

### Added

- `STALE_TRANSLATION` (P1): `translation_meta` now stamps `source_hash`, and
  validation reports a region whose `source_text` changed after translation but
  still carries the old target. Measured during a layout-model migration: two
  regions kept their `region_id` while the source grew; one was caught by
  `PLACEHOLDER_MISMATCH`, **one slipped through** at a 0.69 word ratio.

## [1.6.0] - 2026-08-06

### Added

- **Translation Context Graph** (stage 2.5, `build_context_graph.py`): links
  regions that belong together so the model sees the whole sentence instead of
  fragments. Edges: `continues`, `co_figure`, `same_source`, `under_heading`.
  The graph never translates — it only links, by geometry plus regex. The guards
  are the important part: without them 9 of 10 chains outside one page were wrong
  links (numbered headings, table-of-contents lines, `Table N`/`Figure N`,
  `Label: value` lines, chain heads under four words). After guards: 9/9 correct.
- `CONSISTENCY_DRIFT` (P2): one source rendered as two different translations.
  Compared per chain-filtered group, so a fragment of a multi-line cluster that
  happens to match a standalone label is a legitimate difference.

### Changed

- Requests (`req-v2`) carry `chain_source`, `chain_position`, `chain_kind` and
  `co_figure`; neighbour context widened 80 → 240 characters; batches never split
  a chain. Dropped the "prefer fitting the container over translating closely"
  note — it produced telegraphic prose and invented abbreviations.

## [1.5.2] - 2026-08-06

### Added

- `layout.expand_heading` (on by default): a single-line heading that cannot fit
  is expanded into measured empty space instead of shrinking. Region containers
  come from the *source* text box, and Vietnamese is longer — a cover title of
  158pt became 250pt in a 196.6pt box. Expansion stops before any obstacle in the
  same vertical band and stays inside the body margins; a heading centred on the
  page is expanded symmetrically and switched to centre alignment. Applied at
  stage 6, not at extract, because `region_id` derives from container coordinates.

## [1.5.1] - 2026-08-05

### Fixed

- `authenticity_check` accepts `keep_terms`: a region whose source consists only
  of glossary `keep` terms is correctly left identical rather than reported as
  untranslated.

## [1.5.0] - 2026-08-05

### Fixed

- Inter-word gap width is measured with the font of the adjacent token, not the
  region's first font. Mixed sans/mono lines were off by 2.38pt per gap — four
  gaps is 9.5pt, enough to push a line out of its cell.
- Vertical budget is measured from `base_y`, not from the container height: text
  is painted from the source span's origin, so the space above `base_y` cannot
  hold a line.

## [1.4.5] - 2026-08-05

### Changed

- Gate 3 measures coverage, Gate 4 measures geometry. Target text that is on the
  page but outside its container is now `G3_TARGET_OUTSIDE_BOX` (P2) pointing at
  the Gate 4 warning, instead of `G3_TARGET_NOT_FOUND` (P0). Measured across five
  translation columns of one job: 23/23 P0s from this gate were false. Genuinely
  missing text is still P0 and non-waivable.

## [1.4.4] - 2026-08-05

### Fixed

- Gate 3's read window at the bottom edge now uses the same descent slack the
  fitter is allowed (`max(tol_pt, container_tol_y_em × size)`). The old fixed 2pt
  window put the last line of a multi-line region outside the read area and
  produced non-waivable P0s for text that was demonstrably on the page: 11/11 were
  false. Horizontal and top edges unchanged.

## [1.4.3] - 2026-08-05

### Added

- `TRANSLATION_CARRY_THROUGH` (**P0, non-waivable**): the target keeps ≥3
  lowercase words of the source and more than twice as many as it has target
  words. Catches find-replace posing as translation — a released document had a
  whole start-up/shutdown procedure where only the word `Step` was translated.
  Only lowercase words count, so proper nouns kept verbatim are not flagged.
  Measured over 7185 pairs from 14 jobs: 0 hits on every passing translation.

## [1.4.2] - 2026-08-05

### Added

- `NEGATION_DROP` (P1): the source negates (not/never/forbidden/without) and the
  target has no negation left.
- `SYMBOL_DRIFT` (P1): the `<>≤≥±` multiset must match the source — flipping `≤`
  to `≥` in a temperature range changes a safety limit. 0 false positives
  measured.

### Changed

- Truncation floor lowered 12 → 6 words plus a second tier (source ≥12 words,
  target <60%). An audit found a released manual missing ~10 sentences — short
  circuit and series-connection prohibitions, half a grounding instruction, a
  whole installation step — all sitting at ratios 0.45–0.59, under the old floor.

## [1.4.1] - 2026-08-05

### Added

- `NUMBER_DRIFT` (P1, warning): the target's digit multiset must match the
  source. A model once translated a table of contents into a *different* table of
  contents — eight lines, different numbers and different titles — with every gate
  green, because the prose was fluent, Vietnamese, and not identical to the
  source. Compared as digit strings, so `1,000` ↔ `1.000` does not trip it.

## [1.4.0] - 2026-08-05

### Changed

- Layout model `lg-basic-3`: table rows typed as space-separated text are split
  along the column grid, the wrap budget subtracts the actual indent, and
  `fit_paint` and `qa_gates` share one descent tolerance
  (`qa.container_tol_y_em`). The model was renamed because `regions.json` for the
  same source differs from `lg-basic-2`, so old jobs cannot be reproduced by the
  new engine and must be re-run.

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
