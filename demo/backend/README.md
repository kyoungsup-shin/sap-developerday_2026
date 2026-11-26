# A2A demo backend

When the Orchestrator selects `finish_review`, a separate text completion generates
the final requester summary from the request, relevant history, verified SOP,
completed Artifacts and calculation evidence. The capability's summary remains
an internal draft. The generated answer is shared by Chat, the final Synthesis
Artifact and the final RPT input. Failed synthesis returns a structured failure
instead of presenting the draft as a completed answer.

## Default Harness Profile

Gateway and the shared Team server load the same process-cached
`config/harness/fnb-default.yaml` configuration through
`gateway.harness_profile`. This is the only supported Profile in this step.
It contains Team/Skill/Specialist identities, Specialist Tool/domain allow-lists,
Tool descriptions and input contracts, handoff/Tool-turn limits, provider and
A2A timeout defaults, and references to demo Prompt, CSV and RPT resources.
Exact role prompts now live in `gateway/prompts/roles.toml`; Grounding/RPT
prompts remain in `gateway/prompts/runtime.toml`. Resources resolve relative
to the backend directory, independently of the current working directory.

Both services must restart after source YAML/TOML configuration or Prompt edits. For Docker,
rebuild and recreate the services because configuration is copied into the
image. Existing `LLM_MODEL`, deployment/address settings and credentials
remain environment-based. `DEMO_TEAM_TASK_TIMEOUT` and
`JOULE_CLI_TIMEOUT_SECONDS` override the corresponding Profile defaults;
configure both services consistently. Invalid identities, references, contracts,
budgets, timeouts or missing resources raise `invalid_harness_profile`.

`GET /api/harness-profile` returns the default Profile ID/schema version,
public Agent configuration, Tool permissions/contracts and runtime limits. Its
timeout values include existing environment overrides. The response excludes
credentials, model authentication settings and internal resource paths. It is
read-only. Harness Studio editing APIs save validated immutable revisions in
shared SQLite storage; new requests apply them without restart. Profile switching
is not implemented. Public A2A/SSE contracts, Tool implementations/calculations
and the Harness Guide drawing remain unchanged. See demo/README.md for Studio
management endpoints, persistence, Evaluation and human-input semantics.

Successful Orchestrator completion now creates a read-only A2A-compatible final Synthesis Artifact with TextPart and DataPart content. The artifact retains the model-generated answer, verified SOP references, completed Team findings, calculations and Task/handoff provenance. It is emitted as `orchestrator_artifact_created` and returned in `result.synthesis_artifact`; original Team artifacts remain in `result.artifacts`. Failed reviews return no final synthesis. This first Guide-alignment change preserves the existing final Chat → final RPT → complete sequence.

Final RPT also receives the final Synthesis Artifact. Its English task-state prompt includes the Orchestrator conclusion, SOP source IDs and provenance references alongside the original SOP and Team evidence. Nested evidence is referenced rather than duplicated. The initial RPT input and final Chat → final RPT → complete order are preserved.

Start the shared Team server and Django Gateway in separate terminals from the repository root:

```bash
.venv/bin/python demo/backend/manage.py runserver 8080
PYTHONPATH=demo/backend .venv/bin/python -m gateway.team_server
```

The Gateway discovers twelve Team Cards over HTTP and delegates structured A2A tasks. The Team server owns LLM Specialist delegation, native function calling, and synthesis. Both services use the configured AICORE credentials and LLM_MODEL. All runtime resources and CSV samples are demo-owned. See ../README.md for the collaboration flow and evaluation commands.

Every operational review requires source-bound SOP Grounding. The Orchestrator selects the search query through native function calling, then uses the verified procedures and accumulated evidence to choose Team handoffs or finish the review. Team Assistants select Specialists with the LLM; Specialists choose authorized Tools and arguments with native function calling. No business keyword selects an Agent or substitutes a failed model decision. Code validates contracts, permissions and execution limits, and stops the review when applicable SOP evidence cannot be verified. CSV entity matching and profitability arithmetic are Tool implementations, not Agent routing rules.

DEMO_TEAM_BASE_URL defaults to http://127.0.0.1:8091 and must match the Team server advertised address. DEMO_TEAM_PORT controls its listening port; DEMO_TEAM_TASK_TIMEOUT defaults to 240 seconds. Agent Cards are exposed at /agents/{team_id}/.well-known/agent-card.json and streaming JSON-RPC at /agents/{team_id}/.

Studio model selection lists running GPT chat-completions deployments compatible
with the native function-call adapter; embedding/image/realtime and other vendor
endpoints are excluded. Authentication and address overrides stay environment-only.
