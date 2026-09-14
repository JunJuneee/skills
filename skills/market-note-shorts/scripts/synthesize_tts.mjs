#!/usr/bin/env node
// ElevenLabs TTS 합성 — Market Note Shorts
//
// 사용 예:
//   node synthesize_tts.mjs --list-voices
//   node synthesize_tts.mjs --text tts.txt --out narration.mp3 --voice "Kim"
//
// API 키는 다음 순서로 찾습니다.
//   1) 환경변수 ELEVENLABS_API_KEY 또는 ELEVENLABS_KEY
//   2) macOS 키체인 (security find-generic-password -s ELEVENLABS_API_KEY -w)
//   3) 로그인 셸 프로필 (~/.zshrc 의 ELEVENLABS_API_KEY 또는 ELEVENLABS_KEY)

import {readFile, writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';

const API = 'https://api.elevenlabs.io/v1';

// 기본값은 Market Note 시리즈의 ElevenLabs UI 설정과 동일하게 맞춘 값이다.
// Voice: Kim - Neutral, Steady and Calm / Model: Eleven Multilingual v2
// ElevenLabs history 로 확인한 08-18~08-21 운영 회차의 실제 설정과 동일하다.
// stability 1.0 / similarity 0.18 / style 0.11 / speaker boost ON, speed 만 1.1 -> 1.2 로 변경
const DEFAULTS = {
  voice: 'Kim',
  model: 'eleven_multilingual_v2',
  format: 'mp3_44100_128',
  stability: 1.0,
  similarity: 0.18,
  style: 0.11,
  speed: 1.2,
  speakerBoost: true,
};

function parseArgs(argv) {
  const out = {...DEFAULTS, flags: new Set()};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    switch (key) {
      case 'list-voices':
      case 'dry-run':
      case 'help':
        out.flags.add(key);
        break;
      case 'speaker-boost': out.speakerBoost = true; break;
      case 'no-speaker-boost': out.speakerBoost = false; break;
      case 'text': out.text = next; i++; break;
      case 'out': out.out = next; i++; break;
      case 'voice': out.voice = next; i++; break;
      case 'model': out.model = next; i++; break;
      case 'format': out.format = next; i++; break;
      case 'stability': out.stability = Number(next); i++; break;
      case 'similarity': out.similarity = Number(next); i++; break;
      case 'style': out.style = Number(next); i++; break;
      case 'speed': out.speed = Number(next); i++; break;
      default:
        throw new Error(`알 수 없는 옵션: --${key}`);
    }
  }
  return out;
}

