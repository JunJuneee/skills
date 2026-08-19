import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {marketClose20260814 as data} from './data/market-close-2026-08-14';

const INK = '#112B45';
const BLUE = '#2E76A6';
const BLUE_DARK = '#155D82';
const SKY = '#E8F5FF';
const CARD = 'rgba(255,255,255,.78)';
const MUTED = '#59758E';
const RED = '#E95B62';
const GREEN = '#20886A';
const GOLD = '#FFCD62';
const font = 'Apple SD Gothic Neo, Arial, sans-serif';

// These boundaries come from the supplied ElevenLabs audio, transcribed with word-level timestamps.
// Every visual segment begins when its corresponding narration sentence begins.
const CUES = [
  {from: 0, duration: 167},
  {from: 167, duration: 390},
  {from: 557, duration: 494},
  {from: 1051, duration: 129},
  {from: 1180, duration: 400},
  {from: 1580, duration: 405},
  {from: 1985, duration: 180},
  {from: 2165, duration: 526},
] as const;

const Enter: React.FC<{children: React.ReactNode; delay?: number; fill?: boolean}> = ({children, delay = 0, fill = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({fps, frame: Math.max(0, frame - delay), config: {damping: 20, stiffness: 160, mass: 0.8}});
  return <div style={{height: fill ? '100%' : undefined, opacity: p, transform: `translateY(${interpolate(p, [0, 1], [26, 0])}px)`}}>{children}</div>;
};

const GlobalHud: React.FC = () => {
  const frame = useCurrentFrame();
  const percent = interpolate(frame, [0, 2690], [0, 100], {extrapolateRight: 'clamp'});
  return <>
    <div style={{position: 'absolute', top: 48, left: 54, right: 54, display: 'flex', justifyContent: 'space-between', zIndex: 10, color: MUTED, fontSize: 32, fontWeight: 900, fontFamily: font}}>
      <span>{data.dateLabel}</span><span style={{color: BLUE, letterSpacing: -.5}}>Market Note</span>
    </div>
    <div style={{position: 'absolute', top: 99, left: 54, right: 54, height: 4, borderRadius: 4, background: 'rgba(46,118,166,.14)', zIndex: 10}}><div style={{width: `${percent}%`, height: '100%', borderRadius: 4, background: BLUE}} /></div>
    <div style={{position: 'absolute', left: 54, right: 54, bottom: 42, fontFamily: font, color: '#6F8DA5', fontSize: 23, fontWeight: 800, zIndex: 10}}>투자 권유가 아닌 시장 정보 요약 · 출처: AP · Census · NY Fed</div>
  </>;
};

const Shell: React.FC<{children: React.ReactNode; cue: number}> = ({children}) => <AbsoluteFill style={{background: 'linear-gradient(160deg, #E9F6FF 0%, #F1F8F4 53%, #DFEDF9 100%)', color: INK, fontFamily: font, overflow: 'hidden'}}>
  <div style={{position: 'absolute', width: 760, height: 760, right: -420, top: 380, borderRadius: '50%', background: 'radial-gradient(circle, rgba(63,146,196,.17), rgba(63,146,196,0) 67%)'}} />
  <div style={{position: 'absolute', width: 600, height: 600, left: -390, bottom: -290, borderRadius: '50%', background: 'radial-gradient(circle, rgba(100,191,147,.12), rgba(100,191,147,0) 67%)'}} />
  <div style={{position: 'absolute', inset: 0}}>
    <div style={{position: 'absolute', top: 145, left: 54, right: 54, color: BLUE, fontSize: 38, fontWeight: 900, letterSpacing: 1.2}}>오늘의 미국 증시</div>
    {children}
  </div>
</AbsoluteFill>;

const MetricCard: React.FC<{name: string; close: string; change: string; delay?: number}> = ({name, close, change, delay = 0}) => <Enter delay={delay}><div style={{padding: '38px 40px', minHeight: 172, background: CARD, border: '1px solid rgba(48,108,145,.15)', borderRadius: 31, boxShadow: '0 12px 24px rgba(37,94,132,.08)'}}><div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}><span style={{fontSize: 43, fontWeight: 900}}>{name}</span><span style={{fontSize: 72, letterSpacing: -4, fontWeight: 900}}>{close}</span></div><div style={{color: RED, marginTop: 5, fontSize: 47, fontWeight: 900, textAlign: 'right'}}>{change}</div></div></Enter>;

