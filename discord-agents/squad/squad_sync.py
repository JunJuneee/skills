#!/usr/bin/env python3
"""squad_sync — Discord 스쿼드 작업물 → Linear + GitHub 자동 연동 (중앙 watcher).

흐름:
  봇(claude -p, MCP off)이 작업 끝에 handoff JSON 한 개를 떨군다:
      <repo>/.squad/handoff/<id>.json
  이 스크립트(launchd 상주 또는 --once)가 그걸 주워서:
    ① GitHub: 변경 파일을 격리 worktree에서 JAY-N 브랜치로 커밋 → push → PR 오픈/갱신
                (PR 제목/본문에 JAY-N 포함 → Linear 네이티브 연동이 이슈 자동 링크)
    ② Linear: 이슈 상태 변경(In Progress/Done) + 작업 요약 코멘트(+PR 링크).
                (handoff.doc 가 있으면 repo 파일 내용을 Linear 문서로 upsert)
    ③ Discord: #squad 에 "JAY-N → PR #x / Linear 갱신" 알림.
  처리 끝난 handoff 는 .squad/handoff/done/ 으로 이동.

봇은 MCP 를 못 쓰므로(헤드리스 hang 방지) Linear/GitHub 접근을 전부 이 스크립트가 대행한다.

handoff JSON 스키마:
  {
    "role":   "backend",                       # po|designer|frontend|backend|qa (필수)
    "issue":  "JAY-8",                          # 있으면 그 이슈에 연동. 없고 title 있으면 새 이슈 생성
    "title":  "게임 상태 API",                  # issue 없을 때 새 이슈 제목
    "summary":"GET /game/state 구현 ...",       # Linear 코멘트 본문 (필수)
    "status": "done",                           # in_progress|done  (Linear 상태 매핑)
    "files":  ["server/src/game.ts"],           # 있으면 GitHub 커밋/PR (없으면 Linear/Discord만)
    "doc":    {"title":"API 스펙","path":"docs/api.md"}   # 선택: 파일→Linear 문서 upsert
  }

CLI:
  python squad_sync.py --once          # 대기 중인 handoff 1회 처리
  python squad_sync.py --watch [--interval 60]   # 상주 폴링
  python squad_sync.py --emit --role backend --issue JAY-8 \
         --summary "..." --status done --file server/src/game.ts   # 봇/테스트용 handoff 생성
  python squad_sync.py --selftest      # Linear 연결만 확인
"""
import os, sys, json, time, subprocess, argparse, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
SECRETS_BASE = Path(os.environ.get("CLAUDE_AGENTS_SECRETS_ROOT", "/Users/jun/claude-agents"))
REPO = Path(os.environ.get("SQUAD_APP_DIR", "/Users/jun/Desktop/toss-miniapp"))
HANDOFF_DIR = REPO / ".squad" / "handoff"
DONE_DIR = HANDOFF_DIR / "done"
LINEAR_API = "https://api.linear.app/graphql"
TEAM_KEY = os.environ.get("SQUAD_LINEAR_TEAM", "JAY")
PROJECT_NAME = os.environ.get("SQUAD_LINEAR_PROJECT", "조선 상인 키우기 (앱인토스 미니앱)")

# 역할 → Linear 라벨 (이슈 신규 생성 시)
ROLE_LABEL = {"frontend": "frontend", "backend": "backend",
              "designer": "design", "po": None, "qa": None}
# handoff status → Linear 상태명
STATUS_STATE = {"in_progress": "In Progress", "todo": "Todo", "done": "Done"}

sys.path.insert(0, str(BASE / "lib"))
try:
    import bot_send  # secrets.env 자동 로드 + Discord 전송
except Exception:
    bot_send = None


