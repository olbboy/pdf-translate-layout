# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [1.9.36] - 2026-08-07

### Fixed

- **Degenerate roles** — a role the translation points at that carries no alphanumeric
  character at all in the source. Real case: the "Note：..." callouts in V16 Lite have a
  `body` role consisting of **a single `：` in Song**, while `Note` and the whole sentence
  after it are `emphasis` `Arial-BoldMT`. The translation emits one `body` run, so
  `role_face` obeyed the 1.9.35 rule correctly and still rendered the whole sentence in Noto
  Serif. 3 regions, 261 characters, across two already-released V16 Lite documents.

  A degenerate role now borrows from the region — but **family and weight are borrowed from
  two different measurements**, because they are two different properties:

  - **Family** (`serif`/`mono`) comes from the longest run *that has alphanumerics*.
    Punctuation carries no family identity: the `（A）` cell in the V5 Series manual has `A`
    in sans and both fullwidth parentheses in Song, and sans is the right answer.
  - **Weight/italic** comes from the longest run among *all* runs, punctuation included,
    because weight is a property of the ink mass. Two opposing real cases pin this down: a
    **table-of-contents line** is a BOLD 21-character chapter title plus 38 REGULAR leader
    dots (measuring on alphanumeric runs alone would bold the whole line — breaking 38
    characters to fix 21); a **callout** is 4 bold characters, a regular `：`, then 98 bold
    characters (measuring on all runs makes bold win). Both match the source.

  Measured: 19 regions have a degenerate role corpus-wide. After re-running — V16 Lite quick
  guide **1.281% -> 0.000%**, user manual **0.295% -> 0.000%**, V5 Series manual **0.021% ->
  0.000%**; the 7 TOC lines stay `Noto Sans Regular` exactly as before, and the repaired
  callout is now `Noto Sans Bold`, matching its four siblings on the same page.

  **Stage 6 only** — released jobs re-run stages 6 -> 7 to benefit.

## [1.9.35] - 2026-08-07

### Fixed

- **Typeface for a role now follows the run with the most ink (`role_face`); colour still
  follows the first inked run (`role_style`).** 1.9.34 stopped blank runs from deciding, but
  a short *inked* run still won. V16 Lite quick guide opens a region with **a single `：` in
  `AdobeSongStd-Light`** followed by 210 characters of `ArialMT` in the same role — one
  character set the typeface for the whole paragraph. Measured on the **released** files:
  quick guide **7.94%** Noto Serif characters, V16 Lite user manual **1.26%**. Same mechanism
  behind the `≥` leading `≥6000Cycles` in the V5 datasheet (7 serif characters) and `(A)` in
  the V5 Series manual.

  A one-run translation must pick a single face for the region, so picking the face that
  covers the most source characters is the smallest deviation. Ties keep the earlier run;
  whitespace does not count.

  **Why a separate function instead of widening `role_style`:** that function also decides
  **colour**. Measured across the corpus, taking colour from the dominant run would drag the
  labels of **7** datasheet spec regions from black `#000101` to the value column's grey
  `#585857`. Dominant is right for typeface and wrong for colour, so the two questions are
  now two functions. `key_for` reads only `mono/serif/bold/italic`, so this does not touch
  font size (the 37 regions where the two runs differ in `size` are unaffected).

  Real blast radius: **serif changes in 3 regions, bold in 0, colour in 0**. Re-running the
  V5 datasheet: **0.27% -> 0.000%**. The V5 Series manual keeps 6 serif characters in `(A)`
  at size 8, and that is **correct** — the `body` role of that cell genuinely is Song (the
  fullwidth parentheses `（）`); only the `A` is `emphasis` Arial.

  **Stage 6 only** — released jobs re-run stages 6 -> 7 to benefit.

## [1.9.34] - 2026-08-07

### Fixed