const Opening = () => <Shell cue={0}><div style={{position: 'absolute', left: 54, right: 54, top: 270}}><Enter><div style={{fontSize: 38, color: BLUE, fontWeight: 900, letterSpacing: 1.1}}>CLOSE IN ONE MINUTE</div><div style={{marginTop: 24, fontSize: 140, lineHeight: 1.02, letterSpacing: -11, fontWeight: 900}}>오늘 시장은<br/><span style={{color: BLUE}}>잠시 쉬어감</span></div></Enter><Enter delay={18}><div style={{marginTop: 62, padding: '40px 42px', borderRadius: 30, background: '#155D82', color: '#F2FBFF'}}><div style={{fontSize: 30, color: '#A9DDF5', fontWeight: 900, letterSpacing: 1.4}}>ONE-LINE SUMMARY</div><div style={{marginTop: 15, fontSize: 52, lineHeight: 1.27, letterSpacing: -2.5, fontWeight: 800}}>신고가 다음 날,<br/>3대 지수는 소폭 후퇴</div></div></Enter></div></Shell>;

const Indices = () => <Shell cue={1}><div style={{position: 'absolute', left: 54, right: 54, top: 262}}><Enter><div style={{fontSize: 96, lineHeight: 1.16, letterSpacing: -8, fontWeight: 900}}>지수는 약했지만,<br/><span style={{color: BLUE}}>낙폭은 크지 않았습니다</span></div></Enter><div style={{display: 'grid', gap: 22, marginTop: 64}}>{data.indices.map((index, i) => <MetricCard key={index.label} name={index.label} close={index.close} change={index.change} delay={i * 10 + 8} />)}</div><Enter delay={45}><div style={{marginTop: 42, padding: '32px 35px', borderRadius: 27, background: 'rgba(255,255,255,.52)', color: '#50718A', fontSize: 40, lineHeight: 1.38, letterSpacing: -2, fontWeight: 800}}>소형주 Russell 2000은 <span style={{color: GREEN, fontWeight: 900}}>+0.5%</span>.<br/>대형주와는 다른 흐름이었습니다.</div></Enter></div></Shell>;

const Pulse = () => <Shell cue={2}><div style={{position: 'absolute', left: 54, right: 54, top: 285}}><Enter><div style={{fontSize: 92, lineHeight: 1.1, letterSpacing: -8, fontWeight: 900}}>소형주는<br/><span style={{color: GREEN}}>오히려 올랐습니다</span></div></Enter><Enter delay={12}><div style={{marginTop: 64, padding: '42px 44px', borderRadius: 34, background: '#F7FFFB', border: '3px solid rgba(32,136,106,.25)', boxShadow: '0 16px 32px rgba(32,136,106,.16)'}}><div style={{fontSize: 35, color: MUTED, fontWeight: 900, letterSpacing: .5}}>RUSSELL 2000</div><div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 10}}><span style={{fontSize: 44, fontWeight: 900}}>소형주</span><span style={{fontSize: 142, color: GREEN, letterSpacing: -10, lineHeight: 1, fontWeight: 900}}>+0.5%</span></div><div style={{marginTop: 24, paddingTop: 24, borderTop: '2px solid rgba(32,136,106,.18)', color: '#477187', fontSize: 38, lineHeight: 1.35, fontWeight: 800}}>대형주 3대 지수는 하락했지만,<br/>소형주는 상승했습니다.</div></div></Enter><Enter delay={30}><div style={{marginTop: 38, padding: '32px 36px', borderRadius: 28, background: 'rgba(22,92,129,.10)', color: '#41637C', fontSize: 42, lineHeight: 1.38, letterSpacing: -2, fontWeight: 800}}>시장 전체가 무너지기보다,<br/><span style={{color: BLUE_DARK, fontWeight: 900}}>규모별 흐름이 갈린 날</span>이었습니다.</div></Enter></div></Shell>;

const RetailLead = () => <Shell cue={2}><div style={{position: 'absolute', left: 54, right: 54, top: 315}}><Enter><div style={{fontSize: 40, color: BLUE, fontWeight: 900, letterSpacing: 1.2}}>ONE THING TO WATCH</div><div style={{marginTop: 32, fontSize: 140, lineHeight: 1.02, letterSpacing: -11, fontWeight: 900}}>핵심은<br/><span style={{color: BLUE}}>소매판매</span></div></Enter></div></Shell>;

