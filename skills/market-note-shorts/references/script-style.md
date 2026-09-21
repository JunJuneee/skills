# Korean TTS script style

## Maintain two scripts

Keep conventional notation in the display script and pronunciation notation in the TTS script. Never put pronunciation spellings on screen.

| Display | TTS |
|---|---|
| 신고가 | 신고까 |
| 유가 | 유까 |
| S&P 500 | 에쓰앤피 오백 |
| NASDAQ | 나스닥 |
| DOW | 다우 |
| Russell 2000 | 러셀 이천 |
| 0.2% | 영쩜 이 프로 |
| 0.3% | 영쩜 삼 프로 |
| 0.5% | 영쩜 오 프로 |
| 0.6% | 영쩜 육 프로 |
| 1.7% | 일쩜 칠 프로 |
| 5.1% | 오쩜 일 프로 |
| 12.6% | 십이쩜 육 프로 |
| 2.43% | 이쩜 사삼 프로 |
| 0.38% | 영쩜 삼팔 프로 |
| 3.26% | 삼쩜 이육 프로 |
| 8.24% | 팔쩜 이사 프로 |
| AI | 에이아이 |

When saying `유가`, use `유까` so the final consonant is pronounced naturally by TTS. This
table still governs the rare cases below where narration does carry a number.

## Punctuation

- Insert exactly one space after `쩜`: `영쩜 이`, not `영쩜이`.
- When the decimal part has two or more digits, concatenate all decimal digits with no spaces: `이쩜 사삼`, not `이쩜 사 삼`.
- Write the unit as `프로`, not `percent`, `퍼센트`, or `%`. An English word inside a Korean sentence makes the multilingual model code-switch and the timbre shifts.
- End sentences with a period.
- Avoid commas in ordinary prose.
- Use commas only for genuine lists.
- Put one sentence on each line.
- Do not narrate the disclaimer.

## Narrate the move qualitatively, not the figure

The card already shows every exact number — the close, the percentage, the point change, the
won amount. Narration's job is to say what happened and how big a deal it was, in words, not
to re-read numbers the viewer can already see. This applies to index moves, individual stock
quotes, FX, and fund flows alike. Never omit a figure from the display card merely because it
was omitted from narration.

Pick the word from the actual size of the move, don't default to the same word every time:

| Move | Word |
|---|---|
| ~0% | 보합 / 약보합 |
| small (roughly 0.1–1%) | 소폭 상승 / 소폭 하락 |
| moderate (roughly 1–3%) | 상승 / 하락 (플레인) |
| large (roughly 3%+) | 급등 / 급락 |

```text
코스피는 약보합, 코스닥은 소폭 올랐습니다.
```

```text
삼성전자와 SK하이닉스 모두 약세를 보였습니다.
```

```text
원화는 다시 소폭 약세로 돌아섰습니다.
```

```text
외국인은 대량 매도했고 개인과 기관은 매수에 나섰습니다.
```

not:

```text
코스피는 영쩜 영사 프로 내렸고 코스닥은 영쩜 칠육 프로 올랐습니다.
삼성전자는 영쩜 삼구 프로, SK하이닉스는 영쩜 팔 프로 내렸습니다.
원달러 환율은 전 거래일보다 13.6원 오른 1,382.2원에 마감했습니다.
외국인은 2조 2,770억원 순매도했습니다. 개인은 4,137억원, 기관은 1,586억원 순매수했습니다.
```

**Exception — the headline figure of a discrete event stays a number.** A Fed decision's
exact hike size, the resulting policy rate, a CPI print, a jobs number: these are themselves
the news, reported everywhere by that exact figure, not a price move to describe qualitatively.
Keep those numeric:

```text
미국 연준은 기준금리를 영쩜 이오 프로포인트 올렸습니다.
기준금리는 이번 인상으로 사 프로대에 진입했습니다.
```

If a scene genuinely needs the precision of a percentage to make its point (rare — most scenes
don't), that's a judgment call, not a default; don't reach for a number just because it's more
"accurate" when the qualitative word already conveys what the viewer needs.

## Russell emphasis

Give the divergence enough narration time to support a full card:

```text
다만 소형주 러셀 이천은 홀로 올랐습니다.
대형주가 하락한 날에도 소형주가 오른 건 시장 전체가 무너지진 않았다는 신호입니다.
대형주와 흐름이 달랐습니다.
```

## Multi-name decliner/riser cards: narrate the theme, not the roll call

When a card lists three or more individual names (e.g. "급락한 종목도 있었습니다" with 카카오페이/에코프로/로보티즈), do not narrate each name and its percentage in turn — that reads as a roll call and drags. Instead, say what ties them together: the shared cause, sector, or theme. Do not read out the individual percentage figures either, even folded into the summary sentence — the card itself still shows every name and its exact percentage; the narration carries no numbers at all here, only the theme.

```text
개별 종목 중에서는 규제 이슈와 업종별 순환매 여파로 낙폭이 컸던 종목들도 있었습니다.
```

not:

```text
카카오페이는 십일쩜 사팔 프로, 에코프로는 이쩜 육일 프로, 로보티즈는 사쩜 칠팔 프로 하락했습니다.
```

This only applies to multi-name lists. A two-item contrast card (like the Russell emphasis above) still gets each side narrated individually because the divergence itself is the point — but per the rule above, "individually" means by name and qualitative direction, not by reading its percentage.

## Movers ordering

Read movers in their top-to-bottom visual order. For the current Market Note template, use Reddit first and Applied Materials second whenever the card is ordered `RDDT` then `AMAT`.