- **`role_style` now takes the style of the first run with *ink*, not the first run matching
  the role.** Source PDFs routinely open a paragraph with a whitespace span in a different
  font. The measured case, HV48100 user manual page 5: run 0 is **a single space** in
  `AdobeSongStd-Light` (serif), run 1 is 175 characters of `ArialMT` (sans), both role
  `body`. A one-run `body` translation inherited the space's style, so **the whole paragraph
  was painted in Noto Serif** against a sans original.

  Same defect class `ink_base_x` fixed on the x axis in 1.8.0/1.9.9, and the same thing 1.9.7
  had to guard against locally in `build_runs` (its `lead_in` rule requires the following run
  to carry real text). 1.9.34 puts the guard in `role_style` itself, so every caller is
  covered rather than just the `emphasis` path.

  Blast radius, counting regions with >= 2 runs of one role where the first is blank and
  differs in `serif`/`bold` from the first inked run: **HV48100 user manual 13 regions /
  7,738 translated characters, V5 datasheet 1 region, V5 Series manual 1 region**. Re-running
  the HV48100 manual: Noto Serif characters **12.5% -> 0.00%**; Noto Sans Bold unchanged at
  4.5%, and every other QA issue identical (P1=112, P2=127 before and after).

  When every run of the role is blank the old behaviour is kept; a role absent from `runs`
  still falls back to `runs[0]`. Blankness is `str.strip()`, so nbsp and ideographic space
  do not get a vote either.

  **Stage 6 only** — no change to `regions.json`, `region_id`, `source_hash` or translations.
  Released jobs re-run stages 6 -> 7 to benefit; responses are never orphaned.

## [1.9.33] - 2026-08-07

### Fixed

- **Serif-ness is now decided by the font *name*, not by the PDF flag.** The `serif` flag
  (bit 2 of the FontDescriptor `/Flags`) is whatever the producing tool chose to write, and
  across this corpus it is wrong almost everywhere: of the **9 fonts carrying the serif flag,
  8 are actually sans** — `RanyLight/Regular/Medium/Bold` (a geometric sans brand face),
  `NotoSansHans-Regular` and `SourceHanSansCN-Medium` (the word "Sans" is in the name),
  `FandolHei-Regular`, `CTChaoHeiSF`, `STXihei` (Hei/黑体 means sans). Exactly **one** was
  right: `AdobeSongStd-Light` (Song/宋体 is a serif). The measured consequence: the four Pytes
  datasheets rendered **79–98% of their characters in Noto Serif** against a sans original,
  and the Pi Station 261 EX datasheet rendered **100%**.

  The rule checks `sans` hints first (so "Sans Serif" is not misread), then `serif` hints, and
  falls back to **sans** when the name says nothing. Sans is the safer default: the flag has
  been shown unusable, technical documents are overwhelmingly sans, and guessing wrong this
  way costs only the serifs — guessing wrong the other way changes the voice of an entire
  marketing document. Hints cover CJK family names too: `song`/`ming`/`mincho`/`batang`/
  `simsun` are serif, `hei`/`gothic`/`yahei`/`dengxian` are sans.

  Measured over 2578 regions of five released documents: **0 region ids lost or added, 0
  `source_hash` changed**. **8 regions change run structure** — every one of them a *merge* of
  two runs that were only ever split by the bogus flag (Arial + NotoSansHans, Rany + Arial);
  role order is preserved and no role is lost.

  Layout, `region_id`, `source_hash` and translations are untouched — an existing job picks
  this up by re-running stage 2 → 7, with no orphaned responses.

## [1.9.32] - 2026-08-07

### Fixed

- **UN transport codes are standards, not model numbers** — `STD_RE` now also accepts `UN`.
  Without it, `MODEL_RE` matched only `UN38` and left `.3` behind, so a region containing
  nothing but the mark `UN38.3` had a residual of `"3"` and `classify_action` filed it as
  `translate` instead of `keep`. The engine then repainted a mark that never needed
  translating — and **lost its typeface doing so**: the source sets it in `Impact` (very heavy)
  but declares `bold=False`, so it mapped to Noto Sans Regular and the certification mark came
  out as thin body text. Real cases: the cover pages of the HV48100 and V5° datasheets.

  Measured across **2666 regions in 7 jobs: exactly 11 regions change**, all of them `UN38.3`
  (11) and `UN3480` (1), with **0 false matches** — `Unit 3` and `UNIT` do not match, because
  the rule requires a digit directly after `UN`.

  A `keep` region is left untouched, so the original glyphs survive; Gate 3's keep branch
  still checks it. A certification line with more than one item (`CE, IEC62619, UN38.3`) stays
  `translate`, since text remains outside the placeholders.

  Layout, `region_id` and `source_hash` are untouched, but the **placeholder numbering** of
  those 11 regions changes, so an already-translated job must re-run stage 3 → 7 and
  re-translate exactly those regions.

## [1.9.31] - 2026-08-07

### Added

