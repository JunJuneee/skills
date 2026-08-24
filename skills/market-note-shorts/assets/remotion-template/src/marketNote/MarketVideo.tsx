import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import type {CalculateMetadataFunction} from 'remotion';
import {MarketCards} from './MarketCards';
import type {MarketNoteData} from './types';

export type MarketVideoProps = {data: MarketNoteData};

/**
 * The composition length follows the narration rather than a hand-entered constant, so a
 * re-synthesised MP3 only requires rerunning scripts/build_cues.py.
 */
export const calculateMarketVideoMetadata: CalculateMetadataFunction<MarketVideoProps> = ({
  props,
}) => ({
  durationInFrames: props.data.disclaimerFrom + props.data.disclaimerFrames,
});

export const MarketVideo: React.FC<MarketVideoProps> = ({data}) => (
  <AbsoluteFill>
    <Audio src={staticFile(data.audio)} />
    {data.cues.map((cue, index) => (
      <Sequence key={index} from={cue.from} durationInFrames={cue.duration}>
        <MarketCards data={data} scene={index} />
      </Sequence>
    ))}
    <Sequence from={data.disclaimerFrom} durationInFrames={data.disclaimerFrames}>
      <MarketCards data={data} scene={data.scenes.length + 1} />
    </Sequence>
  </AbsoluteFill>
);
