# Normalization: opening hours and location

Two fields that every multi-source listing dataset has, that every source formats differently, and that sources actively *disagree* about often enough that "just parse it" isn't sufficient — you need a conflict policy, not just a parser.

## Opening hours

### Parse per source, not from one blended field

Don't parse a single "hours" column that some upstream step already merged from multiple sources — parse each source's *raw* hours text independently first, keeping them labeled by source. You need the per-source parses to detect disagreement in the next step; a pre-blended field has already thrown that information away.

Target shape: a day-keyed structure, e.g. `{"mon": {"closed": false, "open": "10:30", "close": "20:00"}, ...}`, built from source text like:

```text
월-목 10:30 ~ 20:00 | 금-일 10:30 ~ 20:30
```

Handle day-ranges (`월-목` → mon,tue,wed,thu), single days, and a `휴무`/`closed` marker per day-group.

### Status vocabulary

Tag every parse attempt with one of:

| status | meaning |
|---|---|
| `parsed` | clean parse, single source or all sources agree |
| `partial` | some days resolved, others weren't in the source text |
| `undecided` | source explicitly says hours aren't announced yet (e.g. `"추후 공지"`) — this is a real, valid state, not a parse failure |
| `conflict` | two or more sources parsed cleanly but disagree on at least one day's hours |
| `unparsed` | source text didn't match any known pattern |

Measured on one production dataset: sources disagree often enough to matter (~8% of items with hours from more than one source) — build the `conflict` path from day one rather than treating it as a rare edge case to patch in later.

### Conflict resolution

When more than one source has a clean parse and they disagree on any day:
1. Pick the winner using the **same source-trust ranking** used for field-merge elsewhere in the pipeline (see main SKILL.md §4) — don't invent a separate ranking for hours specifically.
2. Store the *losing* source's parsed hours in a side table (e.g. `popup_internal(kind='hours_alt')`), not just discard it — a human reviewing a specific listing later needs to see both versions to judge which is actually right; the trust ranking is a good default, not a certainty.
3. Set the listing's `hours_status` to `conflict` so downstream consumers (a chat/search layer, an export) know to hedge or surface the alternative rather than presenting the picked hours as unambiguous fact.

### Cross-validate independently of the conflict path

Separately from the live conflict-resolution above, periodically run an *offline* validation pass: for every listing that has clean parses from two specific sources, diff them directly and report the agreement rate and a sample of disagreements. This is a data-quality health check (catches a parser regression — e.g. a site changed its hours text format and your parser now silently produces confidently-wrong output for every listing from that source) that the per-listing `conflict` status alone won't surface as an aggregate signal.

## Location standardization

### Keep every source's coordinate as its own candidate row

Never overwrite a listing's lat/lng in place per source — insert into a side table keyed by `(listing_id, source)` so every source's original coordinate survives, then compute the canonical `lat`/`lng` from the full candidate set. You cannot re-derive a source's original coordinate later if you've already overwritten it, and you will need to when a bad merge gets reported.

### Confidence tiers, derived from candidate agreement

For each listing, gather all its geo-candidates, rank by the same source-trust table as everywhere else, and compute the maximum pairwise distance between any two candidates:

- **Single candidate** → confidence `medium` (nothing to cross-check against).
- **Multiple candidates, all within an agreement threshold of each other** (200 m worked in practice — recalibrate for your domain's typical venue footprint) → confidence `high`, pick the highest-trust-ranked candidate.
- **Multiple candidates that disagree beyond the threshold** → confidence `low`, and **don't** blindly pick the top-trust-ranked one — a high-trust source can still have a stale or wrong coordinate for one specific listing. Instead, pick whichever candidate is closest to a coarse sanity anchor (see below).

### A coarse sanity anchor catches the outlier, not just the disagreement

Precompute a centroid (and a rough max-radius) per administrative district (city ward / borough) from all *known-good* coordinates in that district. When candidates disagree, prefer the candidate nearest that district's centroid over the nominally highest-trust source — trust rank tells you which source to *believe when they agree*, not which one is *geographically sane when they don't*. Additionally, flag (and downgrade to `low`) any final picked coordinate that's farther from its district centroid than that district's own observed max radius — this catches a single-source geocoding error that had no other candidate to disagree with in the first place (so the disagreement check above wouldn't have caught it).

### Nearest-transit enrichment is a separate, later pass

Once coordinates are standardized, computing "nearest station + walk time" (useful for a foreign-visitor-facing field, since transit orientation is a first-class question a domestic-source listing never bothers to answer) is a simple nearest-neighbor lookup against a static station-coordinate table — but only run it *after* standardization, against the final picked coordinate, never against a raw per-source candidate that might still get overruled.
