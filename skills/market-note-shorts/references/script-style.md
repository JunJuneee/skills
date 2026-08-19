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
| 0.2% | 영쩜 이 percent |
| 0.3% | 영쩜 삼 percent |
| 0.5% | 영쩜 오 percent |
| 0.6% | 영쩜 육 percent |
| 1.7% | 일쩜 칠 percent |
| 5.1% | 오쩜 일 percent |
| 12.6% | 십이쩜 육 percent |
| 2.43% | 이쩜 사삼 percent |
| 0.38% | 영쩜 삼팔 percent |
| 3.26% | 삼쩜 이육 percent |
| 8.24% | 팔쩜 이사 percent |

## Punctuation

- Insert exactly one space after `쩜`: `영쩜 이`, not `영쩜이`.
- When the decimal part has two or more digits, concatenate all decimal digits with no spaces: `이쩜 사삼`, not `이쩜 사 삼`.
- Write the unit as the English word `percent`, not `퍼센트` or `%`.
- End sentences with a period.
- Avoid commas in ordinary prose.
- Use commas only for genuine lists, including the grouped index sentence.
- Put one sentence on each line.
- Do not narrate the disclaimer.

## Preferred grouped-index sentence

```text
에쓰앤피 오백은 영쩜 이 percent, 나스닥은 영쩜 삼 percent, 다우는 영쩜 이 percent 하락했습니다.
```

## Russell emphasis

Give the divergence enough narration time to support a full card:

```text
다만 소형주 러셀 이천은 영쩜 오 percent 올랐습니다.
대형주가 하락한 날에도 소형주가 오른 건 시장 전체가 무너지진 않았다는 신호입니다.
대형주와 흐름이 달랐습니다.
```

## Movers ordering

Read movers in their top-to-bottom visual order. For the current Market Note template, use Reddit first and Applied Materials second whenever the card is ordered `RDDT` then `AMAT`.
