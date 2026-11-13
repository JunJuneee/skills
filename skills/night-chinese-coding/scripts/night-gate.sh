#!/usr/bin/env bash
# night-gate.sh — 야간 자동 실행 gate
# Todo + 제외 라벨 없는 이슈가 있으면 출력, 없으면 무출력 exit 0
# (담당자 조건 없음 — Todo 이슈는 모두 사용자 소유)
set -euo pipefail

COMPOSIO="${HOME}/.local/bin/composio"
ACCOUNT="homeshopick"
TODO_STATE="21512dc7-3d50-420a-ad03-513507931690"

QUERY='{ issues(first: 100, filter: { state: { id: { eq: "'"${TODO_STATE}"'" } } }) { nodes { identifier title state { name } labels { nodes { name } } priority } } }'

RESULT=$("$COMPOSIO" execute LINEAR_RUN_QUERY_OR_MUTATION \
  -d "{\"query_or_mutation\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$QUERY")}" \
  --account "$ACCOUNT" 2>/dev/null) || exit 0

python3 -c "
import json, sys

BLOCK_LABELS = {'agent-running', 'agent-hold', 'blocked', 'needs-confirm', 'owner-action'}

try:
    d = json.loads(sys.argv[1])
    nodes = d['data']['data']['issues']['nodes']
except (KeyError, TypeError, json.JSONDecodeError):
    sys.exit(0)

eligible = []
for n in nodes:
    labels = {l['name'] for l in n.get('labels', {}).get('nodes', [])}
    if labels & BLOCK_LABELS:
        continue
    eligible.append({
        'id': n['identifier'],
        'title': n['title'],
        'labels': sorted(labels),
        'priority': n.get('priority', 0),
    })

if not eligible:
    sys.exit(0)

# Linear priority: 1=긴급 2=높음 3=보통 4=낮음 0=없음 → 긴급 먼저, 없음 마지막
eligible.sort(key=lambda x: (x['priority'] == 0, x['priority']))
print(json.dumps(eligible[:3], ensure_ascii=False, indent=2))
" "$RESULT"
