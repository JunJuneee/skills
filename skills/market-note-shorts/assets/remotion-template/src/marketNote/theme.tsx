import React from 'react';
import {AbsoluteFill} from 'remotion';

// Market Note palette. Keep in sync with the skill's references/visual-spec.md.
export const INK = '#112B45';
export const BLUE = '#2E76A6';
export const BLUE_DARK = '#155D82';
export const MUTED = '#59758E';
export const RED = '#E95B62';
export const GREEN = '#20886A';
export const BODY = '#496A83';
export const CARD = 'rgba(255,255,255,.86)';
export const FONT = 'Apple SD Gothic Neo, Arial, sans-serif';

export type Tone = 'up' | 'down' | 'neutral' | 'blue';

export const toneColor = (tone: Tone | undefined): string => {
  if (tone === 'up') return GREEN;
  if (tone === 'down') return RED;
  if (tone === 'blue') return BLUE;
  return INK;
};

// The content frame is the Instagram Reels and YouTube Shorts safe area: equal 84 px side
// margins, nothing above 260 px, and every essential glyph left of x=864 so the platform
// action rail never covers a number. See references/visual-spec.md.
export const SAFE_LEFT = 84;
export const SAFE_TOP = 270;
export const SAFE_WIDTH = 780;

export const Shell: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill
    style={{
      background: 'linear-gradient(160deg, #E9F6FF 0%, #F1F8F4 53%, #DFEDF9 100%)',
      color: INK,
      fontFamily: FONT,
      overflow: 'hidden',
    }}
  >
    <div
      style={{
        position: 'absolute',
        width: 760,
        height: 760,
        right: -420,
        top: 380,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(63,146,196,.17), rgba(63,146,196,0) 67%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        width: 620,
        height: 620,
        left: -390,
        bottom: -310,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(100,191,147,.12), rgba(100,191,147,0) 67%)',
      }}
    />
    <div style={{position: 'absolute', top: SAFE_TOP, left: SAFE_LEFT, width: SAFE_WIDTH}}>
      {children}
    </div>
  </AbsoluteFill>
);

export const Card: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({
  children,
  style,
}) => (
  <div
    style={{
      padding: '30px 35px',
      borderRadius: 30,
      background: CARD,
      border: '1px solid rgba(48,108,145,.15)',
      boxShadow: '0 12px 24px rgba(37,94,132,.08)',
      ...style,
    }}
  >
    {children}
  </div>
);

export const Title: React.FC<{lines: [string, string]; tone?: Tone}> = ({lines, tone}) => (
  <div style={{fontSize: 86, lineHeight: 1.1, letterSpacing: -7.5, fontWeight: 900}}>
    {lines[0]}
    <br />
    <span style={{color: toneColor(tone)}}>{lines[1]}</span>
  </div>
);

export const Label: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div style={{fontSize: 31, color: MUTED, fontWeight: 900, letterSpacing: 0.4}}>{children}</div>
);

/**
 * Renders one line, colouring any run wrapped in asterisks: "최대 *150조원*" keeps 최대 in
 * ink and paints 150조원 with the accent. Escaping is unnecessary because the copy never
 * contains a literal asterisk.
 */
const RichLine: React.FC<{text: string; accent?: string}> = ({text, accent}) => (
  <>
    {text.split('*').map((part, index) =>
      index % 2 === 1 ? (
        <span key={index} style={{color: accent}}>
          {part}
        </span>
      ) : (
        <React.Fragment key={index}>{part}</React.Fragment>
      ),
    )}
  </>
);

export const Lines: React.FC<{lines: string[]; accent?: string}> = ({lines, accent}) => (
  <>
    {lines.map((line, index) => (
      <React.Fragment key={`${index}-${line}`}>
        {index > 0 ? <br /> : null}
        <RichLine text={line} accent={accent} />
      </React.Fragment>
    ))}
  </>
);
