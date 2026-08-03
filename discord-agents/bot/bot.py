"""Discord 양방향 봇 (하이브리드)
  - `!분석 <종목>` / `!<종목>` : 빠른 KIS 시세 임베드 (고정 함수)
  - @멘션 + 자유질문         : Codex CLI(codex exec) 풀 실행 → 자연어 응답

보안: ALLOWED_USER_IDS 에 등록된 Discord 계정만 Codex 실행 허용.
      (Codex는 맥에서 명령 실행이 가능하므로 본인만 허용 필수)

설정(secrets.env):
  DISCORD_BOT_TOKEN=...
  ALLOWED_USER_IDS=123456789012345678   # 쉼표로 여러 명 가능. 비우면 ID만 알려주고 차단.
실행:
  ~/claude-agents/.venv/bin/python ~/claude-agents/bot/bot.py
"""
import os, sys, asyncio, traceback
sys.path.insert(0, os.path.dirname(__file__))
import discord
import analyzer

WORK_DIR = "/Users/jun/Desktop"
CODEX_TIMEOUT = 300  # 초

def _load_env():
    path = os.path.join(os.path.dirname(__file__), "..", "secrets.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_env()
CODEX_BIN = os.environ.get("CODEX_BIN", "/opt/homebrew/bin/codex")
CODEX_MODEL = os.environ.get("CODEX_MODEL", "")
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ALLOWED = {x.strip() for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()}

def kem(v): return "🔴" if v >= 0 else "🔵"
def W(n): return f"{int(round(n)):,}"
def pls(n): return f"+₩{W(n)}" if n >= 0 else f"-₩{W(abs(n))}"
def pct(n): return f"+{n:.1f}%" if n >= 0 else f"{n:.1f}%"

def build_embed(a):
    color = 0xE74C3C if a["chg"] >= 0 else 0x3498DB
    e = discord.Embed(title=f"{kem(a['chg'])} {a['name']} ({a['code']})",
                      description=f"종합 판단: **{a['verdict']}**", color=color)
    e.add_field(name="현재가", value=f"💵 ₩{W(a['last'])} ({pct(a['chg'])})", inline=True)
    if a.get("held"):
        e.add_field(name="내 손익", value=f"{kem(a['plpct'])} {pct(a['plpct'])} ({pls(int(a['pl']))})", inline=True)
    e.add_field(name="추세", value=f"{a['align']}\nMA20 {pct(a['vs_ma20'])} · MA50 {pct(a['vs_ma50'])}"
                + (f" · MA200 {pct(a['vs_ma200'])}" if a.get("vs_ma200") is not None else ""), inline=False)
    mom = f"RSI {a['rsi']:.1f}"
    if a.get("vol_ratio"): mom += f" · 거래량 {a['vol_ratio']:.1f}x"
    mom += f" · 52주고점 {pct(a['from_hi'])}"
    e.add_field(name="모멘텀", value=mom, inline=False)
    e.set_footer(text=f"데이터: 한국투자증권 KIS · {a['asof']} · 투자조언 아님")
    return e

async def send_chunks(channel, text):
    text = text.strip() or "(빈 응답)"
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i+1900])