function apiKey() {
  const fromEnv = (process.env.ELEVENLABS_API_KEY ?? process.env.ELEVENLABS_KEY)?.trim();
  if (fromEnv) return fromEnv;
  try {
    const fromKeychain = execFileSync('security', ['find-generic-password', '-s', 'ELEVENLABS_API_KEY', '-w'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
    if (fromKeychain) return fromKeychain;
  } catch {
    // 키체인 항목 없음
  }
  try {
    // ~/.zshrc 등 로그인 프로필에만 키가 있는 경우 (비대화형 셸에서는 로드되지 않음)
    const fromProfile = execFileSync('zsh', ['-ic', 'printf %s "${ELEVENLABS_API_KEY:-$ELEVENLABS_KEY}"'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
    if (fromProfile) return fromProfile;
  } catch {
    // 프로필 로드 실패
  }
  throw new Error(
    'ELEVENLABS_API_KEY(또는 ELEVENLABS_KEY)를 찾을 수 없습니다.\n' +
    '키체인에 저장: security add-generic-password -a "$USER" -s ELEVENLABS_API_KEY -w \'<API_KEY>\'\n' +
    '또는 실행 시: ELEVENLABS_API_KEY=<API_KEY> node synthesize_tts.mjs ...'
  );
}

async function call(path, init = {}) {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {'xi-api-key': apiKey(), ...(init.headers ?? {})},
  });
  if (!res.ok) {
    throw new Error(`ElevenLabs API 실패 (${res.status} ${res.statusText}): ${await res.text()}`);
  }
  return res;
}

async function listVoices() {
  try {
    const res = await call('/voices');
    const {voices} = await res.json();
    return voices;
  } catch (error) {
    if (String(error.message).includes('voices_read')) {
      throw new Error(
        '이 API 키에는 voices_read 권한이 없어 보이스 이름으로 조회할 수 없습니다.\n' +
        'ElevenLabs 대시보드에서 키에 voices_read 권한을 추가하거나, --voice 에 voice_id(20자)를 직접 지정하세요.'
      );
    }
    throw error;
  }
}

function pickVoice(voices, wanted) {
  const byId = voices.find((v) => v.voice_id === wanted);
  if (byId) return byId;
  const needle = wanted.toLowerCase();
  const exact = voices.find((v) => v.name.toLowerCase() === needle);
  if (exact) return exact;
  const partial = voices.filter((v) => v.name.toLowerCase().includes(needle));
  if (partial.length === 1) return partial[0];
  if (partial.length > 1) {
    throw new Error(`"${wanted}"에 해당하는 보이스가 여러 개입니다: ${partial.map((v) => `${v.name} (${v.voice_id})`).join(', ')}`);
  }
  throw new Error(`"${wanted}" 보이스를 찾지 못했습니다. --list-voices 로 목록을 확인하세요.`);
}

function durationSeconds(file) {
  try {
    return Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', file], {encoding: 'utf8'}).trim());
  } catch {
    return null;
  }
}

const HELP = `ElevenLabs TTS 합성 (Market Note Shorts)

  --text FILE          TTS 원고 파일 (UTF-8, 한 줄 = 한 문장)
  --out FILE           출력 MP3 경로
  --voice NAME|ID      보이스 이름 또는 voice_id (기본: ${DEFAULTS.voice})
  --model ID           모델 (기본: ${DEFAULTS.model})
  --format FMT         출력 포맷 (기본: ${DEFAULTS.format})
  --stability N        0~1 (기본: ${DEFAULTS.stability})
  --similarity N       0~1 (기본: ${DEFAULTS.similarity})
  --style N            0~1 (기본: ${DEFAULTS.style})
  --speed N            0.7~1.2 (기본: ${DEFAULTS.speed})
  --speaker-boost      Speaker boost 켜기 (기본: 켬)
  --no-speaker-boost   Speaker boost 끄기
  --list-voices        계정의 보이스 목록 출력
  --dry-run            API 호출 없이 설정과 원고만 검증
`;

const args = parseArgs(process.argv.slice(2));

if (args.flags.has('help')) {
  console.log(HELP);
  process.exit(0);
}

if (args.flags.has('list-voices')) {
  const voices = await listVoices();
  for (const v of voices) {
    const labels = Object.values(v.labels ?? {}).filter(Boolean).join(' / ');
    console.log(`${v.voice_id}  ${v.name}${labels ? `  [${labels}]` : ''}`);
  }
  console.log(`\n총 ${voices.length}개`);
  process.exit(0);
}

if (!args.text || !args.out) {
  console.error('--text 와 --out 은 필수입니다.\n');
  console.error(HELP);
  process.exit(1);
}

const raw = await readFile(args.text, 'utf8');
const text = raw.replace(/\r\n/g, '\n').trim();

if (!text) throw new Error(`${args.text} 가 비어 있습니다.`);

const LIMITS = {eleven_multilingual_v2: 10000, eleven_v3: 5000, eleven_flash_v2_5: 40000, eleven_turbo_v2_5: 40000};
const limit = LIMITS[args.model];
if (limit && text.length > limit) {
  throw new Error(`원고가 ${args.model} 한도(${limit}자)를 초과했습니다: ${text.length}자`);
}

const summary = {
  text: args.text,
  out: args.out,
  chars: text.length,
  lines: text.split('\n').filter(Boolean).length,
  voice: args.voice,
  model: args.model,
  format: args.format,
  voice_settings: {stability: args.stability, similarity_boost: args.similarity, style: args.style, speed: args.speed, use_speaker_boost: args.speakerBoost},
};

if (args.flags.has('dry-run')) {
  console.log('[dry-run] 합성 설정');
  console.log(JSON.stringify(summary, null, 2));
  console.log('\n첫 문장:', text.split('\n')[0]);
  process.exit(0);
}

const VOICE_ID_RE = /^[A-Za-z0-9]{20}$/;
const voice = VOICE_ID_RE.test(args.voice)
  ? {voice_id: args.voice, name: '(voice_id 직접 지정)'}
  : pickVoice(await listVoices(), args.voice);

const res = await call(`/text-to-speech/${voice.voice_id}?output_format=${encodeURIComponent(args.format)}`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    text,
    model_id: args.model,
    voice_settings: {
      stability: args.stability,
      similarity_boost: args.similarity,
      style: args.style,
      use_speaker_boost: args.speakerBoost,
      speed: args.speed,
    },
  }),
});

await writeFile(args.out, Buffer.from(await res.arrayBuffer()));

const seconds = durationSeconds(args.out);
console.log(JSON.stringify({
  ...summary,
  voice_name: voice.name,
  voice_id: voice.voice_id,
  duration_seconds: seconds,
  disclaimer_total_seconds: seconds === null ? null : Math.round((seconds + 2) * 1000) / 1000,
}, null, 2));
console.log(`\n생성 완료: ${args.out}`);
if (seconds !== null) {
  console.log(`음성 길이 ${seconds.toFixed(2)}초 · 책임면책고시 2초 포함 총 ${(seconds + 2).toFixed(2)}초`);
}
