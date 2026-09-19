---
name: korean-listing-crawler
description: Build or extend a daily-refreshed crawler that pulls the same kind of listing (pop-up stores, events, venues, deals) from several competing Korean sites into one deduplicated SQLite store. Use when the user wants to scrape/crawl/collect Korean listing data from multiple sources and merge it ("여러 사이트에서 긁어와줘", "팝업 정보 수집 파이프라인 만들어줘", "중복 제거해서 하나로 합쳐줘", "매일 자동으로 돌게 해줘"), when a target site's API needs a token you don't have, when the same real-world entity needs to be matched across sources with different titles/coordinates, or when scheduling unattended macOS automation for a scraper. Built from a production pop-up-store tracker (popup-radar) refreshing ~350 active listings daily from two competing sources.
---

# Korean Listing Crawler

A pipeline that turns "several sites list overlapping things, in Korean, with inconsistent titles and coordinates" into one clean, deduplicated, incrementally-refreshed SQLite table. Every rule below exists because a real run produced a real wrong answer without it — read the reference file for the stage you're on rather than front-loading all of them.

**Reference implementation**: `github.com/JunJuneee/popup-radar` (private), under `crawler/` — the pop-up-store tracker this skill was distilled from. That subfolder is a version-controlled snapshot for backup/reading; the actual daily-run instance lives locally outside the repo's checkout path (see the `~/Desktop` warning in §6) and isn't kept in automatic sync with it — a change made to the running scripts has to be copied over manually if it should also update the tracked copy.

## The pipeline

1. **Per-source fetch strategy** (below) → 2. **Incremental fetch, not full re-fetch** (below) → 3. **Cross-source dedup** (`references/dedup-matching.md`) → 4. **Field-merge trust ranking** (below) → 5. **Normalization** (`references/normalization.md`) → 6. **Daily unattended run** (below)

## 1. Per-source fetch strategy — assume every site needs a different trick

Don't assume "no public API" means "can't fetch it." Check, in order:

