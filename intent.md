# RPT-gated Joule A2A Work Agent

## Framework step 1: default Harness Profile

Extract the existing F&B configuration into the single `fnb-default` Harness
Profile. Gateway and the shared Team server must use the same validated loader
for Agent identities, Specialist Tool/domain permissions, Tool contracts, runtime
budgets/timeouts and demo-owned Prompt/CSV/RPT resource references. Preserve exact
Prompt text, public contracts, LLM-based decisions, Tool implementations and
calculations. Credentials remain environment-only; existing model, address and
timeout environment overrides retain precedence. Expose a read-only
`GET /api/harness-profile` inspection endpoint without credentials or internal
paths. Changes take effect after both services restart. Validate configuration
and references, and reject invalid Profiles with a clear configuration error.
Preserve Chat, SSE, A2A envelopes and the Harness Guide diagram/layout. Editing,
Profile switching, external Agent registration and HITL are future steps.

The next UI step adds a read-only Harness Studio menu and Agents & A2A view.
Load the existing public Profile API to inspect Team/Skill identities, internal
Specialists and authorized Tools/evidence domains. Reuse the system Prompt modal
for all Agent roles, provide loading/error/retry states and preserve the current
Chat session when navigating. Keep the Harness Guide drawing unchanged. Editing
and saving configuration are deferred to a later step.

## Framework completion

Complete the management capabilities in Harness Studio: Agents & A2A,
Prompts & Models, Tools & Data, Grounding, Runtime & Decisions and Evaluation.
Keep the Harness Guide diagram/layout and existing Chat collaboration intact.
Provide validated, versioned, durable configuration with change comparison,
conflict detection and failure-safe saves. Gateway and Team server share the
same immutable configuration revision for each request; ongoing work retains
its revision and new requests use saved changes. Secrets stay server-only.
Implement Prompt editing for Orchestrator, Teams and Specialists plus deployed
role model selection first, then connect each remaining configuration surface
to its runtime consumer and verify it. Evaluation must execute isolated read-only
scenarios and report Tool/Chat/context/RPT evidence; provider failures must be
reported honestly. Preserve LLM decisions rather than adding business keyword
routes. Treat real business writes and creation/deployment of external Agents
as outside this framework's read-only operational boundary.

## Harness Studio card navigation

Replace the initial dense Studio overview with nine text-only setting cards:
Agents & A2A, Prompts & Models, Tools, Business Data, Grounding, Runtime,
RPT Decision, Joule and Evaluation. Open the existing editor directly and use
an internal Back to settings button, without introducing URL routing. Preserve
mounted drafts, versioned saves, comparison/discard/conflict protection and
evaluation progress/history. Use a spacious responsive 3/2/1-column grid and
restore keyboard focus to the originating card. Keep backend contracts, Agent
execution, Chat and the Harness Guide diagram/layout unchanged.

## Final requester summary

After the Orchestrator selects finish_review, generate a fresh LLM summary from
the request, relevant history, verified SOP, completed Team/Joule Artifacts and
calculation evidence. The capability's summary is a preliminary draft, not the
final Chat response. Present the substantive outcome, sources, decisive figures,
remaining conditions and next action in concise English instead of a readiness
acknowledgement. Use the same generated text for Chat, the Synthesis Artifact and
final RPT context. Preserve event ordering and failure-safe termination; do not
publish a draft as a successful final answer if synthesis fails.

## Demo-owned A2A Harness

Implement the collaboration behavior documented in the A2A lesson independently
inside demo. Do not import, copy, or run notebook code, prompts, CSV resources,
or Team servers. Preserve the twelve Team identities and public Tool names.

The Gateway discovers Cards on a separate shared Team server and delegates
structured A2A tasks over HTTP. Each Team selects its internal Specialists with
the LLM, runs authorized native function-calling turns, and returns an Artifact.
The Orchestrator observes accumulated Artifacts and chooses another handoff or
completion. Every request must retrieve applicable SOP evidence through Grounding
before any RPT/Joule or Team review. The Orchestrator selects the SOP query with
prompt-based native Tool calling; code validates the prerequisite and never
selects a business route by keyword. This replaces optional Grounding. If SOP
retrieval fails or no applicable evidence is found, stop the business review and
return a safe failed result. Team and Specialist selection remains LLM-based.
Use newly authored English sample records and prompts. Bound handoffs to three
and Specialist Tool turns to three; reuse exact normalized duplicate Tool calls.
Keep initial RPT/Joule and final RPT as extensions, not Team routing authority.
Acceptance includes real HTTP contract tests, English Chat ordering, independent
resource checks, backend/build preflight, and five isolated live scenarios.

Apply Guide alignment one change at a time without changing its diagram or layout.
The first change creates a final Orchestrator Synthesis Artifact when the LLM
chooses finish_review. Preserve the English answer, verified SOP references,
Team evidence and calculations in an A2A-compatible read-only Artifact. Failed
reviews must not produce a successful synthesis. Keep current Chat/RPT ordering,
HITL behavior, initial extensions and execution budgets in this first change.
The second change passes the final Synthesis Artifact into the final RPT
adapter's LLM-generated English decision state alongside SOP and Team evidence.
Preserve initial RPT behavior, final Chat ordering, HITL and the Guide drawing.