def _load_env():
    """bot_send 가 이미 로드하지만, 단독 실행 대비 한 번 더."""
    for path in (SECRETS_BASE / "secrets.env", SECRETS_BASE / "config.sh"):
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
LINEAR_KEY = os.environ.get("LINEAR_API_KEY", "")
SQUAD_CH = os.environ.get("CH_SQUAD", "") or os.environ.get("DISCORD_CHANNEL_ID", "")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ───────────────────────── Linear (GraphQL) ─────────────────────────
def linear(query, variables=None):
    if not LINEAR_KEY:
        raise RuntimeError("LINEAR_API_KEY 미설정")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(LINEAR_API, data=body, method="POST",
                                 headers={"Authorization": LINEAR_KEY,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Linear HTTP {e.code}: {e.read().decode()[:200]}")
    if out.get("errors"):
        raise RuntimeError(f"Linear GraphQL error: {json.dumps(out['errors'])[:300]}")
    return out["data"]


_cache = {}


def team_id():
    if "team" not in _cache:
        d = linear('query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}', {"k": TEAM_KEY})
        nodes = d["teams"]["nodes"]
        _cache["team"] = nodes[0]["id"] if nodes else None
    return _cache["team"]


def state_id(name):
    key = f"state:{name}"
    if key not in _cache:
        d = linear('query($t:ID!){workflowStates(filter:{team:{id:{eq:$t}}}){nodes{id name}}}',
                   {"t": team_id()})
        for n in d["workflowStates"]["nodes"]:
            _cache[f"state:{n['name']}"] = n["id"]
    return _cache.get(key)


def get_issue(identifier):
    """JAY-8 형태 식별자 → {id, identifier, branchName, state} 또는 None."""
    num = identifier.split("-")[-1]
    d = linear('''query($t:ID!,$n:Float!){issues(filter:{team:{id:{eq:$t}},number:{eq:$n}}){
                    nodes{id identifier branchName state{name}}}}''',
               {"t": team_id(), "n": float(num)})
    nodes = d["issues"]["nodes"]
    return nodes[0] if nodes else None


def project_id():
    if "project" not in _cache:
        d = linear('query($q:String!){projects(filter:{name:{eq:$q}}){nodes{id}}}', {"q": PROJECT_NAME})
        nodes = d["projects"]["nodes"]
        _cache["project"] = nodes[0]["id"] if nodes else None
    return _cache["project"]


def create_issue(title, summary, role):
    inp = {"teamId": team_id(), "title": title, "description": summary}
    if project_id():
        inp["projectId"] = project_id()
    d = linear('''mutation($i:IssueCreateInput!){issueCreate(input:$i){
                    success issue{id identifier branchName}}}''', {"i": inp})
    return d["issueCreate"]["issue"]


def update_issue_state(issue_id, status):
    name = STATUS_STATE.get(status)
    sid = state_id(name) if name else None
    if not sid:
        return
    linear('mutation($id:String!,$s:String!){issueUpdate(id:$id,input:{stateId:$s}){success}}',
           {"id": issue_id, "s": sid})


def add_comment(issue_id, body):
    linear('mutation($i:String!,$b:String!){commentCreate(input:{issueId:$i,body:$b}){success}}',
           {"i": issue_id, "b": body})


def upsert_document(title, content):
    """제목 일치 문서가 있으면 갱신, 없으면 프로젝트에 생성."""
    d = linear('query($q:String!){documents(filter:{title:{eq:$q}}){nodes{id}}}', {"q": title})
    nodes = d["documents"]["nodes"]
    if nodes:
        linear('mutation($id:String!,$c:String!){documentUpdate(id:$id,input:{content:$c}){success}}',
               {"id": nodes[0]["id"], "c": content})
        return nodes[0]["id"]
    inp = {"title": title, "content": content}
    if project_id():
        inp["projectId"] = project_id()
    d = linear('mutation($i:DocumentCreateInput!){documentCreate(input:$i){document{id}}}', {"i": inp})
    return d["documentCreate"]["document"]["id"]


# ───────────────────────── GitHub (git + gh, 격리 worktree) ─────────────────────────
def _git_env():
    e = dict(os.environ)
    e.pop("GITHUB_TOKEN", None)   # invalid GITHUB_TOKEN 이 keyring 가리는 함정 회피
    return e


def _run(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, env=_git_env(), capture_output=True, text=True, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(f"$ {' '.join(args)}\n{r.stdout}\n{r.stderr}".strip()[:500])
    return r


def github_pr(branch, title, body, files, commit_msg):
    """files 를 origin/main 기반 격리 worktree에서 branch로 커밋·push 후 PR upsert. PR URL 반환."""
    _run(["git", "fetch", "origin", "main"], cwd=REPO)
    wt = Path("/tmp") / f"squad-wt-{branch.replace('/', '_')}-{int(time.time())}"
    _run(["git", "worktree", "add", "--detach", str(wt), "origin/main"], cwd=REPO)
    try:
        # 원격에 같은 브랜치가 있으면 그 위에, 없으면 origin/main 에서 분기
        ls = _run(["git", "ls-remote", "--heads", "origin", branch], cwd=REPO, check=False)
        if ls.stdout.strip():
            _run(["git", "fetch", "origin", branch], cwd=REPO)
            _run(["git", "switch", "-C", branch, f"origin/{branch}"], cwd=wt)
        else:
            _run(["git", "switch", "-c", branch], cwd=wt)
        # 라이브 작업트리의 파일을 worktree로 스냅샷 복사
        copied = []
        for f in files:
            src = REPO / f
            if not src.exists():
                log(f"  ⚠️ 파일 없음, 건너뜀: {f}")
                continue
            dst = wt / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            copied.append(f)
        if not copied:
            return None
        _run(["git", "add", "--"] + copied, cwd=wt)
        diff = _run(["git", "diff", "--cached", "--name-only"], cwd=wt, check=False)
        if not diff.stdout.strip():
            log("  (변경 없음 — 커밋 생략)")
        else:
            _run(["git", "commit", "-m", commit_msg], cwd=wt)
            _run(["git", "push", "-u", "origin", branch], cwd=wt)
        # PR upsert
        existing = _run(["gh", "pr", "list", "--head", branch, "--json", "url", "--jq", ".[0].url"],
                        cwd=REPO, check=False)
        url = existing.stdout.strip()
        if url:
            return url
        cr = _run(["gh", "pr", "create", "--base", "main", "--head", branch,
                   "--title", title, "--body", body], cwd=REPO, check=False)
        out = (cr.stdout + cr.stderr).strip()
        for tok in out.split():
            if tok.startswith("https://github.com/"):
                return tok
        return out[:200]
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, check=False)


# ───────────────────────── Discord ─────────────────────────
def notify(text):
    if bot_send and SQUAD_CH:
        try:
            bot_send.send_message(text, channel_id=SQUAD_CH)
        except Exception as e:
            log(f"  Discord 알림 실패: {e}")


# ───────────────────────── handoff 처리 ─────────────────────────
def process_dict(h, label="handoff"):
    role = h.get("role", "?")
    status = h.get("status", "in_progress")
    summary = (h.get("summary") or "").strip()
    files = h.get("files") or []
    log(f"{label}: role={role} issue={h.get('issue')} status={status} files={len(files)}")

    # 1) 이슈 확보 (있으면 조회, 없으면 생성)
    issue = None
    if h.get("issue"):
        issue = get_issue(h["issue"])
        if not issue:
            log(f"  ⚠️ {h['issue']} 조회 실패 — 코멘트/PR 생략")
    elif h.get("title"):
        issue = create_issue(h["title"], summary, role)
        log(f"  + 신규 이슈 {issue['identifier']}")

    ident = issue["identifier"] if issue else (h.get("issue") or "")

    # 2) GitHub PR (파일 있을 때만)
    pr_url = None
    if files and issue:
        # ASCII 브랜치 고정: Linear gitBranchName 은 한글이라 gh PR 생성이 깨짐.
        # 'jay-6' 토큰 + PR 제목 '[JAY-6]' 로 네이티브 연동이 이슈 자동 링크됨.
        branch = f"squad/{ident.lower()}-{role}"
        title = f"[{ident}] {h.get('title') or summary.splitlines()[0][:60]}"
        body = f"{summary}\n\n관련 이슈: {ident}\n담당: {role}\n\n🤖 squad_sync 자동 생성"
        cmsg = f"{ident}: {summary.splitlines()[0][:72]}\n\n담당 {role}\n🤖 squad_sync"
        try:
            pr_url = github_pr(branch, title, body, files, cmsg)
            log(f"  GitHub PR: {pr_url}")
        except Exception as e:
            log(f"  ⚠️ GitHub 실패: {e}")

    # 3) Linear 코멘트 + 상태 + 문서
    if issue:
        try:
            cbody = f"**{role}** 작업 {('완료' if status=='done' else '진행')}\n\n{summary}"
            if pr_url:
                cbody += f"\n\nGitHub PR: {pr_url}"
            add_comment(issue["id"], cbody)
            update_issue_state(issue["id"], status)
            log(f"  Linear {ident} 코멘트+상태({status}) 갱신")
        except Exception as e:
            log(f"  ⚠️ Linear 갱신 실패: {e}")
    doc = h.get("doc")
    if doc and doc.get("path"):
        try:
            content = (REPO / doc["path"]).read_text(encoding="utf-8")
            upsert_document(doc.get("title") or Path(doc["path"]).stem, content)
            log(f"  Linear 문서 upsert: {doc.get('title')}")
        except Exception as e:
            log(f"  ⚠️ 문서 upsert 실패: {e}")

    # 4) Discord 알림
    bits = [f"🔗 **{ident or role}** 연동", summary.splitlines()[0] if summary else ""]
    if pr_url:
        bits.append(f"PR: {pr_url}")
    if issue:
        bits.append(f"Linear: 상태 {STATUS_STATE.get(status, status)}")
    notify("  ·  ".join(b for b in bits if b))


def process(path: Path):
    """파일 기반(watcher) 처리 — 처리 후 done/ 으로 이동."""
    h = json.loads(path.read_text(encoding="utf-8"))
    process_dict(h, label=f"handoff {path.name}")
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    path.rename(DONE_DIR / path.name)


def _args_to_handoff(a):
    h = {"role": a.role, "summary": a.summary or "", "status": a.status}
    if a.issue:
        h["issue"] = a.issue
    if a.title:
        h["title"] = a.title
    if a.file:
        h["files"] = a.file
    if a.doc_title and a.doc_path:
        h["doc"] = {"title": a.doc_title, "path": a.doc_path}
    return h


def process_all():
    if not HANDOFF_DIR.exists():
        return 0
    pending = sorted(p for p in HANDOFF_DIR.glob("*.json"))
    for p in pending:
        try:
            process(p)
        except Exception as e:
            log(f"  ❌ {p.name} 처리 실패: {e}")
    return len(pending)


def emit(args):
    """봇/테스트가 handoff 파일을 생성하는 헬퍼."""
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    h = _args_to_handoff(args)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    p = HANDOFF_DIR / f"{ts}-{args.role}.json"
    p.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"handoff 생성: {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="인자로 받은 작업을 즉시 Linear/GitHub/Discord에 반영(봇 직접 호출용, 데몬 불필요)")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--role"); ap.add_argument("--issue"); ap.add_argument("--title")
    ap.add_argument("--summary"); ap.add_argument("--status", default="in_progress")
    ap.add_argument("--file", action="append"); ap.add_argument("--doc-title"); ap.add_argument("--doc-path")
    a = ap.parse_args()

    if a.selftest:
        d = linear("{ viewer { name } }")
        print(f"Linear OK: viewer={d['viewer']['name']}, team={TEAM_KEY}({team_id()[:8]}…), project={'OK' if project_id() else 'N/A'}")
        return
    if a.apply:
        process_dict(_args_to_handoff(a), label="apply"); return
    if a.emit:
        emit(a); return
    if a.watch:
        log(f"watch 시작 (interval={a.interval}s, repo={REPO})")
        while True:
            try:
                process_all()
            except Exception as e:
                log(f"watch loop 오류: {e}")
            time.sleep(a.interval)
    else:  # --once (기본)
        n = process_all()
        log(f"처리 완료: {n}건")


if __name__ == "__main__":
    main()