const Retail = () => <Shell cue={3}><div style={{position: 'absolute', left: 54, right: 54, top: 315}}><Enter><div style={{fontSize: 30, color: BLUE, fontWeight: 900, letterSpacing: 1.2}}>JULY RETAIL SALES</div><div style={{fontSize: 152, lineHeight: .9, color: RED, letterSpacing: -10, fontWeight: 900, marginTop: 22}}>{data.macro.retailSales}</div></Enter><Enter delay={13}><div style={{marginTop: 44, padding: '31px', borderRadius: 25, background: CARD, border: '1px solid rgba(48,108,145,.15)', fontSize: 37, lineHeight: 1.3, letterSpacing: -2, fontWeight: 800}}>전월 대비 감소.<br/>소비의 힘이 <span style={{color: RED}}>약해졌다는 신호</span>입니다.</div></Enter></div></Shell>;

const Macro = () => <Shell cue={4}><div style={{position: 'absolute', left: 54, right: 54, top: 267}}><Enter><div style={{fontSize: 96, lineHeight: 1.1, letterSpacing: -8, fontWeight: 900}}>소비는 약해지고,<br/><span style={{color: BLUE}}>유가·금리는 부담</span></div></Enter><div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22, marginTop: 67}}><Enter delay={10} fill><div style={{height: '100%', boxSizing: 'border-box', padding: '40px', minHeight: 238, borderRadius: 31, background: CARD}}><div style={{fontSize: 38, color: MUTED, fontWeight: 900}}>7월 소매판매</div><div style={{fontSize: 86, letterSpacing: -5, color: RED, fontWeight: 900, marginTop: 24}}>{data.macro.retailSales}</div></div></Enter><Enter delay={18} fill><div style={{height: '100%', boxSizing: 'border-box', padding: '40px', minHeight: 238, borderRadius: 31, background: CARD}}><div style={{fontSize: 38, color: MUTED, fontWeight: 900}}>브렌트유</div><div style={{fontSize: 80, letterSpacing: -5, fontWeight: 900, marginTop: 20}}>{data.macro.brent}</div><div style={{fontSize: 38, color: RED, fontWeight: 900, marginTop: 3}}>{data.macro.brentChange}</div></div></Enter></div><Enter delay={30}><div style={{marginTop: 26, padding: '36px 40px', minHeight: 192, boxSizing: 'border-box', borderRadius: 29, background: 'rgba(255,255,255,.52)'}}><div style={{fontSize: 38, color: MUTED, fontWeight: 900}}>10년물 국채금리</div><div style={{fontSize: 84, letterSpacing: -5, fontWeight: 900, marginTop: 13}}>{data.macro.tenYearYield}</div></div></Enter><Enter delay={40}><div style={{marginTop: 38, color: '#4B6C84', fontSize: 45, lineHeight: 1.38, letterSpacing: -2.2, fontWeight: 800}}>소비 둔화 우려에 유가와 금리 부담까지 겹치며,<br/>상승 흐름이 약해졌습니다.</div></Enter></div></Shell>;

const Movers = () => <Shell cue={5}><div style={{position: 'absolute', left: 54, right: 54, top: 265}}><Enter><div style={{fontSize: 96, lineHeight: 1.1, letterSpacing: -8, fontWeight: 900}}>종목별로는<br/><span style={{color: BLUE}}>온도 차가 뚜렷</span></div></Enter><Enter delay={12}><div style={{marginTop: 67, padding: '41px 43px', borderRadius: 31, background: CARD}}><div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}><span style={{fontSize: 80, fontWeight: 900}}>RDDT</span><span style={{fontSize: 74, color: GREEN, fontWeight: 900}}>+12.6%</span></div><div style={{marginTop: 16, color: MUTED, fontSize: 41, fontWeight: 800}}>S&P 500 편입 소식</div></div></Enter><Enter delay={29}><div style={{marginTop: 24, padding: '41px 43px', borderRadius: 31, background: CARD}}><div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}><span style={{fontSize: 80, fontWeight: 900}}>AMAT</span><span style={{fontSize: 74, color: RED, fontWeight: 900}}>-5.1%</span></div><div style={{marginTop: 16, color: MUTED, fontSize: 41, fontWeight: 800}}>호실적에도 높은 기대 부담</div></div></Enter><Enter delay={47}><div style={{marginTop: 43, padding: '31px 35px', borderRadius: 27, background: 'rgba(22,92,129,.10)', color: '#41637C', fontSize: 42, lineHeight: 1.38, letterSpacing: -2, fontWeight: 800}}>지금은 지수보다 <span style={{color: BLUE_DARK, fontWeight: 900}}>개별 종목의 기대치</span>가 더 중요합니다.</div></Enter></div></Shell>;

