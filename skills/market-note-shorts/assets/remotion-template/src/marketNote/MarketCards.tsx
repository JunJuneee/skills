import React from 'react';
import {MarketNoticeTemplate} from '../MarketNoticeTemplate';
import {
  BLUE,
  BLUE_DARK,
  BODY,
  Card,
  GREEN,
  Label,
  Lines,
  MUTED,
  RED,
  Shell,
  Title,
  toneColor,
} from './theme';
import type {MarketNoteData, Note, Row, Scene} from './types';

const NoteBlock: React.FC<{note: Note}> = ({note}) => {
  const body = {fontSize: 40, lineHeight: 1.36, letterSpacing: -2, fontWeight: 800} as const;

  if (note.style === 'plain') {
    return (
      <div style={{marginTop: 30, ...body, color: BODY}}>
        <Lines lines={note.lines} />
      </div>
    );
  }

  if (note.style === 'dark') {
    return (
      <Card style={{marginTop: 30, background: BLUE_DARK, color: '#F2FBFF'}}>
        <div style={body}>
          <Lines lines={note.lines} />
        </div>
      </Card>
    );
  }

  const tinted = note.tone === 'up' ? GREEN : RED;
  return (
    <Card
      style={{
        marginTop: 30,
        background: `${tinted}1A`,
        color: note.tone === 'up' ? '#3E6357' : '#73565D',
      }}
    >
      <div style={body}>
        <Lines lines={note.lines} />
      </div>
    </Card>
  );
};

const RowBlock: React.FC<{row: Row; index: number}> = ({row, index}) => {
  if (row.kind === 'pair') {
    return (
      <Card>
        <div style={{fontSize: 35, color: MUTED, fontWeight: 900}}>{row.name}</div>
        <div
          style={{
            marginTop: 13,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
          }}
        >
          <span style={{fontSize: 58, letterSpacing: -4, fontWeight: 900}}>{row.value}</span>
          <span style={{fontSize: 47, color: toneColor(row.tone), fontWeight: 900}}>
            {row.change}
          </span>
        </div>
      </Card>
    );
  }

  if (row.kind === 'stat') {
    return (
      <Card>
        <Label>{row.label}</Label>
        <div style={{marginTop: 14, fontSize: 52, lineHeight: 1.2, letterSpacing: -3, fontWeight: 900}}>
          <Lines lines={row.lines} accent={toneColor(row.tone)} />
        </div>
      </Card>
    );
  }

  if (row.kind === 'numbered') {
    return (
      <Card style={{display: 'flex', alignItems: 'center', gap: 22}}>
        <div
          style={{
            width: 61,
            height: 61,
            borderRadius: 19,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: `${toneColor(row.tone)}18`,
            color: toneColor(row.tone),
            fontSize: 28,
            fontWeight: 900,
            flexShrink: 0,
          }}
        >
          {index + 1}
        </div>
        <div style={{fontSize: 42, lineHeight: 1.18, letterSpacing: -2.5, fontWeight: 900}}>
          {row.text}
        </div>
      </Card>
    );
  }

  return (
    <Card style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
      <span style={{fontSize: 44, letterSpacing: -2.5, fontWeight: 900}}>{row.name}</span>
      <span style={{fontSize: 45, color: toneColor(row.tone), fontWeight: 900}}>{row.value}</span>
    </Card>
  );
};

const SceneBlock: React.FC<{scene: Scene}> = ({scene}) => (
  <Shell>
    <Title lines={scene.title} tone={scene.titleTone} />
    <div style={{display: 'grid', gap: 21, marginTop: 64}}>
      {scene.rows.map((row, index) => (
        <RowBlock key={`${row.kind}-${index}`} row={row} index={index} />
      ))}
    </div>
    {scene.note ? <NoteBlock note={scene.note} /> : null}
  </Shell>
);

const OpeningBlock: React.FC<{data: MarketNoteData}> = ({data}) => {
  const {opening} = data;
  return (
    <Shell>
      <div style={{fontSize: 36, color: BLUE, fontWeight: 900, letterSpacing: 1.1}}>
        {opening.eyebrow}
      </div>
      <div
        style={{
          marginTop: 28,
          fontSize: 105,
          lineHeight: 1.04,
          letterSpacing: -10,
          fontWeight: 900,
        }}
      >
        {opening.headline[0]}
        <br />
        <span style={{color: toneColor(opening.headlineTone)}}>{opening.headline[1]}</span>
      </div>
      <div
        style={{
          marginTop: 61,
          padding: '40px 42px',
          borderRadius: 31,
          background: BLUE_DARK,
          color: '#F2FBFF',
        }}
      >
        <div style={{fontSize: 29, color: '#A9DDF5', fontWeight: 900, letterSpacing: 1.4}}>
          {opening.summaryLabel}
        </div>
        <div
          style={{
            marginTop: 16,
            fontSize: 47,
            lineHeight: 1.31,
            letterSpacing: -2.5,
            fontWeight: 900,
          }}
        >
          <Lines lines={opening.summaryLines} />
        </div>
      </div>
    </Shell>
  );
};

/**
 * Scene 0 is the opening, scenes 1..n come from data.scenes, and the last index is the
 * disclaimer. Rendering a single scene is what the card-image export uses.
 */
export const MarketCards: React.FC<{data: MarketNoteData; scene?: number}> = ({
  data,
  scene = 0,
}) => {
  const disclaimerIndex = data.scenes.length + 1;
  if (scene >= disclaimerIndex) {
    return (
      <MarketNoticeTemplate
        dateLabel={data.dateLabel}
        marketLabel={data.marketLabel}
        socialSafe
      />
    );
  }
  if (scene <= 0) return <OpeningBlock data={data} />;
  return <SceneBlock scene={data.scenes[scene - 1]} />;
};