def _codex_args(prompt, stream=False):
    args = [CODEX_BIN, "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "workspace-write"]
    # 현재 사용자 설정의 오래된/로그인 만료 MCP가 자동 실행을 막지 않게 한다.
    args.append("--ignore-user-config")
    if CODEX_MODEL:
        args.extend(["--model", CODEX_MODEL])
    if stream:
        args.append("--json")
    args.append(prompt)
    return args

async def run_codex(prompt):
    proc = await asyncio.create_subprocess_exec(
        *_codex_args(prompt),
        cwd=WORK_DIR, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=CODEX_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return f"⏱️ 시간 초과({CODEX_TIMEOUT}s). 질문을 더 좁혀서 다시 시도해주세요."
    res = out.decode("utf-8", "replace").strip()
    if not res:
        res = "(응답 없음)\n" + err.decode("utf-8", "replace")[-500:]
    return res

def _clean(s):
    # 스포일러(||...||)/마크다운을 깨뜨리는 문자 제거: 백틱, 파이프, 줄바꿈, 별표
    return (str(s or "").replace("`", "").replace("|", "/")
            .replace("\n", " ").replace("*", "").strip())

def _tool_desc(name, inp):
    if name == "Skill":
        sk = _clean(inp.get('skill') or inp.get('command') or '?')
        return f"🧩 스킬 사용: {sk}" + (f" ({_clean(inp.get('args'))})" if inp.get('args') else "")
    if name == "Bash":
        return f"⚙️ Bash: {_clean(inp.get('command',''))[:60]}"
    if name == "Read":
        return f"📖 Read: {_clean(os.path.basename(inp.get('file_path','')))}"
    if name in ("Grep", "Glob"):
        return f"🔎 {name}: {_clean(inp.get('pattern',''))[:40]}"
    if name.startswith("mcp__"):
        return f"🔌 MCP: {_clean(name.split('__',2)[-1])}"
    if name in ("Edit", "Write"):
        return f"✏️ {name}: {_clean(os.path.basename(inp.get('file_path','')))}"
    return f"🛠️ {_clean(name)}"

class ProcessView(discord.ui.View):
    """작업과정 간단/전문 토글 버튼."""
    def __init__(self, summary, detail):
        super().__init__(timeout=None)
        self.summary = summary
        self.detail = detail
        self.expanded = False

    @discord.ui.button(label="전문 보기", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.expanded = not self.expanded
        if self.expanded:
            button.label = "간단히"; button.emoji = "🔼"
            content = self.detail
        else:
            button.label = "전문 보기"; button.emoji = "🔍"
            content = self.summary
        await interaction.response.edit_message(content=content[:1950], view=self)

async def run_codex_stream(thread, prompt):
    """Codex JSONL 실행 과정을 스레드에 갱신하고 최종 답변을 전송한다."""
    import time, json as _json
    proc = await asyncio.create_subprocess_exec(
        *_codex_args(prompt, stream=True),
        cwd=WORK_DIR, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=2**21)
    steps = []; tools = []; final = None
    prog = await thread.send("🧠 시작…")
    last = 0.0
    async def flush(force=False):
        nonlocal last
        now = time.monotonic()
        if not force and now - last < 1.6:
            return
        body = ("🧠 **작업 과정**\n" + "\n".join(steps[-16:])) if steps else "🧠 생각 중…"
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
            if t == "item.completed" and item.get("type") == "agent_message":
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
    # 진행 메시지 최종 정리 (사용 도구/스킬 요약)
    uniq = []
    for x in tools:
        if x and x not in uniq:
            uniq.append(x)
    summary = "🧠 작업 완료 · 사용: " + (", ".join(uniq) if uniq else "없음")
    detail = "🧠 **작업 과정 전문**\n" + "\n".join(steps)
    try:
        await prog.edit(content=summary, view=ProcessView(summary, detail[:1900]))
    except Exception:
        traceback.print_exc()
    if not final:
        out_err = (await proc.stderr.read()).decode("utf-8", "replace")[-400:]
        final = "(최종 응답 없음)\n" + out_err
    await send_chunks(thread, final)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def strip_mention(content, me, bot_roles=()):
    import re
    c = content
    for m in (f"<@{me.id}>", f"<@!{me.id}>"):
        c = c.replace(m, "")
    for role in bot_roles:
        c = c.replace(f"<@&{role.id}>", "")
    c = re.sub(r"<@[&!]?\d+>", "", c)  # 안전망: 남은 멘션 토큰 제거
    return c.strip()

@client.event
async def on_ready():
    print(f"봇 로그인 완료: {client.user} | 허용 ID: {ALLOWED or '(미설정)'}", flush=True)

@client.event
async def on_message(msg):
    if msg.author.bot:
        return
    content = msg.content.strip()
    print(f"[MSG] author_id={msg.author.id} name={msg.author} : {content[:60]}", flush=True)

    # 1) 빠른 경로: !분석 / ! 접두사 → KIS 시세 임베드 (권한 불필요, 읽기 전용)
    if content.startswith("!"):
        q = content[1:].strip()
        if q.startswith("분석"):
            q = q[2:].strip()
        if not q:
            await msg.channel.send("예) `!분석 삼성전자` 또는 `!005930`")
            return
        async with msg.channel.typing():
            try:
                r = await asyncio.to_thread(analyzer.resolve, q)
                if not r:
                    await msg.channel.send(f"`{q}` 종목을 못 찾았어요.")
                    return
                a = await asyncio.to_thread(analyzer.analyze, *r)
                if "err" in a:
                    await msg.channel.send(f"{r[1]} 분석 실패: {a['err']}")
                else:
                    await msg.channel.send(embed=build_embed(a))
            except Exception:
                traceback.print_exc()
                await msg.channel.send("오류가 발생했어요.")
        return

    # 2) 풀 경로: @멘션(사용자 또는 봇 역할) → Codex 실행 (권한 필요)
    bot_roles = set(msg.guild.me.roles) if msg.guild else set()
    role_mentioned = any(r in bot_roles for r in msg.role_mentions)
    if client.user in msg.mentions or role_mentioned:
        prompt = strip_mention(content, client.user, bot_roles)
        if not prompt:
            await msg.channel.send("질문을 함께 보내주세요. 예) `@투자비서 내 포트폴리오에서 위험한 종목 알려줘`")
            return
        uid = str(msg.author.id)
        if uid not in ALLOWED:
            await msg.channel.send(
                f"🔒 권한이 없어요. 보안상 등록된 사용자만 Codex 실행이 가능합니다.\n"
                f"당신의 Discord ID: `{uid}`\n"
                f"→ `~/claude-agents/secrets.env` 의 `ALLOWED_USER_IDS` 에 이 ID를 넣고 봇을 재시작하세요.")
            return
        # 멘션 메시지 하위에 스레드 생성 후, 그 안에서 답변
        # 이미 스레드/DM 등이면 그대로, 일반 텍스트채널이면 메시지 하위에 스레드 생성
        if isinstance(msg.channel, discord.Thread):
            thread = msg.channel
        else:
            try:
                thread = await msg.create_thread(name=(prompt[:90] or "분석"))
            except Exception:
                traceback.print_exc()
                thread = msg.channel  # 스레드 생성 실패 시 채널로 폴백
        try:
            await run_codex_stream(thread, prompt)
        except Exception:
            traceback.print_exc()
            await thread.send("Codex 실행 중 오류가 발생했어요. 로그를 확인해주세요.")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN 미설정", flush=True); sys.exit(1)
    client.run(TOKEN)
