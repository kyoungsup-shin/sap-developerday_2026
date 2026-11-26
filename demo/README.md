# A2A frontend/backend demo

This folder independently implements the collaboration behavior explained in the A2A lesson. All Agent prompts, Tools, sample CSV records, and Team runtime code belong to demo.

## Local development

From the repository root, use three terminals. Configure AI Core credentials and the model/deployment in the repository .env. The shared Team server defaults to port 8091; DEMO_TEAM_BASE_URL must match its advertised address. Both Gateway and Team server use AI Core.

To enable the optional read-only Joule Work Agent handoff, also configure `SAP_RPT_API_KEY`, `JOULE_SOLUTION_ID`, and `JOULE_ASSET_NAME`. The backend first calls `jl solution list --json` and verifies that the configured Solution ID is deployed, then calls `jl a2a card` and `jl a2a message` when RPT returns `delegate_now`. Install and authenticate the Joule Studio CLI (`jl login`) on the backend host. No Joule call is made for evidence or human-approval decisions.

```bash
# 1. Start the shared Team server (12 independent Agent Card/Task endpoints)
PYTHONPATH=demo/backend .venv/bin/python -m gateway.team_server

# 2. Start the Django Gateway
.venv/bin/python demo/backend/manage.py runserver 8080

# 3. Start the React SPA
cd demo/frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). The SPA calls the gateway at `/api`, which Vite proxies to port 8080; the gateway keeps the A2A event stream open and emits it to the browser as SSE.

## Docker

Docker Compose starts the React SPA, Django Gateway, and the internal-only Team Agent server. It reads the existing repository-root `.env` at runtime; credentials are not copied into an image. The browser reaches only the SPA at `http://localhost:5173`; Nginx proxies `/api` to the Gateway, while the Team server remains on the Compose network.

```bash
./demo/run.sh
```

Choose `Run existing images` or `Rebuild images and run` in the interactive menu:

```bash
./demo/run.sh
```

Useful checks after startup:

```bash
curl http://localhost:5173/api/agents
docker compose -f demo/docker-compose.yml ps
```

## Kyma

Kyma deployment manifests, SAP IAS OIDC proxy setup, persistent SQLite state,
and image build/deploy instructions are in [deploy/kyma/README.md](deploy/kyma/README.md).
Docker Compose remains the local-development path.

## API

- `GET /api/harness-profile` inspects the default Harness configuration and effective runtime limits without credentials or internal paths.
- `GET /api/agents` returns public metadata for all 12 Team Agents.
- `POST /api/chat/stream` accepts `{ "message": "...", "session_id": "optional" }` and streams `text/event-stream` events.
- `GET /healthz` and `GET /readyz` provide process/configuration checks.

The Orchestrator discovers Cards at /agents/{team_id}/.well-known/agent-card.json and delegates using SDK JSON-RPC streaming at /agents/{team_id}/. The Team server owns Specialist selection, native read-only Tool calls, and Team synthesis. Each Task carries a unique handoff ID and the Chat session context ID.

The default fnb-default Profile lives in backend/config/harness/fnb-default.yaml.
It provides the code-registered default Agent roles, Tool contracts, budgets and
resource references. Open **Harness Studio** to manage Agents & A2A,
Prompts & Models, Tools & Data, Grounding, Runtime & Decisions, and Evaluation.
Saved changes are validated and apply to new requests without a restart.
Source YAML/TOML edits still require rebuilding/restarting both services.
Chat layout and the Harness Guide drawing are preserved.

Gateway writes immutable SQLite settings revisions under DEMO_HARNESS_STATE_DIR
(default backend/data/harness_state). Team server reads the same store.
Docker mounts harness-state read/write on Gateway and read-only on Team server.
Concurrent stale saves return 409 and preserve the saved revision. Every request
pins one revision, including Card discovery and A2A Task inputs. Prompts,
permissions, CSV evidence and calculations use that revision. Credentials are
never editable or returned by configuration endpoints.

Tool implementations and required argument contracts remain code-registered.
Studio edits their LLM descriptions, permissions and supported evidence domains;
it does not upload executable Tool code. Data editing/CSV preview validates the
existing four dataset contracts and Context relationships. All operational reviews
still require verified SOP Grounding. Per-Agent models must be running AI Core GPT chat-completions
deployments compatible with this native Tool adapter; shared model/address/timeout environment overrides remain.
External registration supports existing streaming A2A 1.0 JSON-RPC Agents and
standard Text/Data Artifacts at the explicitly registered endpoint. Authentication
for external services is not configured through this editor.

Runtime human review defaults to advisory. With require_input, the final RPT
assessment can create a persisted input checkpoint. Chat shows an input action;
submission starts a new root reassessment with prior Artifacts and the original
settings revision. This does not resume completed Team Tasks or execute a
business approval. The stream explicitly reports input_required.

Evaluation runs are sequential with isolated sessions and a pinned revision.
Studio manages scenario requests/assertions, five category weights totaling 100,
timeouts and pass threshold. Runs retain partial evidence after a failure or
restart, report final Chat/RPT/Tool traces, and assess Joule availability separately.
Reports persist in DEMO_EVALUATION_DIR (default backend/data/evaluations);
Docker uses the harness-evaluations volume. A shared process lease prevents
overlapping runs. API-key/token patterns are redacted from evaluation traces
and still counted as defects. Configurable weights never bypass final Chat,
English output, final RPT lifecycle or successful termination requirements.

Management APIs:

- GET/POST /api/harness/prompts: role Prompt/model edits with expected_revision.
- GET /api/harness/models: discover running AI Core deployments.
- GET/POST /api/harness/configuration: inspect/save one validated section.
- GET /api/harness/agent-card?agent_id=...: validate a registered Card.
- POST /api/harness/data/preview: parse a replacement CSV without saving.
- GET/POST /api/harness/evaluations: history / start selected saved scenarios.
- GET /api/harness/evaluations/{id}: progress, scores and recorded evidence.
- GET /api/chat/input?session_id=...: retrieve pending human input.
- POST /api/chat/stream: optional settings_revision; human_review_id plus
  original session_id submits input using its persisted checkpoint.

See backend/README.md for server commands and environment configuration.

Every request must retrieve applicable, source-bound SOP Grounding before RPT/Joule or Team review. Missing or failed SOP evidence stops the business review with a safe error; it does not fall back to CSV-only review. The Orchestrator applies SOP requirements and chooses up to three Team handoffs with the LLM. Specialists have three Tool turns, reuse duplicate normalized calls, and consume role-scoped records under demo/backend/data/snapshots. These are newly authored fictional English samples, not live SAP data or lesson CSV copies.

RPT/Joule are optional extensions before Team execution; they never choose the next Team. Final Chat is followed by final RPT success/failure and stream completion. A failed Team Task does not become an evidence Artifact. Configure DEMO_TEAM_TASK_TIMEOUT (default 240 seconds) for the server and Gateway transport. Gateway SSE keep-alives remain active during provider waits.

Verification: run backend gateway tests, npm run build in demo/frontend, then demo/backend/scripts/evaluate_scenarios.py against an isolated Gateway. The evaluator requires SOP Grounding before the initial RPT and Team work, and preserves actual HTTP Task, Tool, Artifact, final Chat, and RPT evidence.
