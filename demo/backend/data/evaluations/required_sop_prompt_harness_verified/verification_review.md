# Prompt-driven SOP Harness Verification

Every operational scenario retrieved SOP evidence with an LLM-selected native search_grounding call. Verified SOP context reached every HTTP Team handoff, and successful final English answers cited verified SOP aliases. Team, Specialist, Tool and reassessment decisions remain model-selected; contract checks, permissions, budgets and data lookup/calculation implementations remain code-enforced.

## Validation

- Backend: 49 tests passed; Django system check passed.
- Frontend: production build passed.
- Browser: 1440px and 390px SOP card restoration, original reference expansion, required-SOP Guide and page bounds passed.
- Saved Chat preserves original Korean SOP titles and raw data while filtering generated Korean assistant text.

## Live evidence

The original sequential suite used a 180-second cap: four completed, while lemon timed out after three Team Artifacts at approximately 160 seconds, before final Chat and final RPT. The original report and trace are retained in ../required_sop_prompt_harness/. Lemon was rerun with a 300-second cap and completed in 94.435 seconds. The other four scenarios were rescored from their original live traces; they were not executed again. No routing or prompt change was made between these two runs.

| Scenario | Evidence | Seconds | Score | SOP in every Team / final Chat |
|---|---|---:|---:|---|
| strawberry_order | recorded_trace | 143.458 | 100/100 | PASS |
| cip_seal_kit | recorded_trace | 141.229 | 100/100 | PASS |
| lemon_profitability | live_run | 94.435 | 100/100 | PASS |
| allulose_introduction | recorded_trace | 162.698 | 100/100 | PASS |
| cost_center_change | recorded_trace | 111.53 | 100/100 | PASS |

## Remaining limitations

- External SAP RPT returned HTTP 404 in every completed assessment. Initial and final cards were supplied by the existing ai_core_rpt_fallback provider. Lifecycle completion and 100-point scores do not establish external SAP RPT availability.
- Joule was unconfigured and excluded from scenario scores.
- Latency and Team paths vary with model decisions: the original lemon run exceeded the evaluation cap, although its rerun completed.
- SOP references are validated against retrieved evidence, but semantic applicability is model-assessed; these tests do not prove every possible request will choose the best procedure.

Lemon final Chat retained base profit USD 101,856, stress profit USD 85,021.44 and decrease USD 16,834.56, with base/stress FX and inflation inputs and verified SOP citations.

See five_scenario_report.md and five_scenario_report.json for queries, Tools, handoffs, Artifacts, final Chat, provider status and full SSE evidence.
