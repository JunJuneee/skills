---
name: business-content-youtube-producer
description: Plan or extend "가격표 뒤에 있는 것" — a no-host YouTube channel that decomposes an everyday price or business fee structure (a delivery fee, a coffee price, an airfare) into where the money actually goes, backed only by public-institution/primary-source numbers. Use when the user wants to pick a topic, write a title, or set the look/motion for THIS specific channel/track (not a different explainer channel) — e.g. "이 배달비 채널에 새 편 기획해줘", "바비노트 스타일로 제목 뽑아줘", "이 리포트로 가격표 채널 영상 만들어줘". For the shared how-to (research method, script timing math, storyboard, the render-engine pattern, verification) use `youtube-video-pipeline` — load that skill for the mechanics and load this one only for what's specific to this channel's identity: its reference channels, title formulas, niche, design tokens, and the concrete rendering bugs this channel actually hit.
---

# "가격표 뒤에 있는 것" — Price/Fee-Structure YouTube Track

This is a **channel bible**, not a how-to. Everything about *how* to research, script, storyboard, prototype, and verify an explainer episode already lives in `youtube-video-pipeline` — load that skill first for the mechanics and come back here only for what makes *this* channel this channel.

## Reference channels & the niche decision

Three real channels were surveyed by scrolling their `/videos` tabs and classifying recent uploads into topic buckets, then comparing median views per bucket (41 videos across all three):

- **김바비의 바비위키** (@김바비, 19.5만 구독, 218 videos) — "바비노트" sub-series.
- **오그랲** (@5graph-o6o, SBS 비디오머그 co-production) — higher-budget, dramatized B-roll.
- **머니스웨거** (@MoneySwagger, 38.7만 구독, 269 videos) — the sharpest internal contrast: its own AI-tool-demo videos sit at 1.5k–3k views while its price/business-structure videos (호텔의 경제학, 불꽃축제 예산) hit 6万–96万.

Median views by topic bucket (this channel's own research, not a general claim):

| Bucket | Median views |
|---|---|
| 기업의 몰락과 부활 | 23만 |
| **일상의 가격과 구조 (chosen)** | 16만 |
| 숨은 산업 | 6.2만 |
| 거시경제·정책·투자 | 4.8만 |
| AI 툴 리뷰·튜토리얼 | 1.5만 |

**"기업의 몰락과 부활" scores higher but was deliberately not chosen**: its top values are news-driven (a real regulatory event, a real scandal) and don't repeat on demand, and both reference channels already have 200+ videos of it — a new channel competing head-on there loses by default. "일상의 가격과 구조" is chosen instead because (a) it's the only bucket where infographics *are* the star rather than a supporting visual for a talking head, which converts this channel's lack of an on-camera host from a weakness into a fit, and (b) the underlying subject (every priced thing) never runs out, unlike a finite list of companies to autopsy.

**Never pick a macro/investment-commentary or AI-tool-demo topic for this track** — both bucket at the bottom regardless of channel, confirmed independently on all three references.

### Content angles (mix, not pure repetition)

1. **분해 (Decompose) — 60%.** "이 돈은 어디로 갔나." A single price, itemized by real institutional data.
2. **공짜의 이유 (Why free) — 20%.** Something priced at zero has a reason; find who's actually paying.
3. **가격의 역설 (Paradox) — 20%.** Same item, different price, and why that's not irrational.

### Title formulas (extracted from 바비노트's actual titles)

1. [통념]이라는 착각 — e.g. "줄서기는 공정하다는 착각"
2. [주체]가 [상태]할 수 없는 이유 — e.g. "나이키가 전성기로 돌아갈 수 없는 이유"
3. [비난받는 행동], 사실 [반박]입니다 — e.g. "같은 게임만 만드는 게임사들, 멍청한 게 아닙니다"
4. 이 [대상]이 진짜로 파는 건 [예상]이 아닙니다 — e.g. "이 헬스장이 진짜로 파는 건 운동이 아닙니다"
5. [행동]하던 [익명 주체]가 [사건] 당하면 생기는 일 — e.g. "꼼수로 장사하던 회사가 제재를 당하면 생기는 일"

Run a candidate topic through all five before committing.

### Topics already covered by the reference channels (avoid repeating)

헬스장 회원권, 공항 라운지, 항공 마일리지, 줄서기·프리미엄 패스, 아이스크림 냉동고, 휘발유·경유 가격, 복권, 호텔 객실, 불꽃축제, 도심 주차장, 자판기, 편의점 전략, F1, 아이맥스. Check a new candidate against this list first — it grows every time a reference channel's `/videos` tab is re-surveyed, so re-check periodically rather than trusting this snapshot forever.

## Design tokens (A variant — locked; do not re-propose)

**Typeface is locked and out of scope for future redesign discussion**: IBM Plex Sans KR (body/captions) + IBM Plex Mono (numbers, receipt body, labels) — confirmed explicitly by the user ("서체는 딱 좋아") after a side-by-side comparison. Never propose a different typeface for this channel; vary color/layout/motion instead if a redesign is asked for.

- Background `#14161A` (dark ink stage — a desk in a dim room, receipts are physical objects placed on it).
- Receipt paper `#F4F1EA`, ink-on-paper `#1A1A18` / `#6B665C`.
- **Accent encodes direction, not decoration**: `#E9A13B` (amber) = an amount that *increased*; `#79828D` (muted grey) = an amount that *decreased*. A falling number is not automatically "good news" in this channel's framing (e.g. a delivery fee falling while the total paid rises) — grey marks the smaller/receding number, amber marks the one the episode wants attention on, independent of whether that's ostensibly good or bad for the viewer.
- Both reference channels above use the same neon-green accent — this channel's amber was picked specifically to not sit next to it.
- A **B variant** (bright paper-white background, the whole frame *is* a document, red ink-stamp accent, hand-drawn pen-circle reveals instead of zoom) was prototyped side-by-side and **not chosen** — kept only as an archived alternative, not a default to revert to.

## Episode 1 (built) — "배달비 3,000원은 누가 나눠 갖나"

The reversal the episode is built around, sourced only from public institutions (배민 공식 요금 안내, 서울시 배달플랫폼 상생지수, 참여연대 실측 매입내역, 국토부 실태조사— never an estimate): the *listed* delivery fee fell **3,000원 → 1,990원**, but the same order's *total paid* rose **15,000원 → 17,990원** in the same period — the fee didn't disappear, it moved into the base price and a subscription. Script: ~2,900자 → real ElevenLabs audio ran **27% longer** than the character-count estimate once every number was spelled out phonetically for the TTS (see `youtube-video-pipeline` §8 for why real audio always runs long) — use 27% as a sanity-check margin for this channel's own future estimates, not a universal constant.

**How to apply for the next episode**: pick a new everyday price, run it through the three angles and five title formulas above, and reuse this file's color tokens rather than re-deriving them.

See `references/svg-first-lessons.md` for the exact rendering bugs this channel hit and fixed (all in the "anything with a direction" category `youtube-video-pipeline` warns about in the abstract — these are the concrete before/after). See `references/verification-tooling.md` for the automated check that was actually built here and the real bug it caught after the fact.

Relies on: `youtube-video-pipeline` (pipeline, script timing, storyboard cut types, the `render(t)` engine pattern, SVG-first rule, verification method).
