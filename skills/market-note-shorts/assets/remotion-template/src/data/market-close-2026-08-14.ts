export const marketClose20260814 = {
  dateLabel: '2026.08.14 · 미국 증시',
  headline: '신고가 뒤\n잠시 숨 고르기',
  hook: '소비 둔화 신호에\n미 증시가 소폭 후퇴했습니다',
  indices: [
    {label: 'S&P 500', close: '7,785.76', change: '-0.2%'},
    {label: 'NASDAQ', close: '26,729.16', change: '-0.3%'},
    {label: 'DOW', close: '53,732.41', change: '-0.2%'},
  ],
  macro: {
    retailSales: '-0.6%',
    tenYearYield: '4.69%',
    brent: '$88.52',
    brentChange: '+1.7%',
  },
  movers: [
    {ticker: 'RDDT', change: '+12.6%', note: 'S&P 500 편입 발표'},
    {ticker: 'AMAT', change: '-5.1%', note: '호실적에도 높은 기대 부담'},
  ],
  next: [
    {day: '월', event: 'Empire State 제조업'},
    {day: '화', event: '산업생산 · 주택지표'},
  ],
  narration: '8월 14일 미국 증시는 전날 기록을 세운 뒤 잠시 숨을 골랐습니다. S&P 500은 0.2% 내려 7,785.76, 나스닥은 0.3%, 다우는 0.2% 하락했습니다. 핵심은 7월 소매판매입니다. 전월 대비 0.6% 줄어 소비 둔화 신호가 나왔습니다. 유가가 오르며 10년물 국채금리는 4.69%로 상승했고, 장 초반 상승분도 반납했습니다. 종목별로는 레딧이 S&P 500 편입 소식에 12.6% 뛰었지만, 호실적을 낸 어플라이드 머티어리얼즈는 기대가 높았던 탓에 5.1% 밀렸습니다. 다음 주에는 제조업과 산업생산 지표가 경기 둔화 우려를 더 키울지 확인할 필요가 있습니다. 투자 판단이 아닌 시장 요약입니다.',
  sources: [
    {
      name: 'Associated Press, 2026-08-14 market close',
      url: 'https://apnews.com/article/stocks-markets-rates-oil-inflation-futures-5d9870d6c5ae735f9b74bf4ceefaa3ec',
    },
    {
      name: 'U.S. Census Bureau, July 2026 Advance Retail Sales',
      url: 'https://www.census.gov/retail/marts/www/marts_current.pdf',
    },
    {
      name: 'Federal Reserve Bank of New York, August 2026 calendar',
      url: 'https://www.newyorkfed.org/research/calendars/i-aug26.html',
    },
  ],
} as const;
