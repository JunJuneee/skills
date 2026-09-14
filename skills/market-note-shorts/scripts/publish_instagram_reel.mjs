#!/usr/bin/env node
// Instagram 릴스 업로드 — Market Note Shorts
//
// 사용 예:
//   node publish_instagram_reel.mjs --video final.mp4 --caption-file caption.txt
//   node publish_instagram_reel.mjs --video final.mp4 --caption-file caption.txt --dry-run
//
// 토큰은 다음 순서로 찾는다.
//   1) 환경변수 INSTAGRAM_MARKETNOTE_TOKEN 또는 INSTAGRAM_ACCESS_TOKEN
//   2) macOS 키체인 (security find-generic-password -s INSTAGRAM_MARKETNOTE_TOKEN -w)
//   3) 로그인 셸 프로필 (~/.zshrc)
//
// Instagram Login API(graph.instagram.com)의 resumable 업로드를 쓰기 때문에
// 영상을 공개 URL 에 먼저 올릴 필요가 없다.

import {readFile, stat} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';

const API = 'https://graph.instagram.com/v21.0';
const UPLOAD = 'https://rupload.facebook.com/ig-api-upload/v21.0';

function parseArgs(argv) {
  const out = {flags: new Set(), shareToFeed: true};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    switch (key) {
      case 'dry-run':
      case 'help':
      case 'whoami':
        out.flags.add(key);
        break;
      case 'no-share-to-feed': out.shareToFeed = false; break;
      case 'video': out.video = next; i++; break;
      case 'caption-file': out.captionFile = next; i++; break;
      case 'caption': out.caption = next; i++; break;
      default: throw new Error(`알 수 없는 옵션: --${key}`);
    }
  }
  return out;
}

function token() {
  const fromEnv = (process.env.INSTAGRAM_MARKETNOTE_TOKEN ?? process.env.INSTAGRAM_ACCESS_TOKEN)?.trim();
  if (fromEnv) return fromEnv;
  for (const service of ['INSTAGRAM_MARKETNOTE_TOKEN', 'INSTAGRAM_ACCESS_TOKEN']) {
    try {
      const v = execFileSync('security', ['find-generic-password', '-s', service, '-w'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
      if (v) return v;
    } catch { /* 없음 */ }
  }
  try {
    const v = execFileSync('zsh', ['-ic', 'printf %s "${INSTAGRAM_MARKETNOTE_TOKEN:-$INSTAGRAM_ACCESS_TOKEN}"'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
    if (v) return v;
  } catch { /* 없음 */ }
  throw new Error('INSTAGRAM_MARKETNOTE_TOKEN 을 찾을 수 없습니다. 환경변수나 키체인에 저장하세요.');
}

async function api(path, {method = 'GET', params = {}, body} = {}) {
  const url = new URL(`${API}${path}`);
  for (const [k, v] of Object.entries({...params, access_token: token()})) url.searchParams.set(k, v);
  const res = await fetch(url, {method, ...(body ? {body, headers: {'Content-Type': 'application/json'}} : {})});
  const text = await res.text();
  if (!res.ok) throw new Error(`Instagram API 실패 (${res.status}) ${path}: ${text}`);
  return JSON.parse(text);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const HELP = `Instagram 릴스 업로드 (Market Note Shorts)

  --video FILE          업로드할 MP4 (1080x1920 권장)
  --caption-file FILE   캡션 텍스트 파일 (UTF-8)
  --caption TEXT        캡션을 직접 지정
  --no-share-to-feed    피드에는 노출하지 않음 (기본: 피드에도 노출)
  --whoami              연결된 계정만 확인
  --dry-run             업로드 없이 설정과 캡션만 검증
`;

const args = parseArgs(process.argv.slice(2));
if (args.flags.has('help')) { console.log(HELP); process.exit(0); }

const me = await api('/me', {params: {fields: 'id,user_id,username,account_type,media_count'}});
if (args.flags.has('whoami')) {
  console.log(JSON.stringify(me, null, 2));
  process.exit(0);
}

if (!args.video || (!args.captionFile && !args.caption)) {
  console.error('--video 와 --caption-file(또는 --caption) 은 필수입니다.\n');
  console.error(HELP);
  process.exit(1);
}

const caption = (args.caption ?? await readFile(args.captionFile, 'utf8')).trim();
if (caption.length > 2200) throw new Error(`캡션이 2200자를 넘습니다: ${caption.length}자`);

const {size} = await stat(args.video);
const summary = {account: me.username, video: args.video, bytes: size, caption_chars: caption.length, share_to_feed: args.shareToFeed};

if (args.flags.has('dry-run')) {
  console.log('[dry-run]', JSON.stringify(summary, null, 2));
  console.log('\n캡션 미리보기:\n' + caption.split('\n').slice(0, 4).join('\n'));
  process.exit(0);
}

// 1. 컨테이너 생성 (resumable)
const container = await api('/me/media', {
  method: 'POST',
  params: {media_type: 'REELS', upload_type: 'resumable', caption, share_to_feed: String(args.shareToFeed)},
});
console.log('컨테이너 생성:', container.id);

// 2. 파일 바이트 업로드
const bytes = await readFile(args.video);
const uploadRes = await fetch(`${UPLOAD}/${container.id}`, {
  method: 'POST',
  headers: {Authorization: `OAuth ${token()}`, offset: '0', file_size: String(size), 'Content-Type': 'application/octet-stream'},
  body: bytes,
});
const uploadText = await uploadRes.text();
if (!uploadRes.ok) throw new Error(`영상 업로드 실패 (${uploadRes.status}): ${uploadText}`);
console.log('업로드 완료:', uploadText);

// 3. 인코딩 완료 대기
let status = '';
for (let i = 0; i < 60; i++) {
  await sleep(5000);
  const s = await api(`/${container.id}`, {params: {fields: 'status_code,status'}});
  status = s.status_code;
  process.stdout.write(`\r상태: ${status} (${(i + 1) * 5}초)`);
  if (status === 'FINISHED') break;
  if (status === 'ERROR') throw new Error(`인코딩 실패: ${JSON.stringify(s)}`);
}
console.log('');
if (status !== 'FINISHED') throw new Error(`시간 초과. 마지막 상태: ${status}`);

// 4. 발행
const published = await api('/me/media_publish', {method: 'POST', params: {creation_id: container.id}});
const permalink = await api(`/${published.id}`, {params: {fields: 'permalink,media_type,timestamp'}}).catch(() => null);
console.log(JSON.stringify({...summary, media_id: published.id, permalink: permalink?.permalink ?? null}, null, 2));
console.log(`\n발행 완료: ${permalink?.permalink ?? published.id}`);
