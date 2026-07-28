# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

kcard renders structured JSON into HTML/CSS, screenshots it with Playwright, and produces knowledge-card PNGs for social sharing. Text is never AI-generated pixel-by-pixel — it's rendered from data through HTML templates, so text is always correct and rendering is deterministic (same data + same params → byte-identical PNG, every time). AI's only two jobs are: filling in card content JSON, and generating text-free hero images.

## Commands

Python env is **shared with the sibling `videoPic` project**, not a local `.venv` in this repo:

```bash
/Volumes/Samsung/videoPic/.venv/bin/python scripts/render.py <card_dir>
```

Requires Python 3.13 + playwright(chromium) + Pillow + numpy + scipy. There is no lint/build/test suite — validation is done by rendering and by `style-check.py` / `regress.py` (see below). When verifying a change, the standard move is: re-render the affected cards and diff `output.png` bytes against git (`git status --short | grep output.png` — empty means pixel-identical; this substring match also catches paginated cards' `output-01.png` etc., see the pagination note below).

```bash
# Render one card
python scripts/render.py production/<group>/cards/<topic>

# Batch-render a whole group (shares one Chromium instance, faster than looping render.py)
python scripts/batch.py production/<group>
python scripts/batch.py production/<group> --only tomato,banana

# Style self-proof preview — renders a style's own sample.json, never touches production/
python scripts/render.py --style <style> --preset <preset> [--layout <layout>]

# Gate check before a production group goes live, and after any profile.json edit
python scripts/style-check.py production/<group>

# After editing a style (space.json/engine.html/layouts/presets), confirm no
# group using it broke. Default is dry-run (reports only); --write accepts the diff.
python scripts/regress.py <style-name>
python scripts/regress.py --all
python scripts/regress.py <style-name> --write

# Regenerate design/GALLERY.md from the styles' own files — never hand-edit GALLERY.md
python scripts/gallery.py

# Cut a neutral-background hero image to alpha
python scripts/cutout.py production/<group>/cards/<topic>/hero.png
```

`output.png` files are committed to git, not gitignored — rendering depends on macOS system fonts (Songti SC, Didot, Baskerville, PingFang SC), so a different rendering machine produces different pixels. This is an accepted, intentional constraint (project is designed for single-machine macOS rendering, not cross-platform reproducibility) — do not "fix" it by trying to bundle fonts unless explicitly asked.

## Architecture: two departments, one rendering pipeline

The project is organized as **design** (owns visual systems) and **production** (owns content), modeled as strictly one-directional: `production/ → design/`. `design/` must never contain a reference to anything in `production/`. The one sanctioned exception is `scripts/regress.py`, which reads `production/*/profile.json` to find which groups use a style — that's a neutral tool doing a reverse lookup, not `design/` depending on `production/`. Never let a style's engine/layout/space.json branch on a group name.

A card's rendering assembles five layers at runtime — nothing is ever copied:

```
production/<group>/profile.json      picks style + preset, optionally overrides layout/params
  → design/styles/<style>/presets/<preset>.json   baseline param set
  → design/styles/<style>/layouts/<layout>.css    header-region positioning only
  → design/styles/<style>/engine.html             parametric rendering engine + renderCard(data, params, pageNum?)
  → production/<group>/cards/<topic>/card.json    pure content (data only, no style reference)
  → production/<group>/cards/<topic>/output.png   (or output-01.png.. if the layout paginates, see below)
```

**Production groups hold zero HTML/CSS.** Switching a card's visual style is a two-line `profile.json` edit — the content file (`card.json`) never changes. This is a deliberate, load-bearing property of the architecture, not an accident: check `production/*/` for HTML/CSS if you're ever unsure — there should be none.

### Constitution vs. parameter space

Each style directory (`design/styles/<name>/`) splits what's fixed from what's tunable:

- **`STYLE.md`** — the constitution. Constituent elements (what must be present) and hard constraints (`H1`, `H2`, ... — machine-checkable rules like "background lightness ≤ 0.12" or "accent must be the complementary hue of the background") plus soft "looks expensive" judgment calls a human reviews at group-launch time, not per-card.
- **`space.json`** — the parameter space. Each tunable has a `default` (exactly matching the pre-engine hand-written implementation, so it's the pixel baseline), a `range`/`values`/`length`, a `scope` (`production` = groups may freely set it; `design` = internal to the engine, e.g. `accentExtraction`'s hue-detection thresholds — a group wanting a fixed color sets `palette.accent` instead of touching this), and an `invariants` array of cross-parameter rules.
- Production groups may **never** exceed what `space.json` declares. `render.py`'s `resolve_params()` hard-errors on any param key a group tries to set that isn't declared — silently ignoring an unknown key is treated as a bug, not a fallback.
- `style-check.py` re-verifies both the per-param bounds and the `invariants` using a small safe expression evaluator (whitelisted grammar: numbers, dotted param names, arithmetic, comparisons, `=>` implication, `min`/`max`/`isAscending`, plus a `contrastHSL(h1,s1,l1,h2,s2,l2)` helper any style can use for real WCAG contrast checks) — not a Python `eval()`.

If a group needs a capability the parameter space doesn't expose, that's a proposal back to the style's `space.json`/`STYLE.md`, not a workaround in the group's files. If what's needed would actually change a constitution's constituent elements or hard constraints, that's a **new style**, not a modification of an existing one.

### Layout vs. engine split (why colors/positions live where they do)

Within a style, `engine.html` owns everything **except** the five header-region elements' absolute positioning (hero slot, title, subtitle/meta, ghost/background type, and any style-specific extra like `almanac`'s annotation labels) — that positioning lives entirely in `layouts/<name>.css`, injected at render time via `page.add_style_tag()`. This lets a style ship 3+ layout skeletons that share 100% of the engine's typography/color/material logic while completely reflowing the composition.