- **Two-column blocks aligned with runs of spaces are now painted as a grid**
  (`spec_grid_cells` in `_common.py`, `spec_grid` in `fit_paint.py`). Marketing datasheets
  lay their specification tables out with padding spaces instead of ruling lines, so
  `find_tables` sees no table and the whole block lands in a single `paragraph` region.
  `tokenize` drops every whitespace token, `fit_region` draws every line from `base_x`, and
  `line_baselines` enforces `max(anchor, previous + leading)` — so the value cell can never
  sit beside its label. The whole table collapsed into one left column, and every gate stayed
  green because none of them measures column structure. Measured on all four Pytes
  datasheets: the defect was present in every one.

  `column_split` (1.9.0) does not cover this: it is gated on `table_cell` and models **one**
  row spanning several columns, not a block of many rows.

  Evidence for a real grid is a **column-anchor vote** (`spec_row_votes`): for each row, take
  the widest ink gap; if it is at least `SPEC_MIN_PAD_PT` (12 pt) and at least
  `SPEC_MIN_GAP_PT` (30 pt) from the region's left ink edge, the ink starting after that gap
  is that row's candidate. At least `SPEC_MIN_ANCHOR_ROWS` (2) rows **on the same page** must
  agree. Votes are tallied per page, not per region, because one grid is often split across
  regions: the three feature captions of a datasheet are three separate one-line regions that
  cannot repeat anything on their own, yet all vote for the same x. A region only takes the
  grid if it holds a vote at that anchor — a page containing a grid does not turn every
  region into one.

  Every measurement is at **character** level, not span level: two columns often share one
  span when they use the same font and size, and a span's bbox includes padding spaces, so a
  span-level gap measures 0 on exactly the rows that type label and value on one line.

  Fail-closed everywhere it is ambiguous — two anchors tied, or a row whose left ink overruns
  its right ink — returns no grid rather than guessing one.

  Contract with the translation: one `\n`-separated segment per cell, left to right then down.
  Stage 3 prints the measured grid into `source_warnings` (masked with the region's own
  placeholder numbering, via the new shared-counter form of `protect`), stage 5 raises P1
  `SPEC_GRID_DROPPED` when the segment count does not match, and stage 6 falls back to the old
  single-column behaviour rather than guessing an assignment.

  Table-of-contents lines are the same shape but belong to `leader_split`/`dot_leader`; a
  right column made only of 1–3 digit integers is excluded.

  Measured before shipping: **0 false positives across 2578 regions** of five released
  documents (three user manuals, one quick guide, one table-based datasheet), with 0 region
  ids lost or added and 0 `source_hash` changed. On the four datasheets the rule fires on 16
  regions, all of them real grids.

  `spec_cells` is pure metadata, like `fill_rules` and `bullet_lines`: `region_id`,
  `container` and `source_hash` are untouched, so an already-translated job only needs
  stage 2 → 7 re-run and no response is orphaned.

### Fixed

- **`target_segments` replaces the `"\n".join(runs)` idiom.** A run is a unit of *style*, not
  a unit of paragraph; joining runs with `"\n"` invents one extra segment boundary per run
  pair, so any target with a bold lead-in plus body text was counted with too many segments.
  Segment boundaries live inside the text, and a segment takes the role of the run that opens
  it.

## [1.9.30] - 2026-08-07

### Fixed

- **Two neighbouring labels could each expand into the same gap and end up
  overlapping.** `expand_container` read its obstacles from the **source** page, which
  keeps the result independent of paint order but misses that a neighbour made of
  translated text expands too. Each region individually respected the neighbour's source
  bbox; together they overlapped. Real case from a production job: a row of figure captions
  under a strip of images. The left caption expanded right to x=107.99 while its neighbour
  expanded left to x=106.39 — the glyphs overlapped by **1.60 pt**. Gate 4 did not catch it:
  it measures container overflow, not collision with a neighbouring region.

  Fix: obstacles that are themselves translated text on the same page (`share_gap`, matched
  by identity) now block at the **midpoint of the gap**, minus `SIBLING_GAP_PT` (1.0 pt) on
  each side. Two neighbours expanding toward each other therefore stop 2.0 pt apart, and the
  outcome still does not depend on paint order. Fixed obstacles — images, vectors, rules —
  keep blocking at their own edge, since expanding to the midpoint of a picture means
  painting over it.

  Measured on the two affected jobs, before → after: 1 → 0 overlapping runs on the job that
  showed the defect, 0 → 0 on the other (its 2 flagged runs are vertical text, a measurement
  artefact of the horizontal scan, present identically before the change).

## [1.9.29] - 2026-08-07

### Added

