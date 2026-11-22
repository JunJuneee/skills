#!/usr/bin/env python3
"""이번 실행의 역할별 하네스·모델·추론 수준을 정책 파일에서 계산한다.

실행기와 조율자가 같은 결과를 쓰도록 계산을 한곳에 둔다. 표준 라이브러리만 쓴다.

    resolve.py --project seoulseeing --lane M
    resolve.py --project core-ser --lane L --exhausted claude --now 2026-11-22T23:30
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POLICY = os.path.join(os.path.dirname(HERE), "policy.json")
LOCAL_OVERRIDE = os.path.expanduser("~/.traycer/workflow-policy.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
# 검토 역할로 쓸 때의 등급. 적혀 있지 않은 계열은 호출하는 쪽의 기본값을 쓴다.
CHECK_TIER = {"deepseek": "heavy", "qwen": "std"}


def merge(base, over):
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def load_policy(path=None, override="default"):
    if override == "default":
        override = LOCAL_OVERRIDE
    with open(path or DEFAULT_POLICY, encoding="utf-8") as f:
        policy = json.load(f)
    if override and os.path.exists(override):
        with open(override, encoding="utf-8") as f:
            policy = merge(policy, json.load(f))
    return policy


SWITCH_LINE = re.compile(r"""^\s*(?:export\s+)?NIGHT_ROSTER\s*=\s*(['"]?)(auto|on|off)\1\s*(?:#.*)?$""")


def parse_switch(text):
    """스위치 파일에서 마지막 유효한 대입만 읽는다. 주석과 다른 키는 무시한다."""
    value = None
    for line in text.splitlines():
        found = SWITCH_LINE.match(line)
        if found:
            value = found.group(2)
    return value


def read_switch(policy, env=None):
    """NIGHT_ROSTER 값(auto|on|off). 파일이 우선이고, 없으면 환경변수, 그것도 없으면 auto."""
    path = os.path.expanduser(policy["night"]["switch_file"])
    value = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            value = parse_switch(f.read())
    if value is None:
        value = (os.environ if env is None else env).get("NIGHT_ROSTER")
    return value if value in ("auto", "on", "off") else "auto"


def is_night(policy, now):
    start, end = policy["night"]["window_kst"]
    hour = now.astimezone(KST).hour
    if start > end:  # 자정을 넘는 구간
        return hour >= start or hour < end
    return start <= hour < end


def role(policy, family, tier, effort=None):
    spec = policy["families"][family]
    model = spec["models"].get(tier) or spec["models"]["std"]
    out = {"family": family, "harness": spec["harness"], "model": model}
    if not spec.get("cn"):
        out["effort"] = effort or policy["effort"][tier]
    if spec.get("expect_version"):
        out["expect_version"] = spec["expect_version"]
    return out


def resolve(policy, project, lane, switch, now, exhausted=(), switches=0):
    exhausted = set(exhausted)
    proj = policy["projects"].get(project, policy["default_project"])
    lane_cfg = policy["lanes"][lane]
    night = is_night(policy, now)
    cn_any = proj["cn_allowed"] and switch != "off"
    cn_impl = cn_any and lane_cfg["cn_implement"] and (switch == "on" or night)
    primary = proj["primary"]
    other = "claude" if primary == "codex" else "codex"

    out = {
        "project": project,
        "lane": lane,
        "night_roster": switch,
        "mode": "night_cn" if cn_impl else "day",
        "roles": {},
        "wait": [],
        "notes": [],
        "limits": {
            "review_rounds": lane_cfg["review_rounds"],
            "token_cap": lane_cfg["token_cap"],
            "session_context_cap": policy["session_context_cap"],
            "plan_approval": lane_cfg["plan_approval"],
            "stop_at": proj["stop_at"],
        },
    }
    if switches > policy["fallback"]["max_switches_per_issue"]:
        out["wait"].append("implement")
        out["notes"].append("이슈당 전환 횟수 상한을 넘어 대기한다")
        return out

    def first(candidates):
        return next((f for f in candidates if f not in exhausted), None)

    # 조율자는 주간 계열을 유지한다.
    coordinator = first([primary, other])
    if coordinator:
        out["roles"]["coordinator"] = role(policy, coordinator, "std")
    else:
        out["wait"].append("coordinator")

    chain = (["qwen"] if cn_impl else []) + [primary, other]
    impl = first(chain)
    if not impl:
        out["wait"].append("implement")
        return out
    tier = lane_cfg["implement_tier"]
    out["roles"]["implement"] = role(policy, impl, tier)
    if impl != chain[0]:
        skipped = chain[: chain.index(impl)]
        out["notes"].append("구현 전환: " + ", ".join(skipped) + " 소진 → " + impl)

    # 같은 계열은 마지막 수단이다. 더 높은 등급의 새 세션으로만, L 줄이 아닐 때만 쓰고 기록한다.
    def same_family(kind):
        if lane == "L" or tier == "heavy" or "heavy" not in policy["families"][impl]["models"]:
            return None
        picked = role(policy, impl, "heavy")
        picked["same_family"] = True
        out["notes"].append(kind + ": 다른 계열을 쓸 수 없어 같은 계열(" + impl + ")의 상위 모델을 새 세션으로 쓴다")
        return picked

    # 계획 critique: 계획을 쓴 계열과 다른 계열.
    count = lane_cfg["critics"]
    out["roles"]["critics"] = []
    if count:
        # L 줄의 critique는 중국 모델을 쓰지 않는다.
        cn_critics = ["deepseek", "qwen"] if cn_any and lane != "L" else []
        order = cn_critics + ["claude", "codex"] if cn_impl else ["claude", "codex"] + cn_critics
        critic = first([f for f in order if f != impl])
        if critic and count == 1:
            out["roles"]["critics"] = [role(policy, critic, CHECK_TIER.get(critic, "std"))]
        elif critic:
            out["roles"]["critics"] = [role(policy, critic, t) for t in ["heavy"] * (count - 1) + ["std"]]
        else:
            fallback = same_family("critique")
            if fallback:
                out["roles"]["critics"] = [fallback]
            else:
                out["wait"].append("critique")

    # 테스트 작성·검증 세션은 L 줄에만 둔다. 그 밖에는 구현 세션과 실행기 스크립트가 맡는다.
    if lane_cfg["separate_tests"]:
        spec = policy["test_roles"][impl]
        family = spec.get("family", impl)
        tester = role(policy, family, spec["tier"], spec.get("effort"))
        out["roles"]["test_writer"] = tester
        out["roles"]["verifier"] = dict(tester)

    # 최종 리뷰: 코드를 쓴 계열과 다른 계열.
    cn_reviewers = (["deepseek", "qwen"] if impl == "qwen" else ["qwen", "deepseek"]) if cn_any else []
    chain_r = [(f, CHECK_TIER.get(f, "heavy")) for f in cn_reviewers + ["claude", "codex"]]
    pick = next(((f, t) for f, t in chain_r if f != impl and f not in exhausted), None)
    if pick:
        out["roles"]["reviewer"] = role(policy, pick[0], pick[1])
        if pick != chain_r[0]:
            out["notes"].append("리뷰 전환: " + chain_r[0][0] + " 사용 불가 → " + pick[0])
    else:
        fallback = same_family("리뷰")
        if fallback:
            out["roles"]["reviewer"] = fallback
        else:
            out["wait"].append("review")
    out["escalation"] = escalation(policy, impl, tier, [primary, other], out["roles"].get("reviewer"), exhausted)
    return out


def escalation(policy, impl, tier, day_chain, reviewer, exhausted):
    """리뷰 2회째에 올릴 구현 모델. 올릴 곳이 없으면 None이다."""
    if tier == "heavy":
        return None
    if "heavy" in policy["families"][impl]["models"]:
        return role(policy, impl, "heavy")
    taken = {reviewer["family"]} if reviewer else set()
    family = next((f for f in day_chain if f not in exhausted and f not in taken), None)
    return role(policy, family, "heavy") if family else None


def parse_exhausted(text, policy):
    names = [x.strip() for x in text.split(",") if x.strip()]
    unknown = [x for x in names if x not in policy["families"]]
    if unknown:
        raise ValueError("알 수 없는 계열: " + ", ".join(unknown))
    return names


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--lane", choices=["S", "M", "L"])
    p.add_argument("--exhausted", default="", help="사용량이 소진된 계열을 쉼표로 (claude,codex,qwen,deepseek)")
    p.add_argument("--switches", type=int, default=0, help="이 이슈에서 이미 한 계열 전환 횟수")
    p.add_argument("--now", help="ISO 시각. 생략하면 현재 시각")
    p.add_argument("--night-roster", choices=["auto", "on", "off"], help="스위치 파일 대신 쓸 값")
    p.add_argument("--policy")
    args = p.parse_args(argv)

    policy = load_policy(args.policy)
    now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    switch = args.night_roster or read_switch(policy)
    lane = args.lane or policy["default_lane"]
    try:
        exhausted = parse_exhausted(args.exhausted, policy)
    except ValueError as exc:
        p.error(str(exc))
    result = resolve(policy, args.project, lane, switch, now, exhausted, args.switches)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 3 if result["wait"] else 0


if __name__ == "__main__":
    sys.exit(main())
