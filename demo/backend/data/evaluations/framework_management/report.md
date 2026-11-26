# Harness Studio framework implementation verification

Implemented and deployed at http://localhost:5173 → Harness Studio. Existing Chat layout and Harness Guide diagram are preserved.

## Management capabilities

| Section | Implemented controls |
|---|---|
| Agents & A2A | Team/Skill/Specialist registration, existing external Agent endpoints, Card checks |
| Prompts & Models | Per-role editing, comparison, defaults, validated running GPT model deployment selection |
| Tools & Data | Native Tool descriptions, Specialist permissions/domains, four editable CSV datasets and replacement preview |
| Grounding | Required SOP repository and Prompt configuration |
| Runtime & Decisions | Handoff/Tool budgets, context caps/timeouts, RPT criteria/examples/Prompts, deployed Joule target, optional human-input checkpoint |
| Evaluation | Scenario requests/assertions, rubric weights/timeouts/threshold, live runs/history, Chat/RPT/Tool/SSE evidence |

## Verification

- 97 backend tests passed; Django system check and frontend production build passed.
- Browser checks passed at 1440px and 390px, using both localhost and 127.0.0.1.
- Verified save persistence, draft retention, compare/discard, stale-save protection, invalid-save preservation, actual Team Card checks, and no horizontal page overflow or JavaScript errors.
- Actual HTTP SDK tests cover dynamic Team registration/removal with pinned revisions and external Text Artifact append handling. External execution is integration-tested with a test server; live Joule remains unconfigured.
- Actual ASGI HTTP test verifies immediate SSE transmission before an Agent finishes its review.
- Human-input checkpoint, same-session revision/evidence retention, reassessment submission and duplicate-input prevention passed backend/browser tests.
- Concurrent browser configuration edits during evaluation did not change the running revision 70.
- HarnessLearningPage.tsx, harness-learning.css, chat-layout.css, graph-layout.css and review-timeline.css hashes match the pre-framework baseline.
- All browser test edits were restored. Running Docker Gateway and Team server are healthy.

## Live scenario outcomes

Five scenarios ran sequentially with unique sessions and 300-second limits. Four passed initially. CIP was retested live after its RPT language defect was fixed. These are combined results from two runs, with source run/revision information retained in the JSON report.

| Scenario | Final score | Duration | Tools | Final words |
|---|---:|---:|---:|---:|
| Additional order for existing raw materials | 100.0/100 | 94.193s | 5 | 141 |
| Replenishment purchase for existing equipment consumables | 100.0/100 | 121.51s | 6 | 148 |
| Business impact assessment for exchange-rate and raw-material price changes | 100.0/100 | 95.57s | 8 | 150 |
| Register and introduce a new raw material into production | 100.0/100 | 114.044s | 7 | 151 |
| Change the production-line cost center | 100.0/100 | 81.757s | 5 | 143 |

Initial and final RPT completed through the SAP Decision API for these results. Joule was not configured and was reported separately from scenario scores. Lemon calculations retained base profit USD 101,856, stress profit USD 85,021.44 and reduction USD 16,834.56, including FX/inflation assumptions and attribution.

## Resolved defects

1. ASGI buffered the original synchronous SSE iterator, causing the initial evaluator to time out without events. Gateway now returns a native asynchronous iterator under ASGI; original failure evidence is retained.
2. The initial CIP RPT state repeated Korean SOP department names. The adapter now asks the LLM to rewrite any such generated state entirely in English, preserving evidence and source IDs, and fails safely if repair still contains Korean. Unit and live retest checks passed.
3. Consecutive Chat requests could reuse the final-summary message ID. Stream IDs are now scoped to each request; separate final bubbles passed browser tests.

## Supported boundaries

Only fnb-default is managed in this release. Tool implementations and required inputs remain code-registered; Studio edits descriptions, permissions and sample data. Model selection supports running GPT chat-completions deployments compatible with the current native Tool adapter. Grounding points to an existing SOP repository. Joule points to an existing deployed Work Agent. Credentials remain environment-only.

HITL defaults to advisory. The optional final-RPT checkpoint starts a new root reassessment with previous Artifacts and the pinned revision; it does not resume completed Team Tasks or execute a business approval.

Scenario details, category checks, final answers, RPT status, Tool traces and all SSE evidence are in [five_scenario_report.md](five_scenario_report.md) and [five_scenario_report.json](five_scenario_report.json). Browser evidence is in [browser-report.json](browser-report.json).