- **`approve.py` makes the release evidence read-only.** On release it drops write
  permission on `model/`, `render/`, `output/`, `translation/*.jsonl` and
  `qa/report.json`; `--decision revoke` restores it. Not frozen: `review/`,
  `logs/`, `JOB_SUMMARY.md`, `input/job.yaml` — revoke has to write those — and not
  the whole of `qa/`, because `compare.pdf` and `draft-raster.pdf` must stay
  rebuildable after release.

  Why this is needed even after 1.9.28 gated `validate_responses`: a status check
  inside a stage is a **voluntary** fence — it only stops whatever agrees to call
  it. The hand-written job helper `write_responses.py` does not, and on 2026-08-07
  it overwrote `responses.jsonl` of an already released job. Filesystem permissions
  are not voluntary — the same argument `lock-engine.sh` makes for the engine
  (§1.2). Manual escape hatch: `chmod -R u+w <job>`.

## [1.9.28] - 2026-08-07

### Fixed

- **`validate_responses` now refuses at the gate**, the way `extract_group` and
  `translate_prep` do. It already read `RERUNNABLE_STATUSES`, but only to decide
  the closing status transition — there was no entry check. The consequence: the
  stage could write `target_text` into `model/regions.json` of an **already
  released** job, so the model would stop describing the approved output.

  It happened on 2026-08-07: a loop ran over two jobs without checking status;
  three stages refused, this one went through (as did `write_responses.py`, a
  job-local helper that deliberately has no gate). Nothing was lost that time —
  the inputs were identical and the function is idempotent — but that was luck,
  not a barrier. The new test requires all three stages to hold the check at the
  entry point, not merely to mention the constant.

## [1.9.27] - 2026-08-07

### Fixed

- **`horizontal_rules` only accepts SOLID strokes.** A blank someone writes on is
  always a solid rule; a dashed horizontal stroke in these documents is a
  **contents-page leader**. Without that condition `fill_in_rules` mistook three V5
  contents rows for fill-in blanks and `fit_paint` raised `FILL_BLANK_DROPPED` — a
  false positive a reviewer has to waive on **every** document with a table of
  contents. Worse: had the translation happened to contain a run of `____`, the
  blank-rule erasure pass would have deleted the leader as well.

  Measured across the corpus: the 5 Terms of Warranty documents — exactly the kind
  this feature exists for — carry **15-16 thin horizontal rules each and not one
  dashed**; the only three dashed ones anywhere are the V5 contents leaders. The
  guard drops precisely those three false positives and loses no real case. V5 P1
  goes **23 → 20**, and the waiver list drops from 5 codes to 4.

## [1.9.26] - 2026-08-07

### Changed

- **Bullet marks now follow the text, instead of the text having to follow the
  marks.** 1.9.20 anchored each translated paragraph to its source paragraph's
  baseline so the text would line up with the marks — correct while the marks stay
  put, but when a translated item runs shorter than its source the slack turns
  into **blank space between items**. The layout "skips lines", which no gate
  measures and only a human reading the page can see.

  The old marks are now erased in the line-art redaction pass (the same mechanism
  as `fill_rules` and the contents leaders) and redrawn after the text is placed,
  offset by the difference in baseline. The mark's path is **copied verbatim** from
  the source with `dy` added — not rebuilt as a generated circle, because sources
  use `•` `∘` `◇` `▪` and guessing the shape wrong is immediately visible.

  A region whose marks can move has **baseline anchoring switched off**: the text
  flows continuously and the marks come along. The three pieces — erase, redraw,
  disable anchoring — only work together, so each has its own mutation test.

  Gate 6 gets the union of each mark's old and new box, the same declaration the
  leaders use. Gate 5 is unaffected: the vector cluster count is unchanged (one
  erased, one drawn). On HV48100: **58 marks moved**; pages 8, 9, 11 and 19 lose
  both the bullet overprints and the line skips.

## [1.9.25] - 2026-08-07

### Added

- **Bullet marks are now the first-choice pattern for mapping paragraphs.** The
  `•` `◇` `∘` of the source are small **drawings**, not characters, so they never
  appear in a region's `lines` — yet they are the strongest evidence of item
  structure there is: one mark, one item, no inference. The three patterns from
  1.9.11/1.9.15 all reason from text geometry and fail on exactly those sources
  that break lines mid-sentence. `bullet_lines` (stage 2, pure metadata like
  `fill_rules`) records which lines carry a mark; the head of the region, before
  the first mark, still gets split by `paragraph_starts`.

  Signature: a stroke under 8pt each way, within 30pt of the region's left edge,
  centred less than 7pt above the baseline it marks, and **outside every line's
  ink** — a mark overlapping text is a symbol in a sentence or part of a figure.

  Measured across the jobs on hand: 18 regions carry marks. Where the item count
  matches the translated segment count — **9 regions agree exactly with the old
  patterns, 3 regions the old patterns gave up on, 0 disagreements**. Purely
  additive: no match means falling back, never forcing.

  On HV48100, 15 of 15 marked regions now map by mark. The p19 `CAUTION` block —
  which 1.9.20 declared unsolvable in the engine — now places all 9 items
  correctly, including the `Relative humidity` item `paragraph_starts` missed.
  That earlier verdict was wrong because it only looked for signal in the text;
  the real signal was drawn on the page all along.