const Takeaway = () => <Shell cue={6}><div style={{position: 'absolute', left: 54, right: 54, top: 350}}><Enter><div style={{fontSize: 39, color: BLUE, fontWeight: 900, letterSpacing: 1.3}}>TODAY'S TAKEAWAY</div><div style={{marginTop: 31, fontSize: 120, lineHeight: 1.04, letterSpacing: -9, fontWeight: 900}}>급락보다<br/><span style={{color: BLUE}}>종목별 선별</span></div></Enter><Enter delay={15}><div style={{marginTop: 58, padding: '40px 42px', borderRadius: 31, background: '#155D82', color: '#F2FBFF', fontSize: 48, lineHeight: 1.35, letterSpacing: -2.5, fontWeight: 800}}>오늘은 모든 자산이 무너진 날보다,<br/>기대치에 따라 결과가 갈린 날이었습니다.</div></Enter></div></Shell>;

const Outlook = () => <Shell cue={6}><div style={{position: 'absolute', left: 54, right: 54, top: 286}}><Enter><div style={{fontSize: 100, lineHeight: 1.1, letterSpacing: -8, fontWeight: 900}}>다음 주엔<br/><span style={{color: BLUE}}>경기 지표 확인</span></div></Enter><div style={{display: 'grid', gap: 25, marginTop: 75}}>{data.next.map((entry, i) => <Enter key={entry.day} delay={i * 12 + 12}><div style={{display: 'grid', gridTemplateColumns: '158px 1fr', borderRadius: 31, overflow: 'hidden', background: CARD}}><div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#D4EBF8', color: BLUE, fontSize: 55, fontWeight: 900}}>{entry.day}</div><div style={{padding: '40px 41px', fontSize: 49, letterSpacing: -2.5, fontWeight: 800}}>{entry.event}</div></div></Enter>)}</div><Enter delay={38}><div style={{marginTop: 51, color: '#517088', fontSize: 42, lineHeight: 1.38, letterSpacing: -2, fontWeight: 800}}>소비 둔화 우려가 일시적인지,<br/>다음 지표가 확인해 줄 차례입니다.</div></Enter></div></Shell>;

const Disclaimer = () => <Shell cue={7}><div style={{position: 'absolute', left: 54, right: 54, top: 390, textAlign: 'center'}}><div style={{fontSize: 38, color: BLUE, fontWeight: 900, letterSpacing: 1.4}}>NOTICE</div><div style={{marginTop: 20, fontSize: 88, lineHeight: 1.05, letterSpacing: -7, fontWeight: 900}}>책임면책고시</div><div style={{marginTop: 52, padding: '46px 38px', borderRadius: 32, background: CARD, border: '1px solid rgba(48,108,145,.15)', boxShadow: '0 12px 24px rgba(37,94,132,.08)', color: '#41637C', fontSize: 30, lineHeight: 1.68, letterSpacing: -1, fontWeight: 700}}>본 자료는 작성 시점 기준의 정보와 분석을 바탕으로<br/>제공되며 수익을 보장하거나 손실 회피를 약속하지 않습니다.<br/>투자 결과에 대해 작성자 및 제공자는 법적 책임을 부담하지 않으며<br/>모든 투자는 본인의 판단과 책임하에 진행하시기 바랍니다.</div></div></Shell>;

export const DailyMarketCloseCalm20260814: React.FC = () => <AbsoluteFill>
  <Audio src={staticFile('daily-close-2026-08-14-final-tts.mp3')} />
  <GlobalHud />
  <Sequence from={CUES[0].from} durationInFrames={CUES[0].duration}><Opening /></Sequence>
  <Sequence from={CUES[1].from} durationInFrames={CUES[1].duration}><Indices /></Sequence>
  <Sequence from={CUES[2].from} durationInFrames={CUES[2].duration}><Pulse /></Sequence>
  <Sequence from={CUES[3].from} durationInFrames={CUES[3].duration}><RetailLead /></Sequence>
  <Sequence from={CUES[4].from} durationInFrames={CUES[4].duration}><Macro /></Sequence>
  <Sequence from={CUES[5].from} durationInFrames={CUES[5].duration}><Movers /></Sequence>
  <Sequence from={CUES[6].from} durationInFrames={CUES[6].duration}><Takeaway /></Sequence>
  <Sequence from={CUES[7].from} durationInFrames={CUES[7].duration}><Outlook /></Sequence>
  <Sequence from={2691} durationInFrames={60}><Disclaimer /></Sequence>
</AbsoluteFill>;