**`aurora-glass` extends this line (2026-07-28); the other two styles have not been migrated yet.** Header-only layouts turned out to lock every style into the same look: the three engines emitted byte-identical section DOM, and layout CSS had no hook to select an individual section, so swapping layouts could only change the header composition. In `aurora-glass` the rule is now **layouts own how blocks are arranged; the engine owns what a block looks like** — layout CSS may restyle the section grid (templates, spans, order, per-block differentiation), while typography/color/material/block-body internals stay in the engine. The engine emits three inert hooks for this: `data-n` on `.grid` (rendered block count), `data-i` and `data-style` on each `.section`. Prefer `data-i` over `:nth-child` — the former tracks content order, the latter DOM position, and they diverge as soon as a layout uses `order`. When extending this to the other two styles, keep the hooks inert-by-default so adding them is a zero-pixel-diff change.

A subtlety that has caused real bugs (see `almanac`'s history): when a layout merges two logically-separate label groups onto one side of the composition, the engine can't know that merge happened at design time, so per-side index-based positioning silently collides. The general fix pattern is: the engine computes *multiple* candidate positioning values (e.g. both `--t-side` for symmetric layouts and `--t-all` for merged layouts) and the layout CSS picks which one to consume — the engine never assumes how a layout will use its elements.

Another recurring gotcha: derived colors (anything computed via `color-mix()`) must be declared on `.stage`/`.sheet`, never `:root` — `var()` resolves at declaration time, so a `:root` declaration would permanently bake in the default accent and silently stop responding to runtime color changes.

### Rendering pixel-identity as the actual regression tool

Because rendering is deterministic, "did this change break anything" has a cheap, exact answer: re-render and diff bytes. This is used at every refactor step (confirming `render.py` internals could be restructured with zero behavior change) and is what `regress.py` automates for style changes across every group that uses that style. When editing `engine.html`/`layouts/*.css`/`space.json`, always re-render the affected groups' existing cards and confirm `git status` shows no `output.png` diff — unless the change is *meant* to alter pixels, in which case that's the thing to call out explicitly, not something to discover by accident.

### `card.json` content contract

`card.json` holds only `{"data": {...}}` — no style/template reference. The `data` shape (`name`, `nameEn`, `category`, `emoji`, `hero`, `themeColor`, `blocks[]` with `style: list|tags|metric|text`) is shared across styles; a style may add its own optional fields (e.g. `almanac`'s `specimenLabels`) that degrade cleanly to nothing when omitted. This is what lets an existing group's cards render under a different style with zero content edits — see any style's own `schema.md` for the authoritative field list.

In `aurora-glass`, `blocks[]` is a **content pool rather than a render list**: authors fill up to 6 blocks and each layout renders the first N via `layout.blockLimit` (4–6, tuned per layout). Order is priority. This exists because the alternative — trimming `card.json` to control card height — destroys content permanently and can't be undone by switching layouts; it was done once (see the font-size recalibration commits) and should not be repeated. Card height per block varies ~30% across layouts (391–507px measured), so block capacity is a per-layout property, not a per-style constant — measure before setting a new layout's `blockLimit`.

**Pagination (2026-07-28), also `aurora-glass`-only so far.** The target platforms are social feeds (小红书/视频号) that render as fixed-ratio, swipeable image carousels — a variable-height long image gets cropped to the feed's cover ratio and users have to tap through to see the rest, which fights the medium. A layout opts in by declaring `canvas.height` in its preset (currently only `1080×1440`, i.e. 3:4, has been validated); `render.py` then screenshots the fixed viewport instead of `full_page` and loops `renderCard(data, params, pageNum)` to produce `output-01.png`, `output-02.png`, ... — the content pool is split into a cover (`layout.coverBlocks`) plus continuation pages (`layout.blocksPerPage` each), section numbering stays globally continuous across pages. Only two of the six layouts paginate today (`e-mosaic`/`amber`, `c-bleed-poster`/`onyx`, chosen for having the smallest fixed overhead); the other four remain long-image with `canvas.height: null`. Overflow in paginated mode is a **hard, render-time gate** (`RenderOverflow`, raised from `scripts/render.py`) — unlike the long-image aspect-ratio guidance, which is advisory only because `style-check.py` doesn't run Playwright.

`themeColor` resolution order: `profile.params["palette.accent"]` (group-wide fixed color) > card's own `themeColor` > auto-extracted from `hero` image via the style's `accentExtraction` config (only triggers when a `hero` image exists — a card falling back to `emoji` never triggers auto-extraction, so its accent is whatever the style/profile default is).

## `design/GALLERY.md`

This is the single crossing point between the two departments — generated by `scripts/gallery.py`, never hand-edited. It lists available styles, their layouts/presets, and which production groups use each one (via a read-only scan of `production/*/profile.json`). Regenerate it after adding a style or a preset/layout, or after a new group starts using a style.

See `PLAN.md` for the full rationale behind this architecture (constitution/parameter-space split, independence invariants, the checklists for adding a new style vs. a new production group) and `README.md` for the quick-start.
