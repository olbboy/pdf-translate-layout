# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [1.9.8] - 2026-08-07

### Fixed

- **`infer_alignment` now counts agreeing lines instead of measuring a
  max-minus-min spread.** A spread lets a *single* stray line decide the whole
  block. Real case: an eight-line left-aligned paragraph, every line starting at
  26.8, that `merge_paragraph` had joined with a right-placed table caption on
  the last line — the left spread jumped to 268.5 against a right spread of
  176.8, so `min` picked `right` and the entire paragraph shifted right. Counting
  how many lines share an edge (within 1pt) leaves the stray line holding one
  vote.

  **Evidence escape hatch:** when no edge is shared by at least two lines, the
  old spread rule still applies. Without it, genuinely centred two-line cells get
  forced left — measured across 5 jobs, four `Charge: …/Discharge: …` cells in
  merged columns broke.

  Measured over 258 multi-line regions across 5 jobs: **exactly 6 regions change,
  all to `left`, all of them correctly** — two spec-table label cells, the
  section-7 paragraph, and two cells in another datasheet. Nothing moves to
  `center` or `right`.

  No `region_id`, `container` or translation change — existing jobs re-run
  stages 2 through 7.

## [1.9.7] - 2026-08-07

### Fixed

- **A bold sub-heading that *opens* a region now gets the `emphasis` role.** Source
  documents often put a bold sub-heading (`Danger`, `General Requirements`,
  `Cleaning`, `WARNING`) and the prose that follows it into a single rawdict
  block, so they become one region. The old rule in `build_runs` only granted
  `emphasis` when `i > 0`, and its closing line — `if not any(role == "label"):
  runs[0]["role"] = "body"` — forced run 0 back to `body`. Stage 6's
  `role_style()` returns the **first** run matching a role, which was that bold
  run, so the **entire region** painted bold.

  Measured on an HV48100 user manual: **59 regions affected, holding 46% of all
  characters**; the translation came out **50% Noto Sans Bold** where the source
  is 4.5% bold (`Arial-BoldMT` 2848 vs `ArialMT` 60144) and an already-released
  sibling document sits at 13%.

  Now a bold run 0 **followed by at least one non-bold run carrying real text**
  (`lead_in`) becomes `emphasis`. The "real text" condition is load-bearing:
  sources often end a region with a whitespace-only run, and accepting that would
  demote a fully bold line — six chapter rows in another document's contents page
  — after which `role_style("body")` returns that very blank run and the line
  loses its bold. A fully bold region — a real heading — does not qualify and still
  paints bold as before. The "there is always at least one `body` run" invariant
  is kept, but stated correctly: it checks for `body`, not for `label`.

  After re-running the job: **bold went from 50% to 4%**, matching the source.

  This changes `regions.json` but **not `region_id` or `source_hash`** — measured
  on a real job: 0 region ids lost, 0 new, 0 hashes changed, no orphaned
  responses. Existing jobs re-run stages 2 → 2.5 → 3 → 5 → 6 → 7. A response that
  only uses `body` stays valid, because `body` is always present in
  `style_roles`; it simply renders without the bold until the translation splits
  its runs.

## [1.9.6] - 2026-08-07

### Fixed

- **`base_x` now measures from the first inked glyph, not the first span's
  origin.** Source documents often centre text with a *run of spaces* rather than
  an alignment property. A space has advance width but paints nothing, so the
  first span's origin sits at the start of the space run while the real text
  begins further right. Real case, a V5 Series user manual: the `Pictures` header
  cell has `container_x0 = 282.6` and `origin = 282.6`, but its ink starts at
  `325.1`. `tokenize` drops every whitespace token — all 8 Unicode space
  characters tested, including NBSP, fall through `expanded.strip()` — so the
  translation cannot recreate that run and gets dragged back to the start of it.
  Measured drift reached **151pt**, which pushed table header labels into the
  neighbouring column (19 `G4_TABLE_RULE_CROSS` flags in that job alone).

  This is the other half of a bug 1.8.0 fixed: back then `build_lines` was
  switched to `ink_bbox` so cell boxes stopped inflating on leading/trailing
  spaces, but `base_x` kept reading the padded origin.

  Guard: the value is **only raised**, and only for single-line regions or
  regions whose lines all start at the same x (±1pt). Multi-line prose with a
  first-line indent — bulleted lists, for instance — would otherwise have the
  whole block indented, trading one bug for another. It is never lowered: ink
  cannot start left of the origin.

  Measured over the 2 jobs holding a `regions.json` with affected regions: **36
  regions change how they paint** (32 + 4, all `align=left`, guard passing); 47
  `center/right` regions are also offset but **change nothing**, because their x
  comes from the container rather than from `base_x`; 2 regions are correctly
  held back by the guard. Bonus: bulleted-list indentation comes back in the
  other job.

### Not shipped