## [1.9.24] - 2026-08-07

### Fixed

- **`ink_base_x` applies its "raise, never lower" clamp per LINE**, then takes the
  minimum, instead of clamping the whole region with the first line's origin. The
  two halves do different jobs: `max(origin, ink)` within a line stops a negative
  side bearing (an italic `f`, a `J`) from dragging `base_x` off; `min(...)` across
  lines brings it to the region's real left edge. The whole-region clamp can only
  ever fire when the **first** line sits to the right of another line's ink — and
  in exactly that case it is always wrong.

  Real case, V5 p6: `find_tables` merges the `DC Breaker` and `Cycle Life` rows
  into one cell (the source draws no horizontal rule between them across those
  columns). Reading order starts in the **right** column — `Dual Pole, 125Vdc,` at
  x=297.2 — while the middle column's `No` sits at x=191.0. `base_x` got pinned to
  297.2, every indent `x_i - base_x` went negative and clamped to 0, and all four
  lines collapsed into one stack: `Không` wedged between the two spec lines of the
  right column, and `≥6000 chu kỳ` losing its full-width span.

  Measured across the jobs on hand: **7 regions whose first line is not the
  leftmost, exactly 1 of them left-aligned** — the patch touches the broken region
  and nothing else; the other six are `center`/`right`, which anchor to the box and
  never consult `base_x`.

  **No gate saw this.** P0/P1/P2 are identical before and after. It surfaced in the
  source-vs-translation compare that the reviewer reads before approving — which is
  the argument for producing that compare on every job.

## [1.9.23] - 2026-08-07

### Fixed

- **Gate 6 renders from clean document handles.** `page.get_image_info(hashes=True)`,
  which Gate 5 calls, makes MuPDF decode every image up front and cache it; a
  later render reuses that cached decode instead of decoding at the render
  resolution, so pixels differ on fine detail. Gate 5 only inspects `draft`, so
  Gate 6 was comparing two renders taken under different conditions — and every
  flag that came out of it was a false positive. The experiment: same file, render
  md5 `ec417e0f`, then `get_image_info(hashes=True)`, then `db59d990`; calling
  `get_pixmap(clip=…)` first changes nothing. On V5 Series: **26 → 1
  `G6_DIFF_OUTSIDE_MASK`**, i.e. 25 of 26 were noise, all on pages carrying images
  (5, 7, 8, 9, 14).

- The one surviving flag was real, and is fixed too: the band 1.9.18 declares to
  Gate 6 covered only the **new** leader box, but when the translated title runs
  longer the new leader starts further right than the old one, and the strip
  between them loses its dots — still a pixel change. The declaration is now the
  **union** of the old and new boxes. V5 `g6_visual` goes from red to green.

## [1.9.22] - 2026-08-07

### Fixed

- **A contents leader typed as DOTS is regenerated so the page numbers line up.**
  HV48100 does not draw line art the way V5 does; it types 85 `.` characters
  straight into the text, so `leader_run` (1.9.18) finds no strokes and
  `leader_split` (1.9.13), which wants a gap of 4+ spaces, does not match either.
  The symptom is the opposite of V5's: nothing overprints the leader, but the
  model reproduces roughly the original dot count (85 → 86) while the Vietnamese
  title has a different length, so the page-number column comes out ragged.

  The dot run is shrunk to a minimum *before* fitting — the font size has to be
  decided by the title and the page number, not by the source's leftover dots —
  and then regenerated so the line ends at the **source line's right edge**.
  Signature: single-line region, last token a 1-3 digit page number, the token
  before it ending in 4+ dots; dots glued to the title are split off. Measured
  across the jobs on hand: **54 rows, all on the HV48100 contents pages, no false
  positives**. Right-edge spread: **23.3 → 4.3pt** (p3) and **17.1 → 2.9pt** (p4),
  against 1.8 and 1.5pt in the source. What is left is one dot width — the effect
  of rounding down, not drift.

  Text only: nothing erased, no vector drawn, so Gate 5 needs no declaration.
  Gate 3 does need one: it compares the target string verbatim, and the painted
  dot count deliberately differs from `target_text`. The fit result declares the
  regenerated count, and the gate collapses dot runs on both sides for exactly
  those regions — nothing else is relaxed. Without that declaration the gate
  fires 47 P0s, which is how the omission was caught.

