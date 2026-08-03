"""앱인토스 스쿼드 — 역할 봇 (단일 프로그램, ROLE 환경변수로 4회 기동).

각 인스턴스(PO/Designer/Frontend/Backend)는 독립 Discord 봇 계정으로 로그인하여:
  • 자기 전용 채널(#<role>) — 작업/의사결정 로그를 남김
  • #squad — 멘션받으면 깨어나 토론/핸드오버 (양방향 자율 토론)

트리거 규칙(가드):
  • 본인 메시지 무시 / 멘션 안 된 메시지 무시
  • 사람 트리거: ALLOWED_USER_IDS 만 허용
  • 봇 트리거: 레지스트리에 등록된 스쿼드 봇만 허용
  • #squad 연속 봇-턴이 MAX_BOT_TURNS 초과하면 정지 + "사람 결정 필요"

기동:
  ROLE=po   ~/claude-agents/.venv/bin/python ~/claude-agents/squad/role_bot.py
  (designer / frontend / backend 동일)

secrets.env 필요 키:
  PO_BOT_TOKEN / DESIGNER_BOT_TOKEN / FRONTEND_BOT_TOKEN / BACKEND_BOT_TOKEN
  CH_PO / CH_DESIGNER / CH_FRONTEND / CH_BACKEND / CH_SQUAD
  ALLOWED_USER_IDS (사람 트리거 허용 ID)
"""
import os, sys, asyncio, traceback, tempfile, shutil, json, time, re
sys.path.insert(0, os.path.dirname(__file__))
import discord
import squad_rules as R

CODEX_BIN = os.environ.get("CODEX_BIN", "/opt/homebrew/bin/codex")
APP_DIR = "/Users/jun/Desktop/github"               # Codex 작업 디렉토리(모든 봇의 공용 작업 공간)
PROMPTS = os.path.join(os.path.dirname(__file__), "prompts")
# 모든 Discord 봇의 작업 루트(APP_DIR) 안에 둬서 Codex 세션이 같은 경로로 읽고 관리한다.
SKILLS_ROOT = os.environ.get("SQUAD_SKILLS_ROOT", "/Users/jun/Desktop/github/skills/skills")
# 사용자 대면 응답 한도가 아니라, 백그라운드 작업의 좀비 프로세스 방지용 안전망.
# 봇은 더 이상 응답을 동기 대기하지 않으므로(접수 즉시 리턴) 이 값이 길어도 Discord는 막히지 않는다.
CODEX_TIMEOUT = int(os.environ.get("SQUAD_CODEX_TIMEOUT", "1800"))
MODEL = os.environ.get("SQUAD_CODEX_MODEL", "")
CONTEXT_MSGS = 12          # claude에 넘길 최근 대화 맥락 수
PERSONA = {"po": "스티브", "designer": "디터", "frontend": "댄", "backend": "마틴", "qa": "켄트", "blog": "에디터 조앤"}
ACK_EMOJI = os.environ.get("SQUAD_ACK_EMOJI", "👀")    # 접수
DONE_EMOJI = os.environ.get("SQUAD_DONE_EMOJI", "✅")  # 완료
FAIL_EMOJI = "⚠️"                                       # 실패
# 한 봇이 동시에 돌리는 claude 작업 수 제한(기본 1 = 접수는 즉시, 처리는 순차).
_claude_sem = asyncio.Semaphore(int(os.environ.get("SQUAD_CONCURRENCY", "1")))


