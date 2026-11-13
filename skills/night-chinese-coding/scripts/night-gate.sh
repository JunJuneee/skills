#!/usr/bin/env bash
# night-gate.sh — 야간 자동 실행 gate
# Todo + Jay 담당 + 제외 라벨 없는 이슈가 있으면 출력, 없으면 무출력 exit 0
set -euo pipefail

COMPOSIO="${HOME}/.local/bin/composio"
ACCOUNT="homeshopick"
JAY_ID="f777c018-ba23-48e8-804a-1b23ec3b87fe"
TODO_STATE="21512dc7-3d50-420a-ad03-513507931690"

QUERY='{ issues(first: 20, filter: { state: { id: { eq: "'"${TODO_STATE}"'" } }, assignee: { id: { eq: "'"${JAY_ID}"'" } } }) { nodes { identifier title state { name } labels { nodes { name } } priority } } }'

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

eligible.sort(key=lambda x: -x['priority'])
print(json.dumps(eligible[:3], ensure_ascii=False, indent=2))
" "$RESULT"