## [1.9.21] - 2026-08-07

### Fixed

- **A superscript is folded into the line it belongs to.** Its baseline sits
  above the body line, so the PDF reports it as a **line of its own**: the cell
  `Recommended Charge/ Discharge Current [1]` comes out as three "lines" with
  `[1]` in the middle, `source_text` becomes three segments, the model dutifully
  translates three segments, and the painter puts `[1]` on a line of its own
  floating between two lines of text. The host is the line that ends immediately
  to its left **and** whose baseline sits *below* it by less than a line — a
  superscript is raised, and without that second condition the `[3]` belonging to
  `Cycle Life` gets stuck onto `DC Breaker` in the row above. No host found means
  no fold. Across the jobs on hand: exactly 4 regions, all on V5 p6.

## [1.9.20] - 2026-08-07

### Fixed

- **Each translated paragraph is anchored to its source paragraph's baseline.**
  The `•` `◇` `∘` marks are not part of the region — they are separate glyphs
  pinned to the source baselines and never redacted. The fitter lays lines out
  continuously from `base_y`, so paragraph *i* only lands on its own mark when
  every paragraph before it occupies exactly as many lines as the source did, and
  Vietnamese rarely breaks the same way English does. Real case, V5 p12 §5.2: 6
  source lines and 3 `◇` items against 3 translated paragraphs — the count
  already matched — but paragraph 1 took 3 lines instead of 4, so the last `◇`
  ended up beside nothing. Rewriting the translation cannot fix this: it would
  mean forcing each paragraph to a line count, which is not translating.

  The rule: a paragraph's first line drops to its source baseline but **never
  moves above the previous line** — `max(anchor, previous + leading)`. Thanks to
  the `max`, a paragraph that runs longer than its source simply flows on instead
  of colliding. The fitter measures its vertical budget with the very same
  baseline formula the painter uses.

  `segment_indents` and `segment_anchors` now share `segment_source_lines`:
  indent and anchor have to describe the same structure, or each reads the region
  its own way.

## [1.9.19] - 2026-08-07

### Fixed

- **Column consensus no longer drags a cell to `left` when its ink starts away
  from the container's left edge.** Left-aligned text is drawn from `base_x` —
  the source ink edge — so the wrap budget is only `container.x1 - base_x`; a
  cell whose ink starts well inside loses most of it, and if that cell was
  genuinely centred, forcing it left is both wrong and unfittable. Real case,
  HV48100 p25: an `OFF`/`ON` column 20.4pt wide, where five `OFF` cells nearly
  fill the cell and so were misread as `left`, winning the vote 5-to-1; the `ON`
  cell (genuinely centred, gaps 4.0 / 3.0) got pulled along and `Sáng` was left
  16.4pt to wrap in — `FIT_IMPOSSIBLE`. Only the move *to* `left` is guarded;
  `center` and `right` anchor to the box and cost no budget.

## [1.9.18] - 2026-08-07

### Added

- **Contents-page dot leaders are now redrawn.** A leader is line art running
  from the right edge of the **English** title to the page number: a longer
  Vietnamese title runs over it, a shorter one leaves a gap. `leader_split`
  (1.9.13) only ever fixed the columns. The old strokes are now erased (the same
  line-art redaction pass `fill_rules` uses) and redrawn with the **right edge
  kept**, moving only the start to follow the translated title — the too-long and
  too-short cases are symmetric and neither requires guessing a coordinate.

  Narrow signature: strokes under 1.2pt tall, sharing one y, at least one of them
  **dashed** (table rules and underlines are solid), starting within 12pt of the
  text, and with **text immediately after the run** — the page number. Without
  that last condition a figure's callout line matches too (real case: the
  `Ground` label on V5 p9). Gate 5 and Gate 6 get both the old and the new box in
  `render_manifest.toc_leaders`, so they subtract exactly those two and nothing
  else is relaxed. Result on V5: **24 of 24 contents rows** correct.

  One trap, sprung once: `shape.finish` closes the path by default, drawing a
  return leg from the end point. The return leg is out of phase with the dashes
  and fills the gaps, so the leader comes out solid — but only on rows whose
  length divides that way, which makes it very easy to miss.

## [1.9.17] - 2026-08-07

### Fixed