def _load_env():
    # 비밀값은 Git 저장소에 넣지 않고 기존 보호 파일 또는 환경변수 경로에서만 읽는다.
    path = os.environ.get("CLAUDE_AGENTS_SECRETS_PATH", "/Users/jun/claude-agents/secrets.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

ROLE = (os.environ.get("ROLE") or "").strip().lower()
if ROLE not in R.ROLES:
    print(f"ERROR: ROLE 환경변수가 {R.ROLES} 중 하나여야 합니다 (현재: {ROLE!r})", flush=True)
    sys.exit(1)

RUNTIME_STATE_DIR = os.environ.get("SQUAD_STATE_DIR", "/Users/jun/Library/Application Support/JunClaudeAgents/squad")
PENDING_TASKS_PATH = os.path.join(RUNTIME_STATE_DIR, f"pending-{ROLE}.json")
CODEX_SESSIONS_PATH = os.path.join(RUNTIME_STATE_DIR, f"codex-sessions-{ROLE}.json")
_resume_started = False

TOKEN_ENV = {"blog": "WRITER_BOT_TOKEN"}.get(ROLE, f"{ROLE.upper()}_BOT_TOKEN")
TOKEN = os.environ.get(TOKEN_ENV, "")
OWN_CH = os.environ.get(f"CH_{ROLE.upper()}", "")
SQUAD_CH = os.environ.get("CH_SQUAD", "")
ALLOWED = {x.strip() for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()}
try:
    OWN_CH_ID = int(OWN_CH) if OWN_CH else 0
    SQUAD_CH_ID = int(SQUAD_CH) if SQUAD_CH else 0
except ValueError:
    OWN_CH_ID = SQUAD_CH_ID = 0


def _read(p):
    try:
        return open(os.path.join(PROMPTS, p), encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def _load_pending_tasks():
    try:
        data = json.loads(open(PENDING_TASKS_PATH, encoding="utf-8").read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pending_tasks(tasks):
    os.makedirs(os.path.dirname(PENDING_TASKS_PATH), exist_ok=True)
    temporary = f"{PENDING_TASKS_PATH}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False)
    os.replace(temporary, PENDING_TASKS_PATH)


def _queue_task(msg, in_squad):
    """재시작 뒤에도 원 요청을 다시 가져올 수 있도록 메시지 참조만 저장한다."""
    tasks = _load_pending_tasks()
    message_id = str(msg.id)
    if any(task.get("message_id") == message_id for task in tasks):
        return
    tasks.append({
        "message_id": message_id,
        "channel_id": str(msg.channel.id),
        "in_squad": bool(in_squad),
        "queued_at": int(time.time()),
    })
    _write_pending_tasks(tasks)


def _complete_task(msg):
    tasks = _load_pending_tasks()
    remaining = [task for task in tasks if task.get("message_id") != str(msg.id)]
    if len(remaining) != len(tasks):
        _write_pending_tasks(remaining)


def _load_codex_sessions():
    try:
        data = json.loads(open(CODEX_SESSIONS_PATH, encoding="utf-8").read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_codex_sessions(sessions):
    os.makedirs(os.path.dirname(CODEX_SESSIONS_PATH), exist_ok=True)
    temporary = f"{CODEX_SESSIONS_PATH}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False)
    os.replace(temporary, CODEX_SESSIONS_PATH)


def _session_for(conversation_key):
    return _load_codex_sessions().get(conversation_key, {}).get("thread_id")


def _save_session(conversation_key, thread_id):
    if not thread_id:
        return
    sessions = _load_codex_sessions()
    sessions[conversation_key] = {"thread_id": thread_id, "updated_at": int(time.time())}
    _write_codex_sessions(sessions)


def _is_skill_edit_request(text):
    """resume은 --add-dir를 지원하지 않아, 스킬 수정만 새 쓰기 세션으로 실행한다."""
    text = (text or "").lower()
    skill_terms = ("skill", "스킬", "skill.md", "페르소나", "역할 정의")
    edit_terms = ("수정", "변경", "추가", "삭제", "업데이트", "고쳐", "바꿔")
    return any(term in text for term in skill_terms) and any(term in text for term in edit_terms)


def _apply_skill_update(reply):
    """Codex가 제안한 내용만 현재 역할의 SKILL.md 한 파일에 안전하게 반영한다."""
    match = re.search(r"<skill_update>\s*(.*?)\s*</skill_update>", reply or "", re.DOTALL | re.IGNORECASE)
    if not match:
        return False, reply
    content = match.group(1).strip()
    required_name = f"name: squad-{ROLE}"
    if not content.startswith("---") or required_name not in content or len(content) > 100_000:
        return False, reply + "\n\n⚠️ 스킬 형식 검증에 실패해 반영하지 않았습니다."
    path = os.path.join(SKILLS_ROOT, f"squad-{ROLE}", "SKILL.md")
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(content + "\n")
        os.replace(temporary, path)
    except Exception as exc:
        return False, reply + f"\n\n⚠️ 스킬 파일 반영 실패: {exc}"
    visible_reply = (reply[:match.start()] + reply[match.end():]).strip()
    return True, (visible_reply + "\n\n✅ 라이브 스킬을 반영했습니다. 다음 요청부터 적용됩니다.").strip()


COMMON_PROMPT = "blog_common.md" if ROLE == "blog" else "_common.md"


def _current_system_prompt():
    """스킬 파일을 매 요청마다 다시 읽는다. 재시작 없이 다음 요청에 수정이 반영된다."""
    skill_path = os.path.join(SKILLS_ROOT, f"squad-{ROLE}", "SKILL.md")
    try:
        role_skill = open(skill_path, encoding="utf-8").read()
    except FileNotFoundError:
        role_skill = f"# {ROLE} 역할 스킬\n역할별 스킬 파일이 없습니다: {skill_path}"
    return (
        _read(COMMON_PROMPT)
        + "\n\n---\n\n"
        + "## 현재 역할의 라이브 스킬\n"
        + f"경로: `{skill_path}`\n"
        + "아래 내용이 이 역할의 최신 업무 정의입니다. 반드시 따르세요. "
          "사용자가 역할·업무 방식·페르소나 수정을 명시적으로 요청한 경우에만 이 파일을 직접 수정할 수 있으며, "
          "수정은 다음 요청부터 자동 반영됩니다. 다른 역할의 스킬은 수정하지 마세요.\n\n"
        + role_skill
    )

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def _codex_args(prompt, image_paths=(), session_id=None):
    # Playwright는 브라우저 프로세스·캐시 디렉터리 접근이 필요하다.
    # QA 역할에 한해 E2E를 실행할 수 있도록 Codex 샌드박스를 확장한다.
    sandbox = "danger-full-access" if ROLE == "qa" else "workspace-write"
    if session_id:
        # 새 세션을 만들지 않고 같은 Discord 대화의 Codex 대화를 이어 간다.
        # sandbox·작업 폴더는 최초 세션 생성 시의 설정을 그대로 사용한다.
        args = [CODEX_BIN, "exec", "resume", "--skip-git-repo-check",
                "--ignore-user-config", "--json"]
    else:
        args = [CODEX_BIN, "exec", "--skip-git-repo-check",
                "--cd", APP_DIR, "--sandbox", sandbox,
                "--ignore-user-config", "--json"]
        if sandbox == "workspace-write":
            args.extend(["-c", "sandbox_workspace_write.network_access=true"])
            # 역할별 라이브 스킬은 APP_DIR 밖에 있으므로, 이 디렉터리만 추가 쓰기 허용한다.
            args.extend(["--add-dir", SKILLS_ROOT])
    if MODEL:
        args.extend(["--model", MODEL])
    for image_path in image_paths:
        args.extend(["--image", image_path])
    # --image가 여러 값을 받으므로, -- 뒤의 프롬프트를 이미지 경로로 오인하지 않게 구분한다.
    if session_id:
        args.append(session_id)
    return [*args, "--", prompt]


def _clean(s):
    """스포일러/마크다운 깨짐 방지: 백틱·파이프·줄바꿈·별표 제거."""
    return (str(s or "").replace("`", "").replace("|", "/")
            .replace("\n", " ").replace("*", "").strip())


def _tool_desc(name, inp):
    """tool_use 이벤트를 사람이 읽는 한 줄로(작업과정 로그용)."""
    if name == "WebSearch":
        return f"🔍 웹검색: {_clean(inp.get('query', ''))[:70]}"
    if name == "WebFetch":
        return f"🌐 웹읽기: {_clean(inp.get('url', ''))[:70]}"
    if name == "Skill":
        sk = _clean(inp.get('skill') or inp.get('command') or '?')
        return f"🧩 스킬: {sk}" + (f" ({_clean(inp.get('args'))})" if inp.get('args') else "")
    if name == "Bash":
        return f"⚙️ Bash: {_clean(inp.get('command', ''))[:60]}"
    if name == "Read":
        return f"📖 Read: {_clean(os.path.basename(inp.get('file_path', '')))}"
    if name in ("Grep", "Glob"):
        return f"🔎 {name}: {_clean(inp.get('pattern', ''))[:40]}"
    if name in ("Edit", "Write"):
        return f"✏️ {name}: {_clean(os.path.basename(inp.get('file_path', '')))}"
    if name.startswith("mcp__"):
        return f"🔌 MCP: {_clean(name.split('__', 2)[-1])}"
    return f"🛠️ {_clean(name)}"


class ProcessView(discord.ui.View):
    """작업과정 간단/전문 토글 버튼."""
    def __init__(self, summary, detail):
        super().__init__(timeout=None)
        self.summary = summary
        self.detail = detail
        self.expanded = False

    @discord.ui.button(label="전문 보기", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def toggle(self, interaction, button):
        self.expanded = not self.expanded
        if self.expanded:
            button.label = "간단히"; button.emoji = "🔼"; content = self.detail
        else:
            button.label = "전문 보기"; button.emoji = "🔍"; content = self.summary
        await interaction.response.edit_message(content=content[:1950], view=self)


async def run_claude_stream(log_ch, prompt, header, reply_to=None, image_paths=(), session_id=None):
    """claude를 stream-json으로 실행 → 진행 과정(tool_use/thinking)을 log_ch(개인 채널 #<role>)에
    실시간 갱신으로 기록하고, 최종 result 텍스트를 반환한다. log_ch=None이면 과정 로그 생략."""
    import json as _json
    proc = await asyncio.create_subprocess_exec(
        *_codex_args(prompt, image_paths, session_id),
        cwd=APP_DIR,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=2 ** 21)
    steps = []; tools = []; final = None
    active_session_id = session_id
    prog = None
    if log_ch:
        try:
            prog = await log_ch.send(f"{header}\n🧠 시작…",
                                     allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            traceback.print_exc()
    elif reply_to:
        try:
            prog = await reply_to.reply(
                f"{header}\n🧠 시작…", mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            traceback.print_exc()
    last = 0.0

    async def flush(force=False):
        nonlocal last
        if not prog:
            return
        now = asyncio.get_running_loop().time()
        if not force and now - last < 1.6:
            return
        body = (f"{header}\n🧠 **작업 과정**\n" + "\n".join(steps[-16:])) if steps else f"{header}\n🧠 생각 중…"
        try:
            await prog.edit(content=body[:1950])
        except Exception:
            pass
        last = now

    try:
        while True:
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=CODEX_TIMEOUT)
            except asyncio.TimeoutError:
                steps.append("⏱️ 시간 초과"); break
            if not raw:
                break
            try:
                e = _json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                continue
            t = e.get("type")
            item = e.get("item", {})
            if t == "thread.started":
                active_session_id = e.get("thread_id") or active_session_id
            elif t == "item.completed" and item.get("type") == "agent_message":
                final = item.get("text")
            elif t == "item.completed" and item.get("type") == "command_execution":
                tools.append("command")
                steps.append("⚙️ 명령 실행: " + _clean(item.get("command", ""))[:60])
                await flush()
            elif t == "turn.failed":
                steps.append("⚠️ Codex 실행 실패")
    except Exception:
        traceback.print_exc()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        proc.kill()
    # 진행 메시지 최종 정리(사용 도구 요약 + 전문 토글)
    uniq = []
    for x in tools:
        if x and x not in uniq:
            uniq.append(x)
    if prog:
        summary = f"{header}\n✅ 작업 완료 · 사용: " + (", ".join(uniq) if uniq else "없음")
        detail = "🧠 **작업 과정 전문**\n" + "\n".join(steps)
        try:
            await prog.edit(content=summary[:1950], view=ProcessView(summary[:1950], detail[:1900]))
        except Exception:
            traceback.print_exc()
    if not final:
        err = (await proc.stderr.read()).decode("utf-8", "replace")[-400:]
        final = "(최종 응답 없음)\n" + err
    return final, active_session_id


async def send_chunks(channel, text, am=None):
    text = (text or "").strip() or "(빈 응답)"
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900], allowed_mentions=am)


async def reply_chunks(msg, text, am=None):
    """블로그 봇은 요청 메시지에 직접 답글로 결과를 남긴다."""
    text = (text or "").strip() or "(빈 응답)"
    for i in range(0, len(text), 1900):
        await msg.reply(text[i:i + 1900], mention_author=False, allowed_mentions=am)


def watched(channel):
    """이 봇이 들어야 하는 채널인가? 감시 채널(자기채널/squad) 또는 그 채널의 쓰레드면 True.
    Returns: (watched: bool, is_squad: bool). 쓰레드면 parent 기준으로 판정."""
    cid = channel.id
    parent = getattr(channel, "parent_id", None)
    if cid == SQUAD_CH_ID or parent == SQUAD_CH_ID:
        return True, True
    if cid == OWN_CH_ID or parent == OWN_CH_ID:
        return True, False
    return False, False


async def gather_context(channel, limit=CONTEXT_MSGS):
    lines = []
    async for m in channel.history(limit=limit):
        who = m.author.display_name
        body = (m.content or "").replace("\n", " ").strip()
        if body:
            lines.append(f"{who}: {body}")
    lines.reverse()
    return "\n".join(lines)


def strip_self_mention(content):
    import re
    c = content.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "")
    return re.sub(r"<@[&!]?\d+>", "", c).strip()


async def _swap_reaction(msg, frm, to):
    """접수 이모지(frm)를 완료/실패 이모지(to)로 교체. 실패해도 조용히 무시."""
    try:
        await msg.remove_reaction(frm, client.user)
    except Exception:
        pass
    try:
        await msg.add_reaction(to)
    except Exception:
        pass


async def _download_image_attachments(msg):
    """Discord 이미지 첨부를 Codex 이미지 입력용 임시 파일로 안전하게 내려받는다."""
    images = []
    for attachment in msg.attachments[:10]:
        content_type = (attachment.content_type or "").lower()
        if not (content_type.startswith("image/") or attachment.width is not None):
            continue
        if attachment.size > 10 * 1024 * 1024:
            print(f"[{ROLE}] 첨부 이미지 건너뜀(10MB 초과): {attachment.filename}", flush=True)
            continue
        images.append(attachment)
    if not images:
        return None, []

    temp_dir = tempfile.mkdtemp(prefix="discord-codex-images-")
    paths = []
    try:
        for index, attachment in enumerate(images, start=1):
            name = os.path.basename(attachment.filename) or f"image-{index}.png"
            path = os.path.join(temp_dir, f"{index}-{name}")
            await attachment.save(path, use_cached=True)
            paths.append(path)
            print(f"[{ROLE}] 첨부 이미지 전달 준비: {name}", flush=True)
        return temp_dir, paths
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def _answer_target(msg):
    """최종 답변을 남길 곳: 멘션이 쓰레드 안이면 그 쓰레드, 채널이면 그 메시지에 쓰레드를 만든다."""
    ch = msg.channel
    if isinstance(ch, discord.Thread):
        return ch
    existing = getattr(msg, "thread", None)
    if existing:
        return existing
    try:
        return await msg.create_thread(name=(strip_self_mention(msg.content)[:90] or "답변"),
                                       auto_archive_duration=1440)
    except Exception:
        traceback.print_exc()
        return ch


async def _conversation_key(msg, answer_target=None):
    """Discord 스레드(블로그는 답글의 원 메시지)마다 Codex 세션을 분리한다."""
    channel = answer_target or msg.channel
    if isinstance(channel, discord.Thread):
        return f"thread:{channel.id}"
    if ROLE != "blog":
        return f"message:{msg.id}"

    root = msg
    seen = {msg.id}
    while getattr(root, "reference", None) and root.reference.message_id:
        ref_id = root.reference.message_id
        if ref_id in seen:
            break
        seen.add(ref_id)
        try:
            resolved = root.reference.resolved
            root = resolved if isinstance(resolved, discord.Message) else await msg.channel.fetch_message(ref_id)
        except Exception:
            break
    return f"message:{root.id}"


async def handle_request(msg, in_squad, resumed=False):
    """접수 후 백그라운드 처리(연결 안 붙잡음). 역할 분리:
      • 작업 과정(tool_use/websearch/thinking) → 개인 채널 #<role> 에 실시간 기록
      • 최종 답변 → 내가 멘션한 쓰레드 에만
    끝나면 원 메시지 이모지를 완료(✅)/실패(⚠️)로 교체한다."""
    ask = strip_self_mention(msg.content)
    where = "#squad" if in_squad else f"#{ROLE}"
    who = msg.author.display_name
    title = (ask or "응답").replace("\n", " ").strip()[:80] or "응답"
    persona = PERSONA.get(ROLE, ROLE)
    ok = False
    handled = False
    attachment_dir = None
    try:
        async with _claude_sem:          # 한 봇은 한 번에 한 작업씩(접수는 즉시, 처리는 순차)
            # 일반 역할은 첫 요청부터 전용 스레드를 만들고, 그 스레드에 Codex 세션을 묶는다.
            # 블로그는 Discord 답글 체인을 같은 대화로 묶는다.
            target = None if ROLE == "blog" else await _answer_target(msg)
            conversation_key = await _conversation_key(msg, target)
            previous_session_id = _session_for(conversation_key)
            skill_edit = _is_skill_edit_request(ask)
            # 스킬 편집은 Codex가 내용만 생성하고, 이 봇이 자기 SKILL.md에만 반영한다.
            # 따라서 resume 세션의 맥락과 제한 권한을 그대로 유지할 수 있다.
            session_id = previous_session_id
            context = await gather_context(msg.channel)
            attachment_dir, image_paths = await _download_image_attachments(msg)
            attachment_note = ""
            if image_paths:
                attachment_note = (
                    f"\n\n## 첨부 참고 이미지\n"
                    f"사용자가 이미지 {len(image_paths)}개를 첨부했습니다. Codex 이미지 입력으로 전달됐으니 "
                    "반드시 이미지를 직접 확인하고 요청에 반영하세요."
                )
            skill_edit_instruction = ""
            if skill_edit:
                skill_edit_instruction = (
                    "\n\n## 라이브 스킬 수정 전용 절차\n"
                    f"사용자가 당신의 역할 스킬 수정을 요청했습니다. 직접 파일 쓰기를 시도하지 마세요. "
                    f"대신 `{os.path.join(SKILLS_ROOT, f'squad-{ROLE}', 'SKILL.md')}`의 완성된 전체 내용을 "
                    "반드시 아래 태그만으로 감싸 최종 답변에 포함하세요. 봇이 그 내용만 검증해 해당 한 파일에 반영합니다.\n"
                    "<skill_update>\n---\nname: squad-역할명\ndescription: ...\n---\n...\n</skill_update>\n"
                    "기존 유효한 YAML frontmatter의 `name: squad-현재역할`을 유지하세요."
                )
            prompt = (
                f"{_current_system_prompt()}\n\n"
                f"## 현재 위치: {where} 채널\n"
                f"## 최근 대화 맥락\n{context}\n\n"
                f"## 방금 당신({ROLE})에게 온 메시지 (보낸이: {who})\n{ask}\n\n"
                f"위 맥락에서 {ROLE} 역할로 응답하세요. 다른 역할에 넘길 때는 @po/@designer/"
                f"@frontend/@backend/@blog 형식으로 멘션하세요. 역할 지침에 산출물 저장 경로가 있으면 파일로 남기세요."
                f"{attachment_note}{skill_edit_instruction}"
            )
            # 기존 스쿼드는 개인 채널에 기록한다. 조앤은 요청 메시지 아래 답글을 실시간 갱신한다.
            is_blog = ROLE == "blog"
            log_ch = None if is_blog else (client.get_channel(OWN_CH_ID) if OWN_CH_ID else None)
            restart_note = " · 🔄 재시작 후 자동 재개" if resumed else ""
            log_header = f"🧩 **{persona}**({ROLE.upper()}) · {where} 요청 · {title} (by {who}){restart_note}"
            reply, active_session_id = await run_claude_stream(
                log_ch, prompt, log_header, reply_to=msg if is_blog else None,
                image_paths=image_paths, session_id=session_id,
            )
            _save_session(conversation_key, active_session_id)
            if skill_edit:
                _, reply = _apply_skill_update(reply)
        reply = R.mentionify(reply)
        # 블로그 봇은 요청 메시지에 답글로, 기존 스쿼드 봇은 작업 스레드에 결과를 남긴다.
        if ROLE == "blog":
            await reply_chunks(msg, reply)
        else:
            await send_chunks(target, reply)
        ok = True
        handled = True
    except asyncio.CancelledError:
        # 재시작으로 취소된 작업은 pending 파일에 남겨 다음 기동 시 재개한다.
        raise
    except Exception:
        traceback.print_exc()
        try:
            await msg.channel.send("⚠️ 실행 중 오류가 발생했어요. 로그를 확인해주세요.")
        except Exception:
            pass
        handled = True
    finally:
        if attachment_dir:
            shutil.rmtree(attachment_dir, ignore_errors=True)
        if handled:
            _complete_task(msg)
        await _swap_reaction(msg, ACK_EMOJI, DONE_EMOJI if ok else FAIL_EMOJI)


async def resume_pending_tasks():
    """봇 재기동 전에 접수된 미완료 요청을 원본 Discord 메시지에서 다시 불러와 재개한다."""
    tasks = _load_pending_tasks()
    if not tasks:
        return
    print(f"[{ROLE}] 재개 대기 작업: {len(tasks)}건", flush=True)
    for task in tasks:
        try:
            channel_id = int(task["channel_id"])
            message_id = int(task["message_id"])
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            try:
                await msg.add_reaction("🔄")
            except Exception:
                pass
            asyncio.create_task(handle_request(msg, bool(task.get("in_squad")), resumed=True))
        except discord.NotFound:
            # 원문이 삭제된 경우에는 더 이상 재개할 수 없다.
            remaining = [item for item in _load_pending_tasks()
                         if item.get("message_id") != task.get("message_id")]
            _write_pending_tasks(remaining)
        except Exception:
            traceback.print_exc()


@client.event
async def on_ready():
    global _resume_started
    R.register(ROLE, client.user.id)
    print(f"[{ROLE}] 로그인: {client.user} (id={client.user.id}) | own={OWN_CH_ID} squad={SQUAD_CH_ID}", flush=True)
    if OWN_CH_ID:
        ch = client.get_channel(OWN_CH_ID)
        if ch:
            try:
                await ch.send(f"🤖 **{ROLE.upper()}** 봇 가동. 멘션하면 #squad/이 채널에서 응답합니다.")
            except Exception:
                traceback.print_exc()
    if not _resume_started:
        _resume_started = True
        asyncio.create_task(resume_pending_tasks())


@client.event
async def on_message(msg):
    # 본인 메시지 무시
    if msg.author.id == client.user.id:
        return
    # 관심 채널만 (자기 전용 채널 / squad / 그 채널들의 쓰레드)
    is_watched, in_squad = watched(msg.channel)
    if not is_watched:
        return

    if ROLE == "blog":
        print(f"[blog] 수신: channel={msg.channel.id} author={msg.author.id} mentioned={client.user in msg.mentions}", flush=True)

    is_human = not msg.author.bot

    # 사람이 squad에 말하면 봇-턴 카운터 리셋(가드 해제)
    if in_squad and is_human:
        R.clear_stop()

    # 이 봇이 멘션됐을 때만 반응 (유저 멘션 또는 이 봇의 역할(managed role) 멘션)
    bot_roles = set(msg.guild.me.roles) if msg.guild else set()
    role_hit = any(r in bot_roles for r in msg.role_mentions)
    if client.user not in msg.mentions and not role_hit:
        return

    # 트리거 권한: 사람=ALLOWED, 봇=레지스트리 등록된 스쿼드 봇만
    if is_human:
        if str(msg.author.id) not in ALLOWED:
            await msg.channel.send(
                f"🔒 등록된 사용자만 트리거할 수 있어요. 당신의 ID: `{msg.author.id}`")
            return
    else:
        if str(msg.author.id) not in R.known_bot_ids():
            return  # 외부/미등록 봇 무시

    # #squad 자율토론 루프 가드
    if in_squad and not is_human:
        history = [m async for m in msg.channel.history(limit=R.HISTORY_FETCH)]
        history.reverse()
        if R.should_stop(history):
            if R.mark_stopped_once():
                owner = R.owner_id()
                tag = f"<@{owner}> " if owner else ""
                await msg.channel.send(
                    f"🛑 {tag}**confirm 필요**\n"
                    "• **[무엇을 확인?]** 스쿼드의 자동 논의 한도에 도달해 다음 진행 방향을 사람이 결정해야 합니다.\n"
                    "• **[선택지]** A. 현재까지의 합의·산출물을 기준으로 계속 진행 / B. 방향을 수정하거나 작업을 중단\n"
                    "• **[추천]** A — 기존 합의에 명백한 오류가 없다면 작업 맥락을 유지할 수 있습니다.\n"
                    "• **[confirm 후]** 확정된 방향만 기준으로 다음 담당 봇이 작업을 재개합니다.")
            return

    # 접수 즉시 확인 이모지만 달고, 실제 작업은 백그라운드로 떠나보낸다.
    # → Discord 핸들러는 곧바로 리턴하므로 claude 작업이 길어도 연결을 붙잡지 않는다(300초 timeout 해소).
    _queue_task(msg, in_squad)
    try:
        await msg.add_reaction(ACK_EMOJI)
    except Exception:
        traceback.print_exc()
    asyncio.create_task(handle_request(msg, in_squad))


if __name__ == "__main__":
    if not TOKEN:
        print(f"ERROR: {TOKEN_ENV} 미설정 (secrets.env 확인)", flush=True)
        sys.exit(1)
    client.run(TOKEN)
