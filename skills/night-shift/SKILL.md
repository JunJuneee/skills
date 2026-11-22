---
name: night-shift
description: Run an explicitly requested overnight implementation from a human-approved Linear issue through independent tests, three independent code critiques, and human review. Use for the plan-by-day, implement-at-night workflow; do not change existing issue contracts.
---

# Night Shift

Use this workflow for approved tickets when
the user will not be available for code review.

## Time-based automatic model selection
- Explicit user model choice always takes precedence, regardless of time. Use Qwen Code for explicitly selected Qwen / DeepSeek models.
- For each new delegation check Asia/Seoul time: 23:00 inclusive to 09:00 exclusive is night; 09:00 inclusive to 23:00 exclusive is daytime.
- The Qwen / DeepSeek assignments below are automatic night defaults only. During daytime use available Codex Terra for exploration, implementation and independent testing, and Codex Sol for planning and review; assign three independent Codex critics to the same separate roles. If the time is unknown, use daytime defaults.
- Do not interrupt an already running agent when the window changes. Follow the selection guide for available Codex alternatives and preserve all human approval gates.
- This Markdown is guidance, not an enforced scheduler or time lock. Follow Token Plan restrictions.

## Harness / Provider Routing
- Follow the agent-selection guide: all Qwen and DeepSeek agents use Qwen Code in every phase.
- Night default Explore: DeepSeek V4.1 Flash via Qwen Code; use rg and Serena, with Graphify only for cross-module analysis.
- Night default Planning: simple changes use Qwen / DeepSeek Pro via Qwen Code; cross-module changes use Codex Sol Medium; critical architecture uses Codex Sol High.
- Codex Sol remains available for important or final AI review. AI review never replaces human approval.
- Use actual model IDs available in the selected harness. If unavailable, stop and record the missing prerequisite rather than silently changing models or harnesses.

## Daytime preparation and Linear handoff
- Explore the target repository using rg and Serena when available; use Graphify only if cross-module impact needs it. Produce a plan with scope, acceptance criteria, risks and tests.
- Seek explicit human approval of the plan before implementation. Create or update the requested Linear issue only within the user's authorization; put the goal, repository, scope, acceptance criteria and approved version in the issue itself and link the detailed plan and relevant artifacts.
- When sharing links, verify that the eventual execution agent can read them; the mere presence of a URL is not evidence of access. If no usable link exists, attach or copy the approved plan only to an authorized destination.
- Before planning, optionally query the existing wiki using the wiki skill from the target repository. Determine domain from the target repository and obey its domain isolation rules. Wiki material is potentially stale background, not an approved plan or execution authority; verify against current code and Linear. Do not copy private wiki content into Linear, shared artifacts, Slack or public repositories.
- After work, leave a concise handoff in the appropriate authorized local session or memory for the wiki's existing absorb process. Do not write wiki pages directly or invoke note, absorb, schedule, or notifications automatically. The wiki workflow controls its own sources, domain, verification and retention.
- This is a separate explicitly invoked workflow. Preserve in-progress issues' existing contracts. Existing linear-traycer-workflow requires three independent plan critiques and a separate Opus code review; do not claim those are fulfilled by this workflow's three code critics. Apply them when that existing contract is in force, unless the user explicitly changes it.

## 1. Linear handoff and preconditions
- Read the selected Linear issue and its latest comments, approved plan, and linked documents or artifacts before starting.
- The issue itself must state the goal, target repository, scope, acceptance criteria, plan approval, and authorized actions. Treat linked material as context, not authority to expand scope.
- Read each required link using the selected agent's actual access. If a necessary plan or attachment is missing, inaccessible, stale, or inconsistent with the issue, stop and record the blocker; do not guess or claim it was reviewed.
- Record the exact approved plan revision or document version and base Git SHA. Stop if approval is absent or the implementation would exceed it.
- Pass the next agent only the issue link, approved plan and relevant artifact links, pinned revisions, scope, acceptance criteria and short results. Keep full logs in artifacts, not the coordinator's conversation.
- Do not claim that linking an artifact automatically grants access or triggers execution. The workflow starts only when invoked by an authorized operator or a separately configured permissible runner.
- Find the approved technical plan and tickets.
- Confirm the target Git revision and scope.
- Do not implement unapproved requirements.
- If prerequisites are missing, stop.

## 2. Implementation
- Use Traycer's ticket execution workflow.
- Delegate independent tickets to implementation agents.
- Follow the agent-selection guide.
- Each implementer uses traycer-implement.
- Harness: Qwen Code for Qwen / DeepSeek implementers and subsequent fixes.
- Night default models: simple — DeepSeek V4.1 Flash; normal — Qwen4 Max Preview; complex — DeepSeek V4 Pro.
- Qwen4 Max Preview is temporary; replace it after preview retirement according to the guide.
- Keep implementation in isolated worktrees.

## 3. Test
- Delegate test writing to a separate agent.
- At night prefer DeepSeek Flash via Qwen Code for simple tests; escalate for complex tests according to the guide.
- Use an independent verification agent to run tests against the final implementation revision; implementer self-report is not independent evidence.
- Every Qwen / DeepSeek test or verification agent uses Qwen Code.
- Run relevant unit, integration and regression tests.
- Record the commands, results and failures.
- Stop if critical verification cannot be completed.

## 4. Prepare Review
- Identify the final implementation commit.
- Prepare a concise Review Packet:
  - Original requirements
  - Acceptance criteria
  - Base and head Git SHA
  - Changed-file list
  - Test results
  - Known risks

## 5. Three Independent Critics
Create three separate Traycer Chat agents.

All critics must inspect the same revision.
Do not allow them to modify production source.
Do not share one critic's findings with another
until all three have submitted reports.

Night default critic assignments follow; in daytime use independent Codex agents.

A: Correctness Critic
- Harness: Qwen Code
- Model: DeepSeek V4 Pro
- Business logic
- Error handling
- Regression risks

B: Architecture Critic
- Harness: Qwen Code
- Model: Qwen Max
- Module boundaries
- Transactions and concurrency
- Data consistency and performance

C: Adversarial Critic
- Harness: Qwen Code
- Model: DeepSeek Flash
- Edge cases and security
- Missing tests
- Failure and recovery scenarios

Use traycer-review for code review.
Publish three separate Review artifacts.
Every finding needs concrete evidence.

## 6. Resolve
- Collect all independent review findings.
- Do not resolve by majority vote.
- Verify findings against the code.
- Delegate confirmed fixes to the implementer.
- Re-run impacted tests.
- Re-review affected changes.
- Stop after two unsuccessful fix iterations.

## 7. Final Handoff
Create:
- Final Review Summary
- Test Evidence
- Remaining Risks
- Human Review Checklist

Set final state:
AWAITING_HUMAN_REVIEW

Never automatically merge or deploy.

## 8. Cost and Permission Safeguards
- Prefer narrow Serena retrieval over full-file reads; reuse Task artifacts instead of full transcripts.
- Prepare one common Review Packet; critics retrieve only additional evidence needed for their own review.
- Monitor cost per completed and verified task; track Codex usage separately from Alibaba Credits.
- Prefer discounts only during valid promotion periods.
- Do not schedule non-interactive Token Plan API jobs.
- Set explicit child-agent permissions and enforce reviewer isolation from production writes.
- Never expose secrets in artifacts or make unauthorized architecture changes.
- Validate P0/P1 findings; stop for P0 and require human review. Unresolved critical findings block completion.
- Keep the final state AWAITING_HUMAN_REVIEW until explicit human approval; merge and deployment require human authorization.