- **A single-line table cell now takes its alignment from the column.** Such a
  cell has no internal agreement to count, so it must guess from the left and
  right gaps — and an English line that nearly fills the cell leaves two similar
  gaps, which the tolerance rule reads as `center`, indistinguishable from a real
  left alignment. Real case, V5 p8: `Charge / Discharge over Current Protection`
  fills the cell (gaps 3.2 / 10.9 across 187.1) and came out `center` while the
  other 7 cells in its column were `left`; the shorter translation then sat
  visibly indented. 1.9.8 fixed the multi-line case by counting agreeing lines —
  here the evidence lives *outside* the cell.

  Multi-line cells are left alone, and the thresholds are deliberately high (>=4
  single-line cells, >=75% agreement) because a column mixing a centred header
  with left-aligned body text is entirely normal. Measured: V5 18 cells, HV48100
  23, Pi Station 1.

## [1.9.16] - 2026-08-07

### Fixed

- **`paint_origin_x` now returns the ink edge, not the raw span origin.** Its job
  is to keep the container around the point where the fitter starts drawing —
  correct until 1.9.6/1.9.9, when `ink_base_x` began raising `base_x` to the ink
  edge, so a space-padded origin is no longer where anything gets drawn. The old
  formula dragged the container left by the full width of the run of spaces. Real
  cases on V5: the `CANH` cell has 48 leading spaces, so its container fell back
  to 134.2 while the CAN column starts near 204 — `infer_alignment` read it as
  `right` and the translation hit the edge of the header band; and the value cell
  for `Unit Dimension` fell back to 67.7, **overlapping the label cell at
  `[29.0…121.2]`** and spilling text into it. Stage 2 and stage 6 now agree on
  what that point is. On V5: 133 space-padded regions, 61 alignment changes, and
  Gate 4 goes from red to green.

## [1.9.15] - 2026-08-07

### Added

- **`segment_indents` learned a third pattern**: the translation's paragraph
  count matching the source's count of **paragraph-opening lines**. A line opens
  a paragraph if it is the first one, or if the line *before* it still had room
  for its first word — a source line that wraps must run to the right edge, so
  stopping short of that is a deliberate break. Character width is measured on
  the line itself (ink width over non-space characters), so no font metrics are
  needed.

  Both 1.9.11 patterns count by **indent level** and therefore miss a region
  where one item starts flush at the body margin. Real case, V5 p11 storage
  block: 12 source lines, 7 translated paragraphs, only 6 deep-indented lines.

  Order of attempts is unchanged — the two older patterns measure indent
  directly and are the more reliable, so the new one runs last. An extra guard
  rejects an implausible indent (>25% of region width): a two-column region
  matches on count but yields 268pt on a 366pt box. Across the jobs on hand: 29
  regions with mixed indent, inferable **10 → 19**.

## [1.9.14] - 2026-08-07

### Fixed

- **An expanded container is now accepted when it saves a LINE, not only when it
  raises the FONT SIZE.** 1.9.10 added the "a one-line source forced to wrap is
  also a poor fit" branch to trigger container expansion, but the acceptance test
  at the end was still `got_s > keep_s` — and the two-line fallback already sits
  at full size, so the size can never go up. The two branches cancelled out and a
  correctly computed container was thrown away. Real case, V5 p17:
  `7.1 Unable to start` → `7.1 Không khởi động được` needs 157.0pt in a 132.0pt
  box with the whole band to its right empty.

- **A pre-existing bug in the paint loop**: it removed the region's own bbox from
  the obstacle list by **assigning over** `expand_ctx["obstacles"]` in place. Every
  already-processed region's obstacle therefore disappeared for good, so a region
  near the end of a page saw an almost empty page and could expand over its
  neighbours' text. The filter now produces a per-region copy.

## [1.9.13] - 2026-08-07

### Added

- **`leader_split`** splits a contents-page row that carries its title and page
  number in one region into two columns. Such a row is a single span with the
  title and the number separated by a run of spaces (the dot leader is separate
  line art). `tokenize` drops the spaces, the text collapses, and
  `infer_alignment` then reads the near-full-width line as `center`/`right` and
  pushes the whole thing over the leader. `column_split` never applied: it
  requires a `table_cell` and a repeating grid of at least three lines.

  Two shapes: (A) one line, a gap of 4+ spaces, and a 1-3 digit tail — the column
  boundary is measured from the number's width; (B) the PDF reports **two "lines"
  sharing one y**, which are already two columns with their own boxes. The
  signature is narrow: across 5 jobs it matches contents rows only, no false
  positives. Same translation contract as `column_split`: two `\n`-separated
  segments, left to right.

### Fixed

