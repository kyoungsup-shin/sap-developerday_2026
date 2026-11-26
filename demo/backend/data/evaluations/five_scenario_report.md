# Five-Scenario Live Evaluation

Overall score: **60.0/100**

| Scenario | Score | Result | Tools |
|---|---:|---|---|
| Additional order for existing raw materials | 65/100 | FAIL | search_business_context, retrieve_business_evidence, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence, search_business_context, retrieve_business_evidence; transport: Scenario did not complete within 120 seconds. |
| Replenishment purchase for existing equipment consumables | 65/100 | FAIL | search_business_context, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence; transport: Scenario did not complete within 120 seconds. |
| Business impact assessment for exchange-rate and raw-material price changes | 35/100 | FAIL | unknown, unknown, unknown, unknown, unknown, unknown, unknown, unknown, unknown, unknown; transport: Scenario did not complete within 120 seconds. |
| Register and introduce a new raw material into production | 65/100 | FAIL | search_business_context, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence, retrieve_business_evidence, search_business_context, retrieve_business_evidence, search_business_context, retrieve_business_evidence, retrieve_business_evidence; transport: Scenario did not complete within 120 seconds. |
| Change the production-line cost center | 70/100 | FAIL | unknown, unknown |

## Findings

### Additional order for existing raw materials
- Evaluation transport failure after partial trace: Scenario did not complete within 120 seconds.
- Controlled handoff sequence completed: Required=('grounding_completed', 'rpt_decision_completed', 'delegation_selected', 'artifact_received', 'orchestrator_message_delta', 'rpt_final_decision_completed', 'complete'); observed=['session', 'field_handoff_received', 'grounding_started', 'grounding_completed', 'rpt_decision_started', 'rpt_decision_completed', 'joule_card_verification_started', 'joule_handoff_failed', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received']
- Final Chat answer is present: No final answer event.
- Final Chat answer is English: Missing final answer or Hangul detected.
- Final RPT lifecycle and completion are present: Final RPT=False; complete=False
### Replenishment purchase for existing equipment consumables
- Evaluation transport failure after partial trace: Scenario did not complete within 120 seconds.
- Controlled handoff sequence completed: Required=('grounding_completed', 'rpt_decision_completed', 'delegation_selected', 'artifact_received', 'orchestrator_message_delta', 'rpt_final_decision_completed', 'complete'); observed=['session', 'field_handoff_received', 'grounding_started', 'grounding_completed', 'rpt_decision_started', 'rpt_decision_completed', 'joule_card_verification_started', 'joule_handoff_failed', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received']
- Final Chat answer is present: No final answer event.
- Final Chat answer is English: Missing final answer or Hangul detected.
- Final RPT lifecycle and completion are present: Final RPT=False; complete=False
### Business impact assessment for exchange-rate and raw-material price changes
- Evaluation transport failure after partial trace: Scenario did not complete within 120 seconds.
- LLM Tool contracts are executable: No valid Tool observation.
- Tool Context IDs originate from resolution: Resolved=[]; used=[]
- At least one read-only Tool observation was produced: Tools=['None', 'None', 'None', 'None', 'None', 'None', 'None', 'None', 'None', 'None']
- Controlled handoff sequence completed: Required=('grounding_completed', 'rpt_decision_completed', 'delegation_selected', 'artifact_received', 'orchestrator_message_delta', 'rpt_final_decision_completed', 'complete'); observed=['session', 'field_handoff_received', 'grounding_started', 'grounding_completed', 'rpt_decision_started', 'rpt_decision_completed', 'joule_card_verification_started', 'joule_handoff_failed', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received']
- Final Chat answer is present: No final answer event.
- Final Chat answer is English: Missing final answer or Hangul detected.
- Final RPT lifecycle and completion are present: Final RPT=False; complete=False
- Lemon product Context was resolved: Resolved=[]
- Cost evidence and profitability calculation ran: Tools=['None', 'None', 'None', 'None', 'None', 'None', 'None', 'None', 'None', 'None']
- Final Chat answer cites scenario metrics: No final answer.
### Register and introduce a new raw material into production
- Evaluation transport failure after partial trace: Scenario did not complete within 120 seconds.
- Controlled handoff sequence completed: Required=('grounding_completed', 'rpt_decision_completed', 'delegation_selected', 'artifact_received', 'orchestrator_message_delta', 'rpt_final_decision_completed', 'complete'); observed=['session', 'field_handoff_received', 'grounding_started', 'grounding_completed', 'rpt_decision_started', 'rpt_decision_completed', 'joule_card_verification_started', 'joule_handoff_failed', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'subagent_started', 'tool_observation', 'tool_observation', 'subagent_message_delta', 'subagent_completed', 'team_message_delta', 'a2a_task_update', 'artifact_received', 'orchestration_observation', 'orchestration_decision', 'team_handoff_started', 'a2a_task_update', 'delegation_started', 'delegation_selected', 'subagent_started', 'tool_observation', 'tool_observation', 'tool_observation']
- Final Chat answer is present: No final answer event.
- Final Chat answer is English: Missing final answer or Hangul detected.
- Final RPT lifecycle and completion are present: Final RPT=False; complete=False
- Answer preserves readiness or approval boundary: No final answer.
### Change the production-line cost center
- LLM Tool contracts are executable: No valid Tool observation.
- Tool Context IDs originate from resolution: Resolved=[]; used=[]
- At least one read-only Tool observation was produced: Tools=['None', 'None']
- Financial-control evidence is retrieved and answer does not claim an applied change: Domains=[[], []]; answer=Not ready for review

Finance found no matching Beverage Line 1 record in the supplied local business-context data. The current and requested Cost Centers, exac

## Joule A2A Environment

- strawberry_order: not_configured_or_failed (joule_card_verification_started, joule_handoff_failed)
- cip_seal_kit: not_configured_or_failed (joule_card_verification_started, joule_handoff_failed)
- lemon_profitability: not_configured_or_failed (joule_card_verification_started, joule_handoff_failed)
- allulose_introduction: not_configured_or_failed (joule_card_verification_started, joule_handoff_failed)
- cost_center_change: not_configured_or_failed (joule_card_verification_started, joule_handoff_failed)

## Prioritized remediation

1. Fix the final RPT request path/credentials and add a bounded retry: four runs exceeded the stream budget before final RPT and `complete`.
2. Fix malformed Tool SSE payloads: lemon and cost-center Tool observations could not be decoded, preventing contract validation.
3. Improve semantic context resolution for lemon beverages so `CTX-PROD-LEMON`, cost evidence, and profitability calculation are selected.
4. Configure or explicitly skip Joule A2A before live runs; its current verification failures are reported separately and do not reduce scenario scores.