- **Public REST API, no auth** — the easy case. Still send a real `Origin`/`Referer` pair matching the site (`https://api.X.co.kr/...` frequently 403s without it) and a `User-Agent` that identifies your bot honestly with a contact address, e.g. `"Mozilla/5.0 (...) (+my-project; contact: me@example.com)"` — courteous and makes you easy to allowlist if a site operator ever asks.
- **API requires a token you don't have** — before giving up, check if the site is a Next.js (or similar) SSR app. If so, the *same JSON the API would have returned* is very often embedded directly in the HTML response, because that's how server components hydrate. For Next.js App Router specifically, look for `self.__next_f.push([1, "..."])` script chunks — reassemble them into one string and you have the full RSC payload as a giant string containing dehydrated react-query state:
  ```python
  def flight_payload(html):
      parts = re.findall(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', html, re.S)
      return "".join(json.loads(p) for p in parts)  # each part is itself a JSON-encoded string
  ```
  Then find your data by its query key (e.g. `"popup-info",12345]`) and extract the balanced JSON object that follows it (`json_at`, a simple bracket-depth scanner — `json.loads` on a substring found via string search will fail if you slice at the wrong point, so match brackets, don't guess a fixed length). This got a fully token-gated API's entire response via nothing but `curl`.
- **A sitemap that lags reality by hours** — sitemaps are frequently generated on a delay. If freshness matters, *also* scrape the newest-first list page's own SSR payload for bare id patterns (e.g. `\{"id":(\d+),"type"` ) and merge any ids missing from the sitemap in front of the sitemap's own ordering.
- **A redirect code Python won't follow** — `urllib.request`'s default handler follows 301/302/303 but not 308. If a source uses 308 (seen on a "shop/goods" detail redirect), install a tiny custom `HTTPRedirectHandler` that re-dispatches 308 as a 301.
- **Rate limits** — retry with backoff (`time.sleep(1.5 * (attempt + 1))` between failures) and a small courtesy sleep after every success, not just after failures.

## 2. Incremental fetch — never re-fetch what can't have changed

A "sync everything" pass that re-fetches every historical id every day doesn't scale and gets you rate-limited. Skip by known-immutable state:

- An item whose stored status is already **ended** never needs re-fetching (closed listings don't reopen under the same id) — unless the user explicitly asks for a `--full` backfill.
- A detail record you already have by its **(source, source_id)** natural key — reviews, gallery items, sub-records — never needs re-fetching once present; only fetch ids not yet in your table.
- A binary asset (image) already saved locally never needs re-downloading; check the local path first.

Log every sync run's `{source, started_at, ended_at, fetched, inserted, updated, merged, note}` to its own table. This is what lets you answer "did today's run actually work" without re-deriving it, and it's what a coverage doctor script (§6) diffs against.

## 3. Cross-source dedup

The hardest and most failure-prone stage — it has its own file. Read `references/dedup-matching.md` before writing any matching logic; the thresholds in it are tuned from real false-positive/false-negative cases, not guesses.

## 4. Field-merge trust ranking

When two sources both describe the same real-world item, one source's data usually wins per field — but "most recent write wins" is wrong (a stale, low-quality source can overwrite a good field with a blank one). Rank sources once, use the same ranking everywhere a merge decision happens:

```python
SOURCE_RANK = {"submit": 40, "instagram": 30, "official_site": 30, "site_a_detail_api": 25,
               "site_b": 20, "site_a_list_api": 10}
```

Apply this **same table** in three unrelated-looking places, because they're really the same problem: (a) which source's *value* wins when merging a field on a matched duplicate — only overwrite an existing non-empty field if the incoming source's rank is `>=` the current best rank ever seen for that item; (b) which source's *parsed hours/schedule* wins when two sources disagree (see `references/normalization.md`); (c) which source's *coordinates* wins when geo-candidates disagree by more than the agreement threshold (see `references/normalization.md`). Building three separate ranking schemes for these would drift out of sync; one table, three call sites.

Keep every source's *raw* payload in a per-source table keyed by `(source, source_id)` even after merging into the canonical row — you will need to re-derive a field later when you notice the merge logic had a bug, and you cannot re-derive from a value you already overwrote.

## 5. Normalization

Two things every multi-source Korean listing dataset needs and gets wrong on the first pass: opening-hours parsing (multiple formats, sources disagree ~8% of the time in practice) and location standardization (sources' geocoding can be kilometers apart even when they agree on the venue). Full method, exact status/confidence vocabularies, and the district-centroid sanity check are in `references/normalization.md`.

## 6. Daily unattended run

- **Use `launchd`, not `cron`, on macOS.** `launchd` runs a missed job as soon as the machine wakes up; `cron` simply skips the missed time. For a laptop that isn't always on, this is the difference between "ran every day" and "silently didn't run for a week."
- **Never install the project under `~/Desktop`.** macOS TCC (privacy permissions) blocks `launchd`'s access to the Desktop folder for unattended jobs — the job fails with `exit 126` and no obvious error in a quick glance at the log. Put the project under a plain folder in `$HOME` instead (e.g. `~/project-name`, not `~/Desktop/project-name`).
- **A lock file, not just "don't overlap in cron."** Write your own pid to a lock file at start; on start, if a lock file exists, check whether that pid is still alive (`kill -0 $pid`) — if dead, clean up the stale lock and proceed; if alive, exit immediately without doing anything. Only ever delete a lock file your own process created (via a shell `trap ... EXIT`, or the run that owns it) — never delete a lock just because it looks old.
- **Verify the output before publishing it.** After generating the day's export artifact (e.g. `active.json`), check it isn't empty/zero-count and treat an empty result as a failed run, not a valid "nothing today" — an empty export usually means the fetch step silently failed upstream, and shipping it overwrites yesterday's good data with nothing. On any step failure, stop and leave the previous successful artifact in place; don't let a partial run overwrite a good one.
- **Run a periodic live coverage check separate from the daily sync.** Independently of what your sync script *thinks* it fetched, occasionally re-count the source's own sitemap/API totals live and diff against your DB's per-source counts as a percentage. This catches silent partial failures (a source changed its response shape, your parser now returns 0 fields but doesn't error) that a sync log alone won't reveal, because the sync log only reports what your own code believed happened.
- Send a notification (Discord webhook, or similar) on both success and failure with the last dozen log lines on failure — don't rely on remembering to check a log file.