- **A pre-existing bug in `column_split`**: it joined target runs with
  `"\n".join`, inserting an extra column separator between every pair of runs. A
  multi-run target — a bold lead-in plus the rest, exactly what 1.9.7 started
  producing — was counted as having too many columns, so the function silently
  returned None. Runs are a styling unit, not a column unit; they now join with
  `""`.

  Result on one job: the contents page renders all 24 rows correctly with page
  numbers in a straight column, and **467 regions painted, none skipped**.

## [1.9.12] - 2026-08-07

### Fixed

- **The masking path now measures ink, and can clip vertically.**

  1. `protected` — the text a region must not erase — was built from span boxes
     that include whitespace. Real case: a table's label cell was **26 spaces,
     boxed 123pt wide**, and a row-number cell `'  6     '` inflated from 4.4pt to
     20pt. Those *empty* rectangles forced two neighbouring cells to clip their
     masks, so the English text stayed on the page and the translation was
     painted on top of it. Whitespace-only spans are now skipped, and the rest
     intersect their line's `ink_bbox`.
  2. `build_masks` intersects `ink_bbox` before padding, for the same reason: a
     cell boxed from 30.0 while its text starts at 49.6 reached into the
     neighbouring column and lost the whole region.
  3. The fallback can now clip **vertically** when a protected rect sits inside
     the mask's horizontal span. Real case: a footnote block touching the page
     number by **0.1pt** at its bottom edge — no horizontal branch applied, so
     the block was dropped, left in English, and a neighbour's mask had already
     eaten characters out of it (`temperature` → `tem   tur`).

  Same family as 1.8.0 (`ink_bbox` for lines) and 1.9.6/1.9.9 (`base_x`): every
  place that trusted a whitespace-padded box was wrong.

  Result on one job: `MASK_CLIPPED` **8 → 0**, `MASK_CONFLICT` **2 → 0**, and
  **457/457 regions painted, none skipped**.

## [1.9.11] - 2026-08-07

### Fixed

- **Per-segment indentation** (`segment_indents`). Sources mix indent levels
  inside a single region — bullet items indented, the prose between them not —
  while the fitter has one `base_x`, so every line started at the leftmost ink
  and the translation **ran over the very bullet glyphs the engine preserves**.

  The segment-to-indent mapping accepts only two well-defined shapes: (a) the
  number of translated segments equals the number of source lines, giving a 1:1
  map; (b) the source has exactly two indent levels and the number of indented
  items equals the number of segments, so every segment takes that one indent.
  Anything else returns zero and keeps the old behaviour — **it does not guess**.

  A third rule was tried and dropped: "segments equal same-indent runs" merges two
  adjacent single-line bullets into one run and produces a ragged result — one
  item indented, the next not — which reads worse than leaving it alone.

  Measured across 5 jobs: 50 regions mix indent levels, **30 are derivable**.
  Indents are never negative, and the rule only applies to unrotated,
  left-aligned regions.

  **Still open:** bullet glyphs are line art pinned to the source's y positions,
  and Vietnamese wraps to a different line count, so vertical misalignment
  remains. That needs manual DTP.

## [1.9.10] - 2026-08-07

### Fixed

- **A single-line source now prefers staying on one line**, shrinking within
  `minimum_ratio` rather than wrapping. A cell's vertical budget usually fits two
  lines, so the fitter stopped at full size with a two-line layout. Real case: a
  heading needing 66.28pt inside a 66.0pt box — **0.28pt short** — was broken in
  two when a 0.5% shrink would have fit. If one line is impossible even at the
  floor, the old behaviour returns; nothing is forced.

  Also: a single-line source that still has to wrap now counts as `poor_fit`, so
  `expand_heading` gets a chance. Previously the two-line fallback carried
  `ratio = 1.0`, so expansion never triggered.

  Measured over 863 single-line-source regions across 5 jobs: **16 → 5 still
  wrap**; 47 keep one line by shrinking. Cost: `FONT_RATIO_HARD` 3 → 5 and
  `FONT_RATIO_REVIEW` 18 → 19 in one job — reviewer flags, not defects.

- Corrected the `ink_base_x` docstring, which still described the 1.9.6 guard
  after 1.9.9 relaxed it.

## [1.9.9] - 2026-08-07

### Fixed

- **The `base_x` guard from 1.9.6 now takes the leftmost inked start across lines**
  instead of demanding that every line share one. It still never paints left of
  any line's source ink, so prose with a first-line indent stays safe — the
  leftmost start is the body margin. The old guard missed **merged cells centred
  by space runs of differing length per line**: a spec-table dimension cell whose
  ink began 64.5pt right of the span origin was skipped, and the translation
  spilled into the label column. Measured across 5 jobs, the relaxation touches
  **2 additional regions**.

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