F&B 운영 데모에서 SAP RPT Decision API 판단을 바탕으로 이미 배포된 Joule Studio Work Agent에 읽기 전용 A2A handoff를 보냅니다.

## Business challenge

데모 운영자와 발표자는 운영 요청의 판단 근거와 외부 Joule Work Agent handoff 과정을 안전하게 보여줘야 합니다.

## Business Goals & Success Criteria

| Metric | Baseline | Target | Timeline | Process / Capability | Source |
|---|---|---|---|---|---|
| 유효한 `delegate_now` 요청의 end-to-end handoff 완료율 | — | 100% | — | F&B 운영 요청 판단 및 읽기 전용 A2A handoff | user |

## Key Milestones

1. RPT Decision 판단과 근거가 생성된다.
2. 대상 Joule Work Agent Card가 검증된다.
3. CLI A2A handoff의 읽기 전용 artifact가 수신된다.
4. 기존 F&B Team Agent 종합 결과에 Joule artifact가 포함된다.

## Business Architecture (RBA)

### End-to-End Process

Governance

### Process Hierarchy

```
Governance
├── Manage Information Technology
│   └── Manage enterprise information (BPS-411)
└── Plan to Optimize Enterprise
    └── Develop enterprise strategy and plans (BPS-402)
```

### Summary

RPT 판단 근거를 관리하고, 로컬 Orchestrator가 배포된 Work Agent에 안전한 읽기 전용 handoff를 조율합니다.

## Fit Gap Analysis

| Requirement (business) | Standard asset(s) found | API ORD ID | MCP Server ORD ID | MCP Server Version | Webhook API ORD ID | Data Product ORD ID | Gap? | Notes / assumptions |
|---|---|---|---|---|---|---|---|---|
| 운영 판단 근거 관리 | SAP S/4HANA Cloud Intelligent Business Management | — | — | — | — | — | Yes | 데모에는 RPT Decision API adapter가 필요합니다. |
| A2A Work Agent orchestration | SAP LeanIX Enterprise Architecture Management | — | — | — | — | — | Yes | 기존 Joule Studio CLI로 Card 검증과 메시지 전달을 구현합니다. |

### Key findings

- RPT 판단 및 Joule CLI A2A handoff은 데모 전용 custom integration으로 구현합니다.
- API 카탈로그 조회는 네트워크 오류로 완료되지 않았으며 외부 업무 API는 범위에 없습니다.
- 새 Work Agent 배포와 외부 쓰기는 제외합니다.

## Recommendations

### RPT-gated read-only Joule handoff

#### Executive Summary

RPT 판단과 Card 검증을 거친 단일 Joule Work Agent handoff

#### Recommended Solution

한국어 요청을 AI Core로 번역하고 RPT Decision API가 `delegate_now`를 반환한 경우에만 설정된 Joule Solution/Asset의 Card를 검증한 뒤 A2A 메시지를 전송합니다. 결과는 기존 F&B Team 검토의 읽기 전용 artifact로 사용합니다.

#### Problem Statement

데모에서 외부 Work Agent 호출의 판단 근거, 안전 경계, 실행 결과를 관찰 가능하게 해야 합니다.

#### Affected User Roles

- 데모 운영자
- 데모 발표자

#### Important factors

##### Read-only execution

모든 RPT와 Joule 호출은 읽기 전용이며 외부 상태를 변경하지 않습니다.

#### Potential risks

##### External dependency availability

RPT API, Joule CLI 인증, Agent Card 또는 배포 상태 오류가 handoff를 막을 수 있습니다.

#### Recommended solution category

AI Agent

#### Intent fit

95%


## Harness framework management — confirmed completion scope

Implement the integrated Harness Studio through Agents/A2A registration,
per-role Prompts and running AI Core model selection, native Tool descriptions
and permissions, editable demo CSV datasets, SOP Grounding Prompts/repository,
Runtime/context budgets, RPT criteria/examples, deployed Joule target and
repeatable Evaluation configuration/history/evidence. Preserve the existing
Chat collaboration layout and Harness Guide diagram. Business decisions remain
LLM/native-function based; configuration never adds keyword Agent routing.

Persist validated revisions shared by Gateway and Team server. Compare-and-save
protects concurrent edits; new requests use latest settings and running requests
retain one immutable revision through Card discovery and HTTP Tasks. Credentials
and connection/model environment overrides stay server-side. Tool implementations
and required input schemas remain code-registered; UI controls descriptions,
permissions and sample evidence rather than executing arbitrary uploaded code.

HITL has an advisory default and an optional final-assessment input checkpoint.
When final RPT requests evidence or human review, persist pending input and emit
input_required. Human input starts a new root reassessment with prior Artifacts,
same session and original settings revision. It does not resume completed Team
Tasks or perform business approval/data writes. Evaluation must report a pending
human review as incomplete until input is supplied; never score it as complete.

Verify persisted edits affect real runtime consumers, HTTP A2A Cards/Tasks,
external standard Artifacts, invalid-save preservation, concurrency, HITL,
bounded evaluation history/trace redaction, desktop/mobile browser interactions,
backend contracts and production build. Finish with a fresh five-scenario live
run; report RPT provider/fallback and optional Joule status honestly.
