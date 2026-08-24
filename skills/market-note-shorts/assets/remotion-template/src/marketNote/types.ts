import type {Tone} from './theme';

/** A footnote under the rows. `tint` picks up the scene's own tone. */
export type Note =
  | {style: 'plain'; lines: string[]}
  | {style: 'tint'; tone: Tone; lines: string[]}
  | {style: 'dark'; lines: string[]};

/**
 * Row shapes observed across every Market Note episode:
 *  - `pair`     index or stock with both a close and a change (KOSPI 6,696.96 / -3.12%)
 *  - `stat`     a labelled figure that needs room to wrap (주주환원 90조~110조원)
 *  - `single`   name on the left, one value on the right (개인 / +3조 3,217억원)
 *  - `numbered` an ordered checklist item
 */
export type Row =
  | {kind: 'pair'; name: string; value: string; change: string; tone: Tone}
  | {kind: 'stat'; label: string; lines: string[]; tone?: Tone}
  | {kind: 'single'; name: string; value: string; tone: Tone}
  | {kind: 'numbered'; text: string; tone: Tone};

export type Scene = {
  title: [string, string];
  titleTone: Tone;
  rows: Row[];
  note?: Note;
};

export type Opening = {
  eyebrow: string;
  headline: [string, string];
  headlineTone: Tone;
  summaryLabel: string;
  summaryLines: string[];
};

/** One sequence of the narration, in frames, produced by scripts/build_cues.py. */
export type Cue = {from: number; duration: number};

export type MarketNoteData = {
  market: 'korea' | 'us';
  date: string;
  /** Header text on the disclaimer card, e.g. "2026.08.24 · 한국 증시". */
  dateLabel: string;
  marketLabel: string;
  /** File name inside public/, passed to staticFile(). */
  audio: string;
  opening: Opening;
  /** Scenes after the opening. Cue 0 is the opening, cue N covers scenes[N-1]. */
  scenes: Scene[];
  cues: Cue[];
  disclaimerFrom: number;
  disclaimerFrames: number;
};