- **Two alignment heuristics were tried and rejected** for contents-page rows
  that carry their page number inside the same region. (a) "ink starting within
  12pt of the container edge means left-aligned" changed 122 regions and broke
  genuinely centred table cells (row numbers `1`, `2`, `3` in a narrow column sit
  at lgap 8.2pt). (b) "a line filling ≥80% of its container means left-aligned"
  changed 60 regions and broke short centred labels in snug cells
  (`Grounding Cable` at 0.90, `Blink 3` at 0.82). Both trade one defect for
  another. Those rows are really a **two-column-inside-one-region** problem,
  which is what `column_split` (1.9.0) addresses — but it is gated to
  `region_type == table_cell`, and widening it is a separate design job.

  No `region_id`, `container` or translation change — existing jobs re-run
  stages 6-7 only.

## [1.9.5] - 2026-08-07

### Fixed

- **Gate 3's `keep` branch no longer raises false P0s.** The `translate` branch
  was given an escape hatch in 1.4.5 ("23/23 of this gate's P0s were false
  alarms"); the `keep` branch kept comparing strings in *reading order* and so
  carried that whole class of bug through 1.9.4. A `keep` region is never touched
  by the engine, so the only question worth asking is whether its glyphs survived
  — and neither the order nor the spacing of the extracted string answers that.

  Real case, 2026-08-07, an HV48100 user manual: a `1\n2` callout extracts as
  `'2 1'` inside its own container box in **both `source.pdf` and `draft.pdf`** —
  the original document fails the very same check, which settles it. Because
  `G3_KEEP_LOST` is a P0 and P0s cannot be waived, a job with 565/565 clean
  regions could not be released.

  The branch is now tiered like the `translate` one: exact match, or match after
  stripping whitespace, passes; **all characters present but in a different order
  → `G3_KEEP_REORDERED` (P2)** with a note to check it by eye; **characters
  actually missing → `G3_KEEP_LOST` (P0)**, which now names the missing
  characters instead of just saying text was lost. The comparison lives in
  `char_deficit()` — a character multiset that deliberately ignores order and
  whitespace, used **only** for the survived-or-not question; geometry remains
  Gate 4's job.

  Measured before landing, over **255 keep regions across the 4 jobs that still
  have a `regions.json`**: 254 match exactly as before, **exactly 1 case moves
  P0 → P2, and 0 cases drop from P0 to clean**. Nothing else loosens: a neighbour
  bleeding into the clip box cannot mask a missing character (`'1 2'` against
  `'2 4'` still reports `'1'` missing), and losing one of two identical
  characters is still caught, because the count is a multiset.

  No layout change, no `region_id` change, no translation change — existing jobs
  only need stage 7 re-run.

## [1.9.4] - 2026-08-07

### Changed

- `assets/default_glossary.csv` no longer ships one customer's brand and product
  names (`Pytes`, `V16 Lite`, `V16`); 47 → 44 entries. They belong in that
  customer's own profile, not in the default glossary of a general-purpose PDF
  translation engine — all three were verified present in the customer profile
  first, so nothing is lost. The file is only a fallback for jobs that pass no
  `--glossary`, but its SHA-256 enters the determinism tuple, which is why this
  needs a version bump rather than a silent edit.
- Removed two references pointing into a private document repository (the design
  spec and a plan file); both were dead links once the engine stands alone.

### Fixed

- **A false claim in §1.6.** The text said the authenticity thresholds "were
  settled into a single combined ratio in 1.5.0". Reading the code says
  otherwise: `qa_gates.py` still measures `identical` and `lang_suspect`
  **separately, 5% each, joined by `or`**. That decision was never implemented
  and the gap is still open as of 1.9.4. The document now states what the code
  actually does.
- Status line at the top of SKILL.md still read `v1.9.2`.

## [1.9.3] - 2026-08-06

### Changed

- The engine now lives in its own repository. **No processing code changed.**
  Three things had been anchored to its old location inside a product's document
  folder: `lock-engine.sh` sat outside the skill with a hard-coded local path and
  now lives in `scripts/` and locates itself; the integrity manifest hashed
  **absolute** paths, so moving or cloning the engine broke it, and now hashes
  paths relative to the skill root.

### Fixed

- **The manifest did not protect the shell scripts.** It hashed only
  `.py`/`.yaml`/`.csv`, leaving `setup.sh` and `install.sh` editable by an agent
  while `lock-engine.sh verify` still reported the engine intact — the exact hole
  the guardrail exists to close. It now hashes `.sh` too: 13 → 16 files.

### Added

- `PDFTL_JOBS` environment variable, so `lock-engine.sh verify` can still scan a
  job root for agent-generated `.py` files now that job folders live outside the
  skill directory.

## [1.9.2] - 2026-08-06

### Fixed

- The job directory tree now self-heals at **every** stage, not only at
  preflight. `Job.p()` merely joins path strings, so any missing directory makes
  the next write fail. `ensure_dirs()` and `SUBDIRS` were both already correct,
  but `ensure_dirs()` ran exactly once at job creation — a guarantee that expires
  for jobs built by an older engine with a shorter `SUBDIRS`, and for jobs moved
  through git, zip or rsync, because **empty directories do not survive those**.
  Two real failures share this root: a missing `output/` made approve's
  `copyfile` raise `FileNotFoundError` (patched locally in 1.8.2, so the root
  survived), and `qa_gates` writing PNGs into `qa/page_png/` failed the same way.
  `ensure_dirs()` now runs in `_JobLock.__enter__`; every stage enters through
  `acquire_lock`, so this is the one place that covers both current and future
  stages. Verified by reproducing the failure — delete `qa/page_png`, `qa/diffs`
  and `output` from a job copy, then run `qa_gates`: it completes, producing 15
  PNGs and 6 diffs. Mutation test: drop the `ensure_dirs()` line and all 9
  directories go missing, selftest red.

## [1.9.1] - 2026-08-06

### Fixed

- `decisions.jsonl` is now written only when a decision has **actually taken
  effect**. `approve.py` wrote the decision line on entry — before
  `require_human_terminal` and before the P0/P1 gates. Real incident 2026-08-06:
  a reviewer approved several jobs in a shell loop, where each job demands a
  *different* challenge string `APPROVE <sha8>`; a mistyped string correctly
  blocked the release (job stayed `NEEDS_REVIEW`, `output/` empty) but the log
  still recorded an approval. One session produced **4 phantom lines across 4
  jobs**. `decisions.jsonl` is append-only, so those lines cannot be deleted —
  the audit record of "who approved what" was permanently wrong, failing at
  exactly the thing it exists to protect. Each branch (`reject` / `revoke` /
  `approve`) now calls `record()` after its own gate has passed; the approve
  branch records **immediately before `set_status`**, not after, because the
  release rule requires a released artifact to carry an approver — a `RELEASED`
  job with no decision line is worse than the reverse. `revoke` on a job that was
  never released no longer writes either. The ordering invariant lives in
  `main()` and cannot be tested as a pure function, so the selftest inspects the
  source directly (5 cases, anchored to indentation level).

### Changed

- SKILL.md §4 now forbids approving multiple jobs from a shell loop, and gives
  the command to fetch each job's challenge string in advance.

## [1.9.0] - 2026-08-06

### Added

- **`column_split` — a merged table cell is painted into its real columns.**
  `fit_region` draws every line from the `base_x` of the region's first span, so
  a table row that the PDF declares as ONE cell collapsed against the left margin
  while the header row directly above kept its three columns. Real case: a
  warranty table data row, where `find_tables` correctly returned a single cell
  spanning 65.5→491.6 because the source **draws no vertical rules on data
  rows**, so 1.8.0's `vertical_rules` (right to refuse the split) never applied.
  The row is now split into per-column sub-regions before fitting, each keeping
  its own `base_x`. Evidence that an x is a real column rather than an indent:
  **the same x appears on ≥2 different rows** — a grid repeats, an indent does
  not — plus `region_type == table_cell`, which excludes list labels like `(i)`
  or `a.` that also produce several x values but live in `paragraph`, where
  reflowing into one column is the correct behaviour. Contract with the
  translation: each `\n`-separated segment is one column, left to right; if the
  segment count does not match, the old behaviour stands and the engine does not
  guess. Sub-regions carry the parent's `region_id`, so masking, `painted_ids`
  and Gates 3/4 still score against the parent box.
- **Hand-fill blanks now flow with the translated text.** Forms leave space to
  write on with a **vector underline**; masking deliberately preserves line art
  (`PDF_REDACT_LINE_ART_NONE`) so the rule survives painting, while `tokenize`
  collapses all whitespace to a single space, so the translation could not
  recreate the gap — text ran over the rule and the form became unusable.
  `fill_in_rules` (in `_common.py`, beside `vertical_rules` so every stage reads
  one definition) detects those rules at stage 2 and records them in
  `reg["fill_rules"]`; stage 3 routes a warning into `source_warnings` so the
  model re-creates the blank as a run of `____`; stage 6 removes the original
  rule in a **separate redaction pass with `text=NONE`** — the rule's rect is
  only ~1pt tall but sits on the baseline, so sharing a pass with `text=REMOVE`
  would eat glyphs from regions meant to stay untouched.

### Fixed

- `digit_drift` normalises Unicode superscripts to plain digits before counting.
  Sources print footnote markers as a small-size span (`Energy Retention³`), but
  the engine paints **one font size per region**, so the translation must use
  `¹²³⁴⁵⁶` to stop the marker dropping to the baseline (`năng3` reads as a typo
  in a legal text). Without normalisation every footnote marker was reported as a
  missing digit — 8 false positives on the warranty documents alone — and waiving
  `NUMBER_DRIFT` wholesale would have hidden a genuine drift. The real defect
  (`"3 Interface and Components"` → `"3.1 Dụng cụ"`) is still caught after
  normalisation.

### Note

- No layout model change. `region_id`, `container` and the `responses.jsonl` of
  every existing job are unchanged; old jobs only need stages 5-7 re-run.

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
