# Cross-source dedup matching

The goal: given a new record from source B, decide whether it's the same real-world item as an existing record from source A, or a genuinely different item. Get this wrong in either direction and the dataset is untrustworthy — false merges silently lose one source's data, false splits show the same popup twice.

Run the tiers **in order**, return on the first hit. Each tier trades off precision against recall differently, so a looser tier only runs once a tighter one has already failed to find anything.

## Shared building blocks

**Normalized title** — lowercase, whitespace stripped, then strip generic category words the source itself always appends (`"팝업스토어"`, `"팝업"`, `"popup store"`, `"popup"`, `"store"` and their no-space/hyphen variants), then strip everything that isn't alphanumeric or Hangul:

```python
_STOP = ["팝업스토어", "팝업", "popupstore", "pop-upstore", "popup", "스토어", "store"]
def norm_title(t):
    t = re.sub(r"\s+", "", (t or "").lower().strip())
    for w in _STOP:
        t = t.replace(w, "")
    return re.sub(r"[^\w가-힣@]", "", t)
```
Adapt `_STOP` to your own domain's generic suffix words.

**Branch token** — the same brand often runs simultaneous pop-ups at different locations, distinguished only by a trailing `@장소` or `in 장소` in the title. Extract it and treat two titles with *different* branch tokens as automatically different items, regardless of how similar everything else looks — and conversely, when both sides *have* the same branch token, that's strong enough evidence to ignore a coordinate mismatch (see tier 1):

```python
_BRANCH_RE = re.compile(r"(?:@\s*|\bin\s+)([가-힣A-Za-z]{2,10})")
def branch_of(title):
    m = _BRANCH_RE.search(title or "")
    return m.group(1) if m else None
```

**Date-range overlap** — treat a missing open/close date as an open-ended bound (`"0000"`/`"9999"`) rather than `None`, so string comparison works directly:
```python
def _overlap(a_open, a_close, b_open, b_close):
    a1, a2 = a_open or "0000", a_close or "9999"
    b1, b2 = b_open or "0000", b_close or "9999"
    return a1 <= b2 and b1 <= a2
```

**Title similarity across scripts** — a source might romanize an entity's name while another keeps it in Hangul (`"하우스 오브 토이스토리"` vs `"House of Toy Story"`). Plain `difflib.SequenceMatcher` on the raw strings scores this near 0.0. Also romanize both sides and score that, then take the max of the two:
```python
def title_ratio(a, b):
    plain = SequenceMatcher(None, a, b).ratio()
    ra = "".join(c for c in romanize(a).lower() if c.isalnum())
    rb = "".join(c for c in romanize(b).lower() if c.isalnum())
    return max(plain, SequenceMatcher(None, ra, rb).ratio())
```
This raised the example pair above from 0.00 to 0.63. Use a real Korean revised-romanization library, not a hand-rolled transliteration table — edge cases (double consonants, batchim) are numerous enough that a partial table produces more bugs than it fixes.

**Haversine distance** in meters between two lat/lng pairs — standard formula, nothing project-specific.

## The three tiers

Tuned thresholds below are starting points validated against real false-positive/negative cases in one production dataset (~350 active, several thousand historical listings) — recalibrate against your own confirmed-duplicate and confirmed-distinct pairs before trusting them blind, but treat "make up different numbers because they feel more precise" as the wrong move; these came from actually inspecting mismatches, not from theory.

**Tier 1 — same normalized title, overlapping dates.**
Query existing rows whose `norm_title` matches exactly. For each candidate whose date range overlaps the new record's:
- If both sides have a branch token and the tokens differ → not a match, keep looking (this is a different branch of the same brand, correctly a separate row).
- If both sides have the *same* branch token → match, **regardless of coordinate distance**. This sounds dangerous but is necessary: cross-source geocoding for the same physical venue has been observed to disagree by as much as **3.4 km** in this dataset (one source geocodes to a mall's registered corporate address, another to the actual storefront). Title + branch identity is stronger evidence than either source's coordinates.
- Otherwise (no branch info, or branch matches implicitly by both being absent) require coordinates within **600 m** if both sides have coordinates; if either side lacks coordinates, the title match alone is enough.
- First qualifying candidate wins — return immediately.

**Tier 2 — nearby coordinates, fuzzy title.**
Only runs if tier 1 found nothing and the new record has coordinates. Pull all existing rows within a coarse bounding box (±0.004° lat/lng, roughly ±400m, cheap pre-filter before the real distance check), then among those whose date range overlaps and whose branch tokens don't conflict:
- Require haversine distance ≤ **250 m**.
- Score `title_ratio` (romanization-aware, above) and keep the best-scoring candidate.
- Accept if the best score is ≥ **0.72**.

**Tier 3 — identical dates, very close, looser title match.**
Only runs if tier 2 found nothing, and only when the new record has *exact* open and close dates. Among the same bounding-box candidates: require the candidate's open/close dates to match **exactly** (not just overlap), distance ≤ **150 m**, and `title_ratio` ≥ **0.55**. The rationale for accepting a lower similarity threshold here is that an exact date match on top of near-identical coordinates is itself strong evidence — the title match only needs to rule out "two unrelated things that happen to share a launch day," not carry the whole decision.

If none of the three tiers match: it's a new row. If the same title+location matches but the date ranges *don't* overlap at all, that's very likely a re-opening / new run of a recurring pop-up — insert it as a new row rather than merging, since the two runs are genuinely separate events even if they'll dedup-match each other's *internal* records fine.

## What NOT to automate: retroactive re-merging

Once new rows exist, the *dedup tiers above only run at ingest time* against already-committed rows — they don't retroactively re-scan the whole table. A separate, **manually-triggered** merge pass is worth having for cases the ingest-time tiers miss (e.g. two sources both submitted a record before either had coordinates, so tier 1/2 couldn't have found the connection at insert time). Keep this pass manual, not part of the daily automated run, for two reasons: it deletes rows (merging inevitably means picking a survivor and removing the loser), and it needs one more gate the automatic tiers don't have — a body/description similarity check. Two listings can share a venue and an overlapping date range while genuinely being different offerings (a mall running two distinct curated pop-up slots back-to-back in the same space) — don't merge across a description that fails a basic similarity gate, no matter how well title/location/date line up.
