import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import jouleLogo from "./assets/joule.png";
import sapLogo from "./assets/sap_logo.png";
import { readableChatText, splitReviewDetails } from "./reviewText";
import HarnessLearningPage from "./HarnessLearningPage";
import HarnessStudio from "./HarnessStudio";
import "./prompt-view.css";

type Agent = {
  agent_id: string;
  agent_label: string;
  skill_id: string;
  description: string;
  sub_agents: string[];
};
type AgentPrompt = {
  label: string;
  system_prompt: string;
  agent_id?: string;
  prompt_key?: string;
};
type PromptCatalog = {
  orchestrator: AgentPrompt;
  team_agents: AgentPrompt[];
  specialist_agents: AgentPrompt[];
};
type GroundingConfig = {
  configured: boolean;
};
type GroundingAnswer = {
  query: string;
  answer: string;
  source: string;
  metadata_available: boolean;
  message: string;
};
type GroundingDocument = { id: string; name: string };
type ToolDefinition = {
  name: string;
  description: string;
  required_parameter: string;
  mode: "read-only";
  source: string;
  inputs?: { name: string; type: string; required: boolean; description: string; example: string }[];
  policy_note?: string;
};
type DataSnapshot = {
  name: string;
  view_name: string;
  rows: number;
  columns: string[];
  mode: "read-only";
  source: string;
  product_name: string;
  domain: string;
  description: string;
  owner: string;
  refresh: string;
};
type DataSnapshotDetail = {
  name: string;
  view_name: string;
  columns: string[];
  rows: Record<string, string>[];
  limit: number;
  mode: "read-only";
  product_name: string;
  domain: string;
  description: string;
  owner: string;
  refresh: string;
};
type TimelineEvent = {
  type: string;
  at: string;
  data: Record<string, unknown>;
};
type OrchestrationObservation = {
  completedWork: string[];
  newEvidence: string[];
  unresolvedDecisions: string[];
  availableCapabilities: string[];
  decisionFocus: string[];
  summary: string;
};
type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  body: string;
  time: string;
  actor?: "orchestrator" | "team" | "subagent" | "joule";
  agentName?: string;
  loading?: boolean;
  kind?: "grounding" | "rptDecision" | "event" | "observation";
  systemEvent?: {
    category: string;
    title: string;
    detail: string;
    icon: string;
    tone: "handoff" | "progress" | "received" | "complete";
    toolCall?: { input: unknown; output: unknown; domains: string[] };
  };
  grounding?: {
    source: string;
    sopSources?: string[];
    originalSopSources?: string[];
    metadataAvailable: boolean;
    message: string;
    preview: string;
  };
  rptDecision?: {
    nextAgent: string;
    nextAgentLabel?: string;
    handoffMode: string;
    risk: string;
    priority: string;
    groundingUsed?: boolean;
    final?: boolean;
    teamRankings?: { agentId: string; agentLabel?: string; score: number }[];
  };
  observation?: OrchestrationObservation;
  observationStep?: number;
  toolCalls?: {
    specialist: string;
    name: string;
    domains: string[];
    input: unknown;
    output: unknown;
    time: string;
  }[];
};
type TypingAgent = {
  id: string;
  label: string;
  role: "orchestrator" | "team" | "subagent";
};
type StudioSection = "grounding" | "chat" | "agents" | "tools" | "toolCalling" | "data" | "harnessStudio";
const scenarios: { title: string; request: string }[] = [
    { title: "Additional order for existing raw materials", request: "Please place an additional order for strawberry concentrate." },
    { title: "Replenishment purchase for existing equipment consumables", request: "Please purchase a CIP pump mechanical seal kit." },
    { title: "Business impact assessment for exchange-rate and raw-material price changes", request: "Please review how recent exchange-rate and raw-material price changes could affect the profitability of lemon carbonated beverages next quarter." },
    { title: "Register and introduce a new raw material into production", request: "We plan to use allulose sweetener in the next production run. Please proceed with the required process." },
    { title: "Change the production-line cost center", request: "Please change the Cost Center for Beverage Line 1 starting next quarter." },
];
const labels: Record<string, string> = {
  field_handoff_received: "Request received",
  orchestration_observation: "Context observed",
  orchestration_decision: "Route selected",
  team_handoff_started: "Agent handoff",
  a2a_task_update: "Task status",
  grounding_started: "Grounding started",
  grounding_failed: "Grounding unavailable",
  agent_cards_discovery_started: "Discovering Team Cards",
  agent_cards_discovered: "Team Cards verified",
  team_handoff_failed: "Team review failed",
  tool_input_rejected: "Tool request being corrected",
  grounding_completed: "Grounding retrieved",
  delegation_started: "Team delegation",
  delegation_selected: "Specialists selected",
  subagent_started: "Specialist started",
  subagent_completed: "Specialist completed",
  artifact_received: "Evidence received",
  complete: "Run complete",
  rpt_decision_started: "RPT decision started",
  rpt_decision_completed: "RPT decision completed",
  rpt_decision_failed: "RPT decision unavailable",
  rpt_final_decision_started: "Final RPT decision started",
  rpt_final_decision_completed: "Final RPT decision completed",
  rpt_final_decision_failed: "Final RPT decision unavailable",
  joule_card_verification_started: "Joule Card verification",
  joule_card_verified: "Joule Card verified",
  joule_handoff_started: "Joule handoff started",
  joule_handoff_skipped: "Joule handoff skipped",
  joule_handoff_failed: "Joule handoff failed",
  joule_artifact_received: "Joule artifact received",
};
const agentId = (event: TimelineEvent) =>
  typeof event.data.agent_id === "string" ? event.data.agent_id : undefined;

function rptStageStatus(events: TimelineEvent[], final: boolean): { state: "idle" | "running" | "complete" | "failed"; decision?: Record<string, unknown> } {
  const prefix = final ? "rpt_final_decision_" : "rpt_decision_";
  const latest = [...events].reverse().find((event) => event.type.startsWith(prefix));
  if (!latest) return { state: "idle" };
  if (latest.type === prefix + "completed") return { state: "complete", decision: latest.data.decision as Record<string, unknown> | undefined };
  return { state: latest.type === prefix + "failed" ? "failed" : "running" };
}

function narration(
  kind: string,
  data: Record<string, unknown>,
  agents: Agent[],
) {
  const name = (id: unknown) =>
    agents.find((agent) => agent.agent_id === id)?.agent_label ??
    String(id ?? "responsible team");
  if (kind === "field_handoff_received")
    return "Request received. Identifying the relevant business domains and responsible teams.";
  if (kind === "grounding_started") return "Retrieving relevant SOPs and operational evidence from the Grounding Repository…";
  if (kind === "grounding_completed") return undefined;
  if (kind === "grounding_failed" || kind === "team_handoff_failed") return String(data.message ?? "The review could not be completed.");
  if (kind === "rpt_decision_started") return "Evaluating handoff conditions with SAP RPT Decision…";
  if (kind === "rpt_decision_completed") return undefined;
  if (kind === "rpt_decision_failed") return `RPT decision is unavailable: ${String(data.message)}`;
  if (kind === "rpt_final_decision_started") return "Evaluating the completed review with SAP RPT Decision…";
  if (kind === "rpt_final_decision_completed") return undefined;
  if (kind === "rpt_final_decision_failed") return `Final RPT decision is unavailable: ${String(data.message)}`;
  if (kind === "joule_card_verification_started") return "Verifying the Joule Work Agent Card…";
  if (kind === "joule_card_verified") return "Joule Work Agent Card verified. Starting the read-only handoff.";
  if (kind === "joule_handoff_started") return "[JOULE WORK AGENT] A2A request sent…";
  if (kind === "joule_handoff_skipped") return `Joule handoff skipped: ${String(data.reason)}.`;
  if (kind === "joule_handoff_failed") return `Joule handoff could not be completed: ${String(data.message)}`;
  if (kind === "joule_artifact_received") {
    const artifact = data.artifact as Record<string, unknown>;
    return "### Joule Work Agent review\n\n" + readableChatText(JSON.stringify(artifact.result ?? {}));
  }
  if (kind === "orchestration_observation") return undefined;
  if (kind === "orchestration_decision") {
    const decision = data.decision as Record<string, unknown> | undefined;
    return decision?.action === "complete"
      ? undefined
      : `Requesting a review from ${name(decision?.target_agent_id)}.`;
  }
  if (kind === "team_handoff_started") return undefined;
  if (kind === "team_message_delta")
    return String(data.delta ?? "");
  if (kind === "delegation_started" || kind === "delegation_selected") return undefined;
  if (kind === "subagent_started") return undefined;
  if (kind === "subagent_message_delta") return String(data.delta ?? "");
  if (kind === "orchestrator_message_delta") return String(data.delta ?? "");
  if (kind === "artifact_received") return undefined;
}

function MarkdownMessage({ body, toolCalls, formatStructured = true }: { body: string; toolCalls?: ChatMessage["toolCalls"]; formatStructured?: boolean }) {
  const content = body.replace(/^\[TEAM AGENT · [^\]]+\]\n?/, "");
  const review = formatStructured ? splitReviewDetails(readableChatText(content)) : { answer: content, details: [] };
  return <>
    {(toolCalls?.length || review.details.length) ? <div className="message-review-timeline">
      <MessageToolCalls calls={toolCalls ?? []} />
      {review.details.map((section, index) => <details className="review-timeline-entry" key={index}>
        <summary><span>{section.title}</span><i aria-hidden="true">⌄</i></summary>
        <div className="review-timeline-entry__content"><div className="message-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown></div></div>
      </details>)}
    </div> : null}
    {review.answer && <div className="message-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{review.answer}</ReactMarkdown></div>}
  </>;
}

function SystemPromptText({ prompt }: { prompt: string }) {
  const lines = prompt.replace(/\r\n/g, "\n")
    .split(/\n\s*\n/)
    .flatMap((paragraph, index) => [
      ...(index ? [""] : []),
      ...paragraph.replace(/\n/g, " ").trim().split(/(?<=[.!?])\s+(?=[A-Z])/g),
    ]);
  let lineNumber = 0;
  return <ol className="system-prompt" aria-label="System prompt text">
    {lines.map((line, index) => {
      const number = line ? String(++lineNumber).padStart(2, "0") : "";
      return <li key={`${index}-${line.slice(0, 16)}`} data-line={number} className={line ? "" : "blank"}>{line || " "}</li>;
    })}
  </ol>;
}

type DataFrameSection = { title: string; rows: Record<string, unknown>[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function dataFrameCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function displayLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function dataFrameSections(value: unknown): DataFrameSection[] {
  if (Array.isArray(value)) {
    return [{ title: "OUTPUT", rows: value.map((item) => isRecord(item) ? item : { value: item }) }];
  }
  if (!isRecord(value)) return [{ title: "OUTPUT", rows: [{ value }] }];

  const sections: DataFrameSection[] = [];
  const overview = Object.fromEntries(Object.entries(value).filter(([, item]) => !Array.isArray(item) && !isRecord(item)));
  const overviewTitle = typeof value.context_id === "string" || typeof value.CONTEXT_ID === "string"
    ? "Retrieved evidence"
    : value.lookup === "business_context" || Array.isArray(value.matches)
      ? "Matching business records"
      : "Tool summary";
  if (Object.keys(overview).length) sections.push({ title: overviewTitle, rows: [overview] });
  for (const [key, item] of Object.entries(value)) {
    if (Array.isArray(item)) {
      sections.push({ title: key.replaceAll("_", " ").toUpperCase(), rows: item.map((entry) => isRecord(entry) ? entry : { value: entry }) });
    } else if (isRecord(item)) {
      if (key === "evidence_by_domain") {
        // This is an adapter envelope, not a business-data category.
        // Unwrap it so a reader sees useful domain and dataset names.
        for (const [domain, evidence] of Object.entries(item)) {
          if (!isRecord(evidence)) continue;
          const recordsBySnapshot = evidence.datasets ?? evidence.records_by_snapshot;
          if (isRecord(recordsBySnapshot)) {
            for (const [snapshot, records] of Object.entries(recordsBySnapshot)) {
              if (Array.isArray(records)) sections.push({ title: `${displayLabel(domain)} · ${displayLabel(snapshot)}`, rows: records.map((entry) => isRecord(entry) ? entry : { value: entry }) });
            }
          }
          if (Array.isArray(evidence.status_tokens)) {
            sections.push({ title: `${displayLabel(domain)} · Status checks`, rows: evidence.status_tokens.map((entry) => isRecord(entry) ? entry : { value: entry }) });
          }
        }
      } else if (key === "records_by_snapshot" || key === "datasets") {
        for (const [snapshot, records] of Object.entries(item)) {
          if (Array.isArray(records)) sections.push({ title: `DATASET · ${displayLabel(snapshot)}`, rows: records.map((entry) => isRecord(entry) ? entry : { value: entry }) });
        }
      } else {
        sections.push({ title: displayLabel(key), rows: [item] });
      }
    }
  }
  return sections.length ? sections : [{ title: "OUTPUT", rows: [{ value }] }];
}

function ToolOutputDataFrames({ output }: { output: unknown }) {
  return <div className="tool-output-frames">
    {dataFrameSections(output).map((section) => {
      const columns = Array.from(new Set(section.rows.flatMap((row) => Object.keys(row))));
      return <section className="tool-dataframe" key={section.title}>
        <b>{section.title}</b>
        {section.rows.length === 0 ? <p>No rows returned.</p> : <div className="tool-dataframe__scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{section.rows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((column) => <td key={column}>{dataFrameCell(row[column])}</td>)}</tr>)}</tbody></table></div>}
      </section>;
    })}
  </div>;
}

function MessageToolCalls({ calls }: { calls: NonNullable<ChatMessage["toolCalls"]> }) {
  if (!calls.length) return null;
  return <div className="message-tool-calls">
    {calls.map((call, index) => <details className="message-tool-call" key={`${call.name}-${index}`}>
      <summary>
        <span>⌘</span><b>READ-ONLY TOOL</b><time>{call.time}</time>
        <strong>{call.specialist} · {call.name}{call.domains.length ? ` · ${call.domains.join(", ")}` : ""}</strong><i aria-hidden="true">⌄</i>
      </summary>
      <div className="message-tool-call__detail">
        <section><b>INPUT</b><pre>{JSON.stringify(call.input, null, 2)}</pre></section>
        {call.domains.length > 0 && <section><b>APPLIED DOMAINS</b><pre>{JSON.stringify(call.domains, null, 2)}</pre></section>}
        <section><b>OUTPUT · DATAFRAME</b><ToolOutputDataFrames output={call.output} /></section>
      </div>
    </details>)}
  </div>;
}

function SystemEventCard({ event, time }: { event: NonNullable<ChatMessage["systemEvent"]>; time: string }) {
  const summary = <article className={`system-event ${event.tone}`} role="status" aria-label={`${event.title}. ${event.detail}`}>
    <span className="system-event__icon">{event.icon}</span>
    <b>{event.category}</b><time>{time}</time><span>{event.title}</span>
  </article>;
  if (!event.toolCall) return summary;
  return <details className="tool-observation">
    <summary>{summary}<i aria-hidden="true">⌄</i></summary>
    <div className="tool-observation__detail">
      <p>{event.detail}</p>
      <section><b>INPUT</b><pre>{JSON.stringify(event.toolCall.input, null, 2)}</pre></section>
      {event.toolCall.domains.length > 0 && <section><b>APPLIED DOMAINS</b><pre>{JSON.stringify(event.toolCall.domains, null, 2)}</pre></section>}
      <section><b>OUTPUT · DATAFRAME</b><ToolOutputDataFrames output={event.toolCall.output} /></section>
    </div>
  </details>;
}

function observationFrom(value: unknown): OrchestrationObservation {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const list = (field: string) => Array.isArray(source[field])
    ? source[field].filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
  return {
    completedWork: list("completed_work"),
    newEvidence: list("new_evidence"),
    unresolvedDecisions: list("unresolved_decisions"),
    availableCapabilities: list("available_capabilities"),
    decisionFocus: list("decision_focus"),
    summary: typeof source.chat_summary === "string" ? source.chat_summary : "Observed the operational context for this request.",
  };
}

function ObservationResult({ result, step }: { result: OrchestrationObservation; step?: number }) {
  const compactList = (items: string[]) => items.length ? <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>No items were identified.</p>;
  return <section className="observation-result">
    <header><span>◉</span><div><p className="kicker">OBSERVE {step ? `· STEP ${step}` : ""}</p><b>Current assessment</b></div></header>
    <p className="observation-result__summary">{result.summary}</p>
    <div className="observation-result__focus"><section><span>UNRESOLVED</span>{compactList(result.unresolvedDecisions)}</section><section><span>DECISION FOCUS</span>{compactList(result.decisionFocus)}</section></div>
    <details><summary>View evidence</summary><div className="observation-result__details"><section><span>COMPLETED</span>{compactList(result.completedWork)}</section><section><span>NEW EVIDENCE</span>{compactList(result.newEvidence)}</section><section><span>CAPABILITIES</span>{compactList(result.availableCapabilities)}</section></div></details>
  </section>;
}

function GroundingResult({ result }: { result: NonNullable<ChatMessage["grounding"]> }) {
  return <section className="grounding-result">
    <div className="grounding-result__header">
      <span className="grounding-result__icon">◌</span>
      <div><p className="kicker">GROUNDING RESULT · READ ONLY</p><b>{result.sopSources?.length ? "Verified SOP context" : "Retrieved business context"}</b></div>
      <span className="grounding-result__status">{result.metadataAvailable ? "METADATA READY" : "CONTEXT READY"}</span>
    </div>
    <dl>
      <div><dt>Source</dt><dd>{result.source}</dd></div>
      <div><dt>Status</dt><dd>{result.message}</dd></div>
      {Boolean(result.sopSources?.length) && <div><dt>SOP sources</dt><dd>{result.sopSources?.join(" · ")}</dd></div>}
    </dl>
    {Boolean(result.originalSopSources?.length) && <details className="grounding-references">
      <summary><span>View original SOP references</span><i aria-hidden="true">⌄</i></summary>
      <ul>{result.originalSopSources?.map((source, index) => <li key={index}>
        <span className="grounding-references__id">{result.sopSources?.[index] ?? '#' + (index + 1)}</span>
        <span className="grounding-references__title">{source}</span>
      </li>)}</ul>
    </details>}
    <p className="grounding-result__label">Context excerpt</p>
    <div className="grounding-result__preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.preview || "No context excerpt returned."}</ReactMarkdown>
    </div>
  </section>;
}

function RptDecisionResult({ result }: { result: NonNullable<ChatMessage["rptDecision"]> }) {
  const riskScore = result.risk === "high" ? 100 : result.risk === "medium" ? 66 : 33;
  const rawPriority = Number(result.priority);
  const priorityScore = Number.isFinite(rawPriority) ? Math.max(0, Math.min(100, (rawPriority / 2) * 100)) : 0;
  const humanLevel = result.handoffMode === "request_human_approval" ? "high" : result.handoffMode === "request_evidence" ? "medium" : "low";
  const humanScore = humanLevel === "high" ? 100 : humanLevel === "medium" ? 66 : 33;
  const handoffLabels: Record<string, string> = {
    delegate_now: "Delegate now", request_evidence: "Request evidence", request_human_approval: "Human approval",
  };
  const rankedTeams = result.teamRankings?.length
    ? result.teamRankings
    : [{ agentId: result.nextAgent, agentLabel: result.nextAgentLabel, score: 100 }];
  const assistantLabel = (label: string | undefined, fallback: string) => {
    const value = label ?? fallback;
    return value.endsWith("Assistant") ? value : `${value} Assistant`;
  };
  return <section className="rpt-result">
    <div className="rpt-result__header"><span className="rpt-result__icon">◈</span><div><p className="kicker">{result.final ? "FINAL RPT DECISION MODEL · READ ONLY" : "RPT DECISION MODEL · READ ONLY"}</p><b>Operational assessment</b></div><div className="rpt-result__badges">{result.groundingUsed && <span className="rpt-result__grounded">GROUNDED EVIDENCE USED</span>}<span className="rpt-result__status">EVALUATED</span></div></div>
    {!result.final && <><div className="rpt-result__choices" style={{ gridTemplateColumns: "1fr" }}><div><span>Handoff</span><b>{handoffLabels[result.handoffMode] ?? result.handoffMode.replaceAll("_", " ")}</b></div></div><section className="rpt-result__ranking"><p>Top 3 Team Assistant routing fit</p>{rankedTeams.map((team, index) => <div key={team.agentId}><span>#{index + 1} · {assistantLabel(team.agentLabel, team.agentId.replaceAll("-", " "))}</span><b>{team.score}</b><i><em style={{ width: team.score + "%" }} /></i></div>)}</section></>}
    <div className="rpt-result__chart" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }} role="img" aria-label={"Human review " + humanLevel + ", RPT risk " + result.risk + ", priority " + result.priority}>
      <div className="rpt-result__metric"><div><span>Human in the loop</span></div><div className="rpt-result__track"><i className={"risk " + humanLevel} style={{ width: humanScore + "%" }} /></div><small>LOW <em>MEDIUM</em> HIGH</small></div>
      <div className="rpt-result__metric"><div><span>Operational risk</span><b>{result.risk}</b></div><div className="rpt-result__track"><i className={"risk " + result.risk} style={{ width: riskScore + "%" }} /></div><small>LOW <em>MEDIUM</em> HIGH</small></div>
      <div className="rpt-result__metric"><div><span>Priority</span><b>{result.priority} <small>/ 2</small></b></div><div className="rpt-result__track"><i className="priority" style={{ width: priorityScore + "%" }} /></div><small>CAN WAIT <em>THIS WEEK</em> TODAY</small></div>
    </div>
  </section>;
}

const hasKoreanGeneratedText = (messages: unknown[]) => messages.some((value) => {
  if (!value || typeof value !== "object") return false;
  const message = value as ChatMessage;
  if (message.role === "user") return false;
  // Original SOP references and raw Tool data retain their source language.
  return /[가-힣]/.test(JSON.stringify({
    body: message.body, agentName: message.agentName, observation: message.observation,
    rptDecision: message.rptDecision, specialistNames: message.toolCalls?.map((call) => call.specialist),
    groundingPreview: message.grounding?.preview, groundingMessage: message.grounding?.message,
    systemTitle: message.systemEvent?.title, systemDetail: message.systemEvent?.detail,
  }));
});

function HarnessConsole() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [selectedTool, setSelectedTool] = useState<ToolDefinition>();
  const [toolModalOpen, setToolModalOpen] = useState(false);
  const [dataSnapshots, setDataSnapshots] = useState<DataSnapshot[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<DataSnapshotDetail>();
  const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");
  const [prompts, setPrompts] = useState<PromptCatalog>();
  const [groundingConfig, setGroundingConfig] = useState<GroundingConfig>();
  const [groundingQuestion, setGroundingQuestion] = useState("");
  const [groundingAnswer, setGroundingAnswer] = useState<GroundingAnswer>();
  const [groundingLoading, setGroundingLoading] = useState(false);
  const [groundingError, setGroundingError] = useState("");
  const [groundingTab, setGroundingTab] = useState<"ground" | "documents">("ground");
  const [groundingDocuments, setGroundingDocuments] = useState<GroundingDocument[]>([]);
  const [groundingDocumentsLoading, setGroundingDocumentsLoading] = useState(false);
  const [groundingDocumentsError, setGroundingDocumentsError] = useState("");
  const [promptsLoading, setPromptsLoading] = useState(true);
  const [promptsError, setPromptsError] = useState("");
  const [selectedPromptId, setSelectedPromptId] = useState("orchestrator");
  const [promptModalOpen, setPromptModalOpen] = useState(false);
  useEffect(() => {
    if (!promptModalOpen) return;
    const trigger = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>(".prompt-modal");
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPromptModalOpen(false);
      if (event.key !== "Tab" || !dialog) return;
      const buttons = Array.from(dialog.querySelectorAll<HTMLButtonElement>("button:not([disabled])"));
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); if (trigger?.isConnected) trigger.focus(); };
  }, [promptModalOpen]);
  const [jouleCardVerified, setJouleCardVerified] = useState(false);
  const [jouleCard, setJouleCard] = useState<Record<string, unknown>>();
  const [jouleCardLoading, setJouleCardLoading] = useState(false);
  const [jouleCardError, setJouleCardError] = useState("");
  const latestRptDecision = useRef<NonNullable<ChatMessage["rptDecision"]> | undefined>(undefined);
  const [message, setMessage] = useState("");
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [humanReview, setHumanReview] = useState<{ id: string; handoff_mode: string }>();
  const [sessionId, setSessionId] = useState<string>(() => {
    const saved = window.sessionStorage.getItem("a2a-demo-session-id");
    return saved && saved.length <= 128 ? saved : crypto.randomUUID();
  });
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [chat, setChat] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      body: "Hello. Send an operational request and the Harness will select relevant Team Agents and record their collaboration.",
      time: "READY",
    },
  ]);
  const [typingAgents, setTypingAgents] = useState<TypingAgent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [metadataEpoch, setMetadataEpoch] = useState(0);
  const [studioVisited, setStudioVisited] = useState(false);
  const [section, setSection] = useState<StudioSection>("chat");
  const [agentNetworkTab, setAgentNetworkTab] = useState<"local" | "joule">("local");
  const [railExpanded, setRailExpanded] = useState(true);
  const aborter = useRef<AbortController | undefined>(undefined);
  const pendingToolCalls = useRef<Record<string, NonNullable<ChatMessage["toolCalls"]>>>({});
  const teamStartMessageIds = useRef<Record<string, string>>({});
  const loadPrompts = useCallback(async () => {
    setPromptsLoading(true);
    setPromptsError("");
    try {
      const response = await fetch("/api/prompts");
      if (!response.ok) throw new Error("Could not load system prompts.");
      setPrompts((await response.json()) as PromptCatalog);
    } catch {
      setPromptsError("Could not load system prompts.");
    } finally {
      setPromptsLoading(false);
    }
  }, []);
  const loadJouleCard = useCallback(async () => {
    setJouleCardLoading(true);
    setJouleCardError("");
    try {
      const response = await fetch("/api/joule-agent-card");
      const payload = (await response.json()) as { card?: Record<string, unknown>; detail?: string };
      if (!response.ok || !payload.card) throw new Error(payload.detail ?? "Could not load the Agent Card.");
      setJouleCard(payload.card);
      setJouleCardVerified(true);
    } catch (cause) {
      setJouleCardError(cause instanceof Error ? cause.message : "Could not load the Agent Card.");
    } finally {
      setJouleCardLoading(false);
    }
  }, []);
  useEffect(() => {
    if (!sessionId) { setHumanReview(undefined); return; }
    const controller = new AbortController();
    void fetch("/api/chat/input?session_id=" + encodeURIComponent(sessionId), { signal: controller.signal }).then(async (response) => {
      if (response.ok) { const value = await response.json() as { review?: { id: string; handoff_mode: string } }; if (!controller.signal.aborted) setHumanReview(value.review ?? undefined); }
    }).catch(() => undefined);
    return () => controller.abort();
  }, [sessionId]);
  useEffect(() => { if (section === "harnessStudio") setStudioVisited(true); }, [section]);
  useEffect(() => {
    fetch("/api/agents")
      .then(async (response) => setAgents((await response.json()) as Agent[]))
      .catch(() => setError("Could not load the Agent catalog."));
  }, [metadataEpoch]);
  useEffect(() => {
    window.sessionStorage.setItem("a2a-demo-session-id", sessionId);
  }, [sessionId]);
  const openSnapshot = useCallback(async (name: string) => {
    setSnapshotModalOpen(true);
    setSelectedSnapshot(undefined);
    setSnapshotError("");
    setSnapshotLoading(true);
    try {
      const response = await fetch(`/api/data-snapshots/${encodeURIComponent(name)}`);
      if (!response.ok) throw new Error("Could not load the CSV snapshot.");
      setSelectedSnapshot((await response.json()) as DataSnapshotDetail);
    } catch (cause) {
      setSnapshotError(cause instanceof Error ? cause.message : "Could not load the CSV snapshot.");
    } finally {
      setSnapshotLoading(false);
    }
  }, []);
  useEffect(() => {
    fetch("/api/tools")
      .then(async (response) => setTools((await response.json()) as ToolDefinition[]))
      .catch(() => setError("Could not load the Tool Catalog."));
  }, [metadataEpoch]);
  useEffect(() => {
    fetch("/api/data-snapshots")
      .then(async (response) => setDataSnapshots((await response.json()) as DataSnapshot[]))
      .catch(() => setError("Could not load CSV snapshots."));
  }, [metadataEpoch]);
  useEffect(() => {
    fetch("/api/grounding")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load Grounding configuration.");
        const config = (await response.json()) as GroundingConfig;
        setGroundingConfig(config);
      })
      .catch(() => setError("Could not load Grounding configuration."));
  }, [metadataEpoch]);
  useEffect(() => {
    void loadPrompts();
  }, [loadPrompts]);
  useEffect(() => {
    if (section === "agents" && agentNetworkTab === "joule") void loadJouleCard();
  }, [section, agentNetworkTab, loadJouleCard]);
  useEffect(() => {
    document
      .querySelectorAll<HTMLElement>(".legacy-message.assistant")
      .forEach((messageNode) => {
        const text = messageNode.querySelector("p")?.textContent ?? "";
        const match = text.match(/^\[TEAM AGENT · ([^\]]+)\]/);
        const meta = messageNode.querySelector<HTMLElement>(".message-meta");
        if (meta && match)
          meta.firstChild!.textContent = `TEAM AGENT · ${match[1]} `;
      });
  }, [chat]);
  useEffect(() => {
    document
      .querySelectorAll<HTMLElement>(".legacy-message.assistant")
      .forEach((messageNode) => {
        const image = messageNode.querySelector<HTMLImageElement>(
          ".message-avatar img",
        );
        if (image)
          image.src = (
            messageNode.querySelector("p")?.textContent ?? ""
          ).startsWith("[TEAM AGENT")
            ? jouleLogo
            : sapLogo;
      });
  }, [chat]);
  useEffect(() => {
    const render = (value: string) => {
      const escaped = value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      const tables = escaped.replace(/(?:^\|.*\|(?:\n|$)){2,}/gm, (block) => {
        const rows = block
          .trim()
          .split(String.fromCharCode(10))
          .filter((row) => !/^\|?[-:| ]+\|?$/.test(row));
        return `<table>${rows
          .map((row, index) => {
            const cells = row
              .split("|")
              .slice(1, -1)
              .map((cell) => cell.trim());
            const tag = index === 0 ? "th" : "td";
            return `<tr>${cells.map((cell) => `<${tag}>${cell}</${tag}>`).join("")}</tr>`;
          })
          .join("")}</table>`;
      });
      return tables
        .replace(/^### (.+)$/gm, "<h4>$1</h4>")
        .replace(/^## (.+)$/gm, "<h3>$1</h3>")
        .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .split(String.fromCharCode(10))
        .join("<br>");
    };
    document
      .querySelectorAll<HTMLElement>(".legacy-message.assistant p")
      .forEach((node) => {
        if (!node.dataset.markdownRendered) {
          node.innerHTML = render(node.textContent ?? "");
          node.dataset.markdownRendered = "true";
        }
      });
  }, [chat]);
  const active = useMemo(
    () => new Set(events.map(agentId).filter(Boolean)),
    [events],
  );
  const activeSpecialists = useMemo(() => new Set(
    events.flatMap((event) => event.type === "subagent_started" || event.type === "subagent_completed"
      ? [String(event.data.subagent_label ?? "")] : []).filter(Boolean),
  ), [events]);
  const workingTeams = useMemo(() => {
    const working = new Set<string>();
    for (const event of events) {
      const id = agentId(event);
      if (!id) continue;
      if (event.type === "team_handoff_started") working.add(id);
      if (event.type === "team_handoff_failed") working.delete(id);
      if (event.type === "a2a_task_update") {
        const task = event.data.task as Record<string, unknown> | undefined;
        const status = task?.status as Record<string, unknown> | undefined;
        if (["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"].includes(String(status?.state))) working.delete(id);
        if (status?.state === "TASK_STATE_WORKING") working.add(id);
      }
    }
    return working;
  }, [events]);
  const groundingInProgress = events.some((event) => event.type === "grounding_started") && !events.some((event) => event.type === "grounding_completed" || event.type === "grounding_failed");
  const initialRptStatus = useMemo(() => rptStageStatus(events, false), [events]);
  const rptStatus = useMemo(() => rptStageStatus(events, true), [events]);
  const initialHumanReviewRequired = initialRptStatus.decision?.handoff_mode === "request_human_approval";
  const humanReviewRequired = rptStatus.decision?.handoff_mode === "request_human_approval";
  const rptGroundingUsed = initialRptStatus.decision?.grounding_used === true;
  const agentName = (id: unknown) =>
    agents.find((agent) => agent.agent_id === id)?.agent_label ?? "Team Agent";
  const selectedPrompt = useMemo(() => {
    if (!prompts) return undefined;
    if (selectedPromptId === "orchestrator") return prompts.orchestrator;
    return [...prompts.team_agents, ...prompts.specialist_agents].find((agent) => agent.agent_id === selectedPromptId);
  }, [prompts, selectedPromptId]);
  const addTypingAgent = useCallback((agent: TypingAgent) => {
    // A2A execution is sequential in this demo. Replacing, rather than
    // accumulating, the typing indicator makes the active owner explicit.
    setTypingAgents([agent]);
  }, []);
  const removeTypingAgent = useCallback((id: string) => {
    setTypingAgents((previous) => previous.filter((item) => item.id !== id));
  }, []);

  async function send(event: FormEvent) {
    event.preventDefault();
    const prompt = message.trim();
    const runId = crypto.randomUUID();
    if (!prompt || running) return;
    setChat((previous) => [
      ...previous,
      {
        id: crypto.randomUUID(),
        role: "user",
        body: prompt,
        time: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
    ]);
    setTypingAgents([{ id: "orchestrator", label: "ORCHESTRATOR", role: "orchestrator" }]);
    setMessage("");
    setEvents([]);
    setJouleCardVerified(false);
    setJouleCard(undefined);
    latestRptDecision.current = undefined;
    pendingToolCalls.current = {};
    teamStartMessageIds.current = {};
    setRunning(true);
    setError("");
    const controller = new AbortController();
    aborter.current = controller;
    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ message: prompt, session_id: sessionId, language: "en", ...(humanReview ? { human_review_id: humanReview.id } : {}) }),
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => undefined) as { error?: { message?: string }; detail?: string } | undefined;
        throw new Error(payload?.error?.message ?? payload?.detail ?? "Could not start the request.");
      }
      setHumanReview(undefined);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true });
        const packets = buffer.split("\n\n");
        buffer = packets.pop() ?? "";
        for (const packet of packets) {
          const kind = packet.match(/^event: (.+)$/m)?.[1] ?? "update";
          const raw = packet.match(/^data: (.+)$/m)?.[1];
          if (!raw) continue;
          const data = JSON.parse(raw) as Record<string, unknown>;
          if (kind === "session") setSessionId(String(data.session_id));
          else if (kind === "error") {
            setTypingAgents([]);
            setError(String(data.message));
          }
          else {
            const item = {
              type: kind,
              at: new Date().toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              }),
              data,
            };
            setEvents((previous) => [...previous, item]);
            if (kind === "joule_card_verified") {
              setJouleCardVerified(true);
              if (data.card && typeof data.card === "object" && !Array.isArray(data.card))
                setJouleCard(data.card as Record<string, unknown>);
            }
            if (kind === "human_input_required" && typeof data.id === "string") setHumanReview({ id: data.id, handoff_mode: String(data.handoff_mode) });
            const text = narration(kind, data, agents);
            const producer = (
              data.record as Record<string, unknown> | undefined
            )?.producer;
            if (kind === "tool_observation") {
              const specialist = String(data.subagent_label ?? "Specialist");
              const toolKey = `${String(data.handoff_id ?? data.agent_id ?? "team")}:${specialist}`;
              const domains = Array.isArray(data.domains)
                ? data.domains.filter((domain): domain is string => typeof domain === "string")
                : [];
              pendingToolCalls.current[toolKey] = [
                ...(pendingToolCalls.current[toolKey] ?? []),
                { specialist, name: String(data.tool ?? "Tool"), domains, input: data.arguments ?? {}, output: data.result ?? {}, time: item.at },
              ];
            }
            if (kind === "orchestration_observation") {
              setChat((previous) => [
                ...previous,
                {
                  id: crypto.randomUUID(), role: "assistant", time: item.at, body: "",
                  actor: "orchestrator", kind: "observation",
                  observation: observationFrom(data.observation),
                  observationStep: typeof data.step === "number" ? data.step : undefined,
                },
              ]);
            }
            if (kind === "grounding_completed") {
              setChat((previous) => [
                ...previous,
                {
                  id: crypto.randomUUID(), role: "assistant", time: item.at, body: "",
                  actor: "orchestrator", kind: "grounding",
                  grounding: {
                    source: String(data.source ?? "configured repository"),
                    sopSources: Array.isArray(data.sop_source_ids) ? data.sop_source_ids.filter((source): source is string => typeof source === "string") : undefined,
                    originalSopSources: Array.isArray(data.sop_sources) ? data.sop_sources.filter((source): source is string => typeof source === "string") : undefined,
                    metadataAvailable: data.metadata_available === true,
                    message: String(data.message ?? "Grounding context retrieved."),
                    preview: String(data.context_preview ?? ""),
                  },
                },
              ]);
            }
            if (kind === "rpt_decision_completed" || kind === "rpt_final_decision_completed") {
              const decision = data.decision as Record<string, unknown>;
              const nextAgent = String(decision.next_agent ?? "unknown");
              const value = {
                nextAgent,
                nextAgentLabel: agents.find((agent) => agent.agent_id === nextAgent)?.agent_label,
                handoffMode: String(decision.handoff_mode ?? "unknown"),
                risk: String(decision.risk ?? "unknown"),
                priority: String(decision.priority ?? "unknown"),
                groundingUsed: decision.grounding_used === true,
                final: kind === "rpt_final_decision_completed",
                teamRankings: Array.isArray(decision.team_rankings)
                  ? decision.team_rankings.flatMap((item) => {
                    if (!item || typeof item !== "object") return [];
                    const ranking = item as Record<string, unknown>;
                    const score = Number(ranking.score);
                    return typeof ranking.agent_id === "string" && Number.isFinite(score)
                      ? [{ agentId: ranking.agent_id, agentLabel: agents.find((agent) => agent.agent_id === ranking.agent_id)?.agent_label, score }]
                      : [];
                  })
                  : undefined,
              };
              latestRptDecision.current = value;
              setChat((previous) => [
                ...previous,
                {
                  id: crypto.randomUUID(), role: "assistant", time: item.at, body: "",
                  actor: "orchestrator", kind: "rptDecision",
                  rptDecision: value,
                },
              ]);
            }
            const teamId = typeof data.agent_id === "string" ? data.agent_id : undefined;
            const teamHandoffKey = String(data.handoff_id ?? teamId ?? "team");
            const teamLabel = String(data.agent_label ?? agentName(teamId ?? producer));
            const subagentLabel = String(data.subagent_label ?? "Specialist Agent");
            if (kind === "team_handoff_started" && teamId) {
              const step = typeof data.step === "number" ? data.step : 0;
              const messageId = `team-handoff:${teamHandoffKey}:${step}`;
              teamStartMessageIds.current[teamHandoffKey] = messageId;
              setChat((previous) => previous.some((message) => message.id === messageId) ? previous : [
                ...previous,
                {
                  id: messageId, role: "assistant", body: "I received the Orchestrator's review request. I will select the relevant Specialists.",
                  time: item.at, actor: "team", agentName: teamLabel,
                },
              ]);
            }
            if (kind === "delegation_started" && teamId) {
              const messageId = teamStartMessageIds.current[teamHandoffKey];
              if (messageId) setChat((previous) => previous.map((message) => message.id === messageId
                ? { ...message, body: "I received the Orchestrator's review request. I am selecting the relevant Specialists.", time: item.at }
                : message));
            }
            if (kind === "delegation_selected" && teamId) {
              const messageId = teamStartMessageIds.current[teamHandoffKey];
              const selected = Array.isArray(data.delegations)
                ? data.delegations.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
                : [];
              const goals = Array.isArray(data.delegation_goals)
                ? data.delegation_goals.flatMap((item) => isRecord(item) && typeof item.agent === "string" && typeof item.goal === "string"
                  ? [`- ${item.agent}: ${item.goal}`] : [])
                : [];
              if (messageId) setChat((previous) => previous.map((message) => message.id === messageId
                ? { ...message, body: selected.length
                  ? goals.length
                    ? `I received the Orchestrator's review request. I delegated the review:\n\n${goals.join("\n")}`
                    : `I received the Orchestrator's review request. I delegated the review to ${selected.join(" and ")}.`
                  : "I received the Orchestrator's review request. I will continue the review with the available Specialist.", time: item.at }
                : message));
            }
            if (kind === "orchestration_decision" && (data.decision as Record<string, unknown> | undefined)?.action === "complete")
              addTypingAgent({ id: "orchestrator", label: "ORCHESTRATOR · PREPARING FINAL RESPONSE", role: "orchestrator" });
            if (kind === "artifact_received" || kind === "team_handoff_failed")
              addTypingAgent({ id: "orchestrator", label: "ORCHESTRATOR · REVIEWING EVIDENCE", role: "orchestrator" });
            if ((kind === "team_handoff_started" || kind === "delegation_started") && teamId)
              addTypingAgent({ id: "team:" + teamId, label: "TEAM ASSISTANT · " + teamLabel, role: "team" });
            if (kind === "subagent_started") {
              const subagentId = String(data.subagent_label ?? data.subagent_id ?? data.agent_id ?? "specialist");
              addTypingAgent({ id: "subagent:" + subagentId, label: "SPECIALIST AGENT · " + subagentLabel, role: "subagent" });
            }
            if (kind === "team_message_delta" && teamId)
              removeTypingAgent("team:" + teamId);
            if (kind === "subagent_message_delta" || kind === "subagent_completed") {
              const subagentId = String(data.subagent_label ?? data.subagent_id ?? data.agent_id ?? "specialist");
              removeTypingAgent("subagent:" + subagentId);
            }
            if (kind === "orchestrator_message_delta") removeTypingAgent("orchestrator");
            if (text) {
              const streamId = typeof data.stream_id === "string" ? data.stream_id : undefined;
              const isTeam = kind === "team_message_delta";
              const isSubagent = kind === "subagent_message_delta";
              const isJoule = kind.startsWith("joule_");
              const messageId = streamId ? `stream:${runId}:${streamId}` : crypto.randomUUID();
              const toolKey = `${String(data.handoff_id ?? data.agent_id ?? "team")}:${String(data.subagent_label ?? "Specialist")}`;
              const toolCalls = isSubagent ? pendingToolCalls.current[toolKey] : undefined;
              if (isSubagent) delete pendingToolCalls.current[toolKey];
              setChat((previous) => {
                const existing = streamId ? previous.findIndex((message) => message.id === messageId) : -1;
                if (existing >= 0) {
                  const next = [...previous];
                  next[existing] = { ...next[existing], body: next[existing].body + text };
                  return next;
                }
                return [...previous, {
                  id: messageId, role: "assistant", body: text, time: item.at,
                  actor: isJoule ? "joule" : isSubagent ? "subagent" : isTeam ? "team" : "orchestrator",
                  agentName: isJoule ? "Joule Work Agent" : isSubagent ? String(data.subagent_label ?? "Specialist Agent") : isTeam ? String(data.agent_label ?? agentName(data.agent_id ?? producer)) : undefined,
                  toolCalls,
                }];
              });
            }
            if (kind === "complete") {
              setTypingAgents([]);
              const result = data.result as Record<string, unknown> | undefined;
              const summary = typeof result?.summary === "string" ? result.summary.trim() : "";
              if (summary) setChat((previous) => previous.some((item) => item.id === `stream:${runId}:final-summary`)
                ? previous
                : [...previous, {
                  id: `stream:${runId}:final-summary`, role: "assistant", body: summary, time: item.at, actor: "orchestrator",
                }]);
            }
          }
        }
      }
    } catch (cause) {
      setTypingAgents([]);
      if ((cause as Error).name !== "AbortError")
        setError(cause instanceof Error ? cause.message : "Network error.");
    } finally {
      setRunning(false);
      setTypingAgents([]);
      aborter.current = undefined;
    }
  }
  const reset = () => {
    aborter.current?.abort();
    setSessionId(crypto.randomUUID());
    setHumanReview(undefined);
    setEvents([]);
    setJouleCardVerified(false);
    setJouleCard(undefined);
    latestRptDecision.current = undefined;
    pendingToolCalls.current = {};
    teamStartMessageIds.current = {};
    setRunning(false);
    setTypingAgents([]);
    setChat([
      {
        id: "welcome",
        role: "assistant",
        body: "A new Harness session has started. Enter an operational request.",
        time: "READY",
      },
    ]);
  };
  const submitGroundingQuestion = async () => {
    const query = groundingQuestion.trim();
    if (!query || groundingLoading) return;
    setGroundingLoading(true);
    setGroundingError("");
    setGroundingAnswer(undefined);
    try {
      const response = await fetch("/api/grounding/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, language: "en" }),
      });
      const payload = (await response.json()) as GroundingAnswer & { detail?: string };
      if (!response.ok || !payload.answer)
        throw new Error(payload.detail ?? "Could not generate a grounded answer.");
      setGroundingAnswer(payload);
    } catch (cause) {
      setGroundingError(cause instanceof Error ? cause.message : "Could not generate a grounded answer.");
    } finally {
      setGroundingLoading(false);
    }
  };
  const showGroundingDocuments = async () => {
    setGroundingTab("documents");
    setGroundingDocumentsLoading(true);
    setGroundingDocumentsError("");
    try {
      const response = await fetch("/api/grounding/documents");
      const payload = (await response.json()) as { documents?: GroundingDocument[]; detail?: string };
      if (!response.ok || !Array.isArray(payload.documents))
        throw new Error(payload.detail ?? "Could not load repository documents.");
      setGroundingDocuments(payload.documents);
    } catch (cause) {
      setGroundingDocumentsError(cause instanceof Error ? cause.message : "Could not load repository documents.");
    } finally {
      setGroundingDocumentsLoading(false);
    }
  };
  const nav: Array<[StudioSection, string, string]> = [
    ["grounding", "◌", "Grounding"],
    ["chat", "◉", "Chat"],
    ["agents", "◈", "Agent"],
    ["toolCalling", "⌘", "Tool Calling"],
    ["data", "▤", "CSV Data"],
    ["harnessStudio", "▦", "Harness Studio"],
  ];
  const groundingWorkspace = (
    <section className="console studio-chat grounding-workspace">
      <div className="console-heading">
        <div>
          <p className="kicker">GROUNDING · CONTEXT WORKSPACE</p>
          <h1>Business context</h1>
          <p>
            Agents use this read-only context to interpret an operational
            request.
          </p>
        </div>
        <div className="run-state">
          <i />
          READ ONLY
        </div>
      </div>
      <div className="grounding-summary">
        <article>
          <span>01</span>
          <div>
            <b>Request context</b>
            <p>
              The operator request and this session’s prior messages are
              supplied to the Orchestrator.
            </p>
          </div>
          <em>
            {chat.filter((item) => item.role === "user").length} request
            {chat.filter((item) => item.role === "user").length === 1
              ? ""
              : "s"}
          </em>
        </article>
        <article>
          <span>02</span>
          <div>
            <b>Agent catalog</b>
            <p>
              Team descriptions and capability boundaries guide the routing
              decision.
            </p>
          </div>
          <em>{agents.length || 12} teams</em>
        </article>
        <article>
          <span>03</span>
          <div>
            <b>Evidence policy</b>
            <p>
              Team Agents return planning evidence only. No write action is
              permitted in this demo.
            </p>
          </div>
          <em>READ ONLY</em>
        </article>
      </div>
      <div className="grounding-empty">
        <div className="grounding-orb">◌</div>
        <div>
          <p className="kicker">CONNECTED SOURCES</p>
          <h2>No external source connected</h2>
          <p>
            This sandbox grounds each run with the submitted request, session
            context, and the local Team Agent catalog. Connect an approved
            business source when the demo needs live reference data.
          </p>
          <button className="run-button" onClick={() => setSection("chat")}>
            Send a grounded request →
          </button>
        </div>
      </div>
    </section>
  );
  const showingGrounding = () => false;
  if (showingGrounding())
    return (
      <main className="harness studio-shell">
        <header className="topbar">
          <div className="brand">
            <img
              className="brand-mark"
              src={jouleLogo}
              alt="Joule"
            />
            <div>
              <strong>Orchestrator Harness</strong>
              <small>F&amp;B OPERATIONS · A2A SANDBOX</small>
            </div>
          </div>
          <button className="ghost-button" onClick={() => reset()}>
            ↻ New session
          </button>
        </header>
        <section
          className={railExpanded ? "studio-layout expanded" : "studio-layout"}
        >
          <aside className="studio-rail">
            <button
              className="rail-toggle"
              onClick={() => setRailExpanded((value) => !value)}
            >
              ☰
            </button>
            {nav.map(([id, icon, label]) => (
              <button
                key={id}
                className={section === id ? "rail-item active" : "rail-item"}
                onClick={() => {
                  setSection(id);
                  setRailExpanded(true);
                }}
              >
                <span>{icon}</span>
                <b>{label}</b>
              </button>
            ))}
          </aside>
          {groundingWorkspace}
          <aside className="config-panel">
            <p className="kicker">GROUNDING STATUS</p>
            <h2>Context inputs</h2>
            <p>
              Grounding is visible before a run. It never performs a write
              action.
            </p>
            <dl>
              <dt>Session memory</dt>
              <dd>{sessionId ? "Active" : "New"}</dd>
              <dt>External sources</dt>
              <dd>None</dd>
              <dt>Catalog teams</dt>
              <dd>{agents.length || 12}</dd>
            </dl>
            <button className="panel-action" onClick={() => setSection("chat")}>
              Open Chat →
            </button>
          </aside>
        </section>
      </main>
    );

  return (
    <main className="harness studio-shell">
      <header className="topbar">
        <div className="brand">
          <img
            className="brand-mark"
            src={jouleLogo}
            alt="Joule"
          />
          <div>
            <strong>Orchestrator Harness</strong>
            <small>F&amp;B OPERATIONS · A2A SANDBOX</small>
          </div>
        </div>
        <div className="topbar-actions">
          <a className="ghost-button learning-menu-link" href="#/harness">
            ◈ Harness guide
          </a>
        </div>
      </header>
      <section className={(railExpanded ? "studio-layout expanded" : "studio-layout") + (section === "harnessStudio" ? " harness-studio-layout" : "")}>
        <aside className="studio-rail">
          <button className="rail-toggle" onClick={() => setRailExpanded((value) => !value)}>☰</button>
          {nav.map(([id, icon, label]) => (
            <button
              key={id}
              aria-label={label}
              aria-pressed={section === id}
              className={section === id ? "rail-item active" : "rail-item"}
              onClick={() => {
                setSection(id);
                setRailExpanded(true);
              }}
            >
              <span>{icon}</span>
              <b>{label}</b>
            </button>
          ))}
        </aside>
        {(studioVisited || section === "harnessStudio") && <div className="harness-studio-container" hidden={section !== "harnessStudio"}><HarnessStudio onSettingsSaved={() => { void loadPrompts(); setMetadataEpoch((value) => value + 1); setJouleCardVerified(false); setJouleCard(undefined); }} /></div>}
        <section className="console studio-chat" style={section === "harnessStudio" ? { display: "none" } : undefined}>
          <div className="console-heading chat-toolbar">
            <div className="chat-heading-actions">
              <button className="ghost-button new-session-button" onClick={() => reset()}>↻ New session</button>
              <div className="run-state">
                <i className={running ? "pulse" : ""} />
                {running ? "LIVE RUNNING" : "A2A COLLABORATION"}
              </div>
            </div>
          </div>
          <div className="session-line">
            <span>
              {sessionId
                ? `SESSION ${sessionId.slice(0, 8)}`
                : "SESSION NOT STARTED"}
            </span>
            <span>{events.length} events</span>
          </div>
          <div className="chat-feed">
            {chat.map((item) => item.systemEvent ? (
              <SystemEventCard key={item.id} event={item.systemEvent} time={item.time} />
            ) : (
              <article className={`message ${item.role}${item.kind ? " " + item.kind : ""}${item.actor ? " actor-" + item.actor : ""}`} key={item.id}>
                <div className="message-avatar">
                  {item.role === "user" ? (
                    <svg className="operator-avatar-icon" viewBox="0 0 24 24" aria-label="Operator" role="img">
                      <circle cx="12" cy="8" r="3.5" />
                      <path d="M5.5 20c.7-4 3.1-6 6.5-6s5.8 2 6.5 6" />
                    </svg>
                  ) : <img
                    src={item.actor === "orchestrator" || !item.actor ? sapLogo : jouleLogo}
                    alt=""
                  />}
                </div>
                <div>
                  <div className="message-meta">
                    {item.role === "user" ? "OPERATOR" : item.actor === "joule" ? "JOULE WORK AGENT" : item.actor === "subagent" ? `SPECIALIST AGENT · ${item.agentName ?? "Specialist Agent"}` : item.actor === "team" ? `TEAM ASSISTANT · ${item.agentName ?? "Team Agent"}` : "ORCHESTRATOR"}{" "}
                    <span>{item.time}</span>
                  </div>
                  {item.observation ? <ObservationResult result={item.observation} step={item.observationStep} /> : item.grounding ? <GroundingResult result={item.grounding} /> : item.rptDecision ? <RptDecisionResult result={item.rptDecision} /> : item.loading ? <div className="typing-bubble"><i /><i /><i /></div> : <MarkdownMessage body={item.body} toolCalls={item.toolCalls} formatStructured={item.role === "assistant"} />}
                </div>
              </article>
            ))}
            {typingAgents.map((agent) => (
              <article className={`message typing-message actor-${agent.role}`} key={agent.id}>
                <div className="message-avatar">
                  <img src={agent.role === "orchestrator" ? sapLogo : jouleLogo} alt="" />
                </div>
                <div>
                  <div className="message-meta">{agent.label}</div>
                  <div className="typing-bubble" role="status" aria-label={agent.label + " is generating a response"}>
                    <i /><i /><i />
                  </div>
                </div>
              </article>
            ))}
          </div>
          {error && <p className="error">{error}</p>}
          <form className="composer" onSubmit={send}>
            {humanReview && <section className="human-review-input" role="status"><b>Human input required</b><p>{humanReview.handoff_mode === "request_evidence" ? "Add the requested evidence to continue the review." : "Add your review comments to continue."} The Harness will reassess the request with the prior Artifacts and saved settings.</p></section>}
            {examplesOpen && <section className="scenario-picker" aria-label="Example scenarios">
              <div><p className="kicker">SCENARIOS</p><b>Choose an operational request</b></div>
              <div className="scenario-picker__grid">
                {scenarios.map((scenario, index) => <button key={scenario.title} type="button" onClick={() => { setMessage(scenario.request); setExamplesOpen(false); }}>
                  <span>{String(index + 1).padStart(2, "0")}</span><b>{scenario.title}</b><small>{scenario.request}</small>
                </button>)}
              </div>
            </section>}
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={humanReview ? "Provide evidence or human review comments…" : "Example: Review purchasing a CIP pump mechanical seal kit."}
            />
            <div>
              <button
                type="button"
                className="example-button"
                onClick={() => setExamplesOpen((open) => !open)}
              >
                Use example
              </button>
              <span>↵ Enter to run</span>
              <button
                className="run-button"
                disabled={running || !message.trim()}
              >
                {running ? "Running…" : humanReview ? "Submit input & reassess →" : "Run harness →"}
              </button>
            </div>
          </form>
        </section>
        <aside className="config-panel" style={section === "harnessStudio" ? { display: "none" } : undefined}>
          <p className="kicker">
            {section === "grounding"
              ? "GROUNDING"
              : section === "chat"
                ? "CHAT SETTINGS"
                : section === "agents"
                  ? "AGENT NETWORK"
                  : section === "toolCalling"
                    ? "TOOL CALLING"
                    : section === "data"
                      ? "CSV SNAPSHOTS"
                    : "SKILL & TOOLS"}
          </p>
          {section === "grounding" && (
            <>
              <h2>Grounding</h2>
              <div className="grounding-actions"><button type="button" className="primary">{groundingConfig?.configured ? "Connected" : "Not configured"}</button></div>
              <p className="grounding-status">{groundingConfig?.configured ? "✓ Grounding source connected" : "Grounding is not configured"}</p>
              <div className="grounding-tabs"><button className={groundingTab === "ground" ? "active" : ""} type="button" onClick={() => setGroundingTab("ground")}>Ground</button><button className={groundingTab === "documents" ? "active" : ""} type="button" onClick={() => void showGroundingDocuments()}>Documents</button></div>
              {groundingTab === "ground" ? <>
                <p className="grounding-subtitle">Active sources</p>
                <article className="document-card"><b>Configured grounding source</b><small>{groundingConfig?.configured ? "Connected" : "Not configured"}</small><span>Grounding source</span></article>
                <article className="document-card"><b>Current session context</b><small>{sessionId ? "Active conversation memory" : "Starts when the first request is sent"}</small><span>Session source</span></article>
                <label className="grounding-label">Question
                  <textarea value={groundingQuestion} onChange={(event) => setGroundingQuestion(event.target.value)} placeholder="Ask a question grounded in your sources" />
                </label>
                <button className="grounding-answer" type="button" disabled={!groundingQuestion.trim() || groundingLoading} onClick={() => void submitGroundingQuestion()}>{groundingLoading ? "Retrieving grounded context…" : "Generate grounded answer"}</button>
                {groundingError && <p className="grounding-query-error">{groundingError}</p>}
                {groundingAnswer && <section className="grounding-query-result">
                  <p className="grounding-result__label">Grounded answer · {groundingAnswer.metadata_available ? "metadata ready" : "context ready"}</p>
                  <p className="grounding-query-result__question">Q. {groundingAnswer.query}</p>
                  <div>{groundingAnswer.answer}</div><small>{groundingAnswer.source} · {groundingAnswer.message}</small>
                </section>}
              </> : <section className="grounding-documents">
                <p className="grounding-subtitle">Repository documents</p>
                {groundingDocumentsLoading && <p className="grounding-hint">Loading repository documents…</p>}
                {groundingDocumentsError && <p className="grounding-query-error">{groundingDocumentsError}</p>}
                {!groundingDocumentsLoading && !groundingDocumentsError && groundingDocuments.length === 0 && <p className="grounding-hint">No repository documents are registered.</p>}
                {groundingDocuments.map((document) => <article className="document-card" key={document.id}><b>{document.name}</b><small>{document.id}</small><span>Vector repository document</span></article>)}
              </section>}
            </>
          )}
          {section === "chat" && (
            <>
              <h2>A2A collaboration graph</h2>
              <div className={running ? "a2a-graph running" : "a2a-graph"}>
                <article className={running && events.length === 0 ? "graph-node orchestrator live" : "graph-node orchestrator"}>
                  <img src={sapLogo} alt="SAP" />
                  <div><b>ORCHESTRATOR</b><small>{running ? "Routing live" : "Route coordinator"}</small></div>
                </article>
                <div className="graph-connector grounding-connector"><span>retrieve context</span></div>
                <article className={groundingInProgress ? "graph-node grounding fetching" : events.some((event) => event.type === "grounding_completed") ? "graph-node grounding active" : "graph-node grounding"}>
                  <span className="grounding-node-icon">◌</span>
                  <div><b>GROUNDING REPOSITORY</b><small>{groundingInProgress ? "Retrieving context" : events.some((event) => event.type === "grounding_completed") ? "Context retrieved" : "Vector SOP & business context"}</small></div>
                </article>
                <div className="graph-connector rpt-connector"><span>grounded handoff decision</span></div>
                <article className={"graph-node rpt " + initialRptStatus.state + (initialHumanReviewRequired ? " human-required" : "")}>
                  <span className="rpt-node-icon">◈</span>
                  <div>
                    <b>INITIAL RPT DECISION</b>
                    <small>{initialRptStatus.state === "running" ? "Assessing Joule handoff conditions" : initialRptStatus.state === "failed" ? "Unavailable · Local review continues" : initialRptStatus.state === "complete" ? "Joule handoff assessment complete" : "Awaiting initial assessment"}</small>
                  </div>
                  {initialRptStatus.state === "running" && <i>●</i>}
                  {initialRptStatus.state === "complete" && rptGroundingUsed && <em className="grounded-badge">GROUNDED</em>}
                  {initialRptStatus.state === "complete" && <em className={initialHumanReviewRequired ? "hitl-badge required" : "hitl-badge"}>{initialRptStatus.decision?.handoff_mode === "delegate_now" ? "JOULE ELIGIBLE" : "DEFERRED"}</em>}
                </article>
                <div className="graph-connector"><span>route & handoff</span></div>
                <div className="graph-team-list">
                  {agents.map((agent) => (
                    <article key={agent.agent_id} className={(active.has(agent.agent_id) ? "graph-node team active" : "graph-node team") + (workingTeams.has(agent.agent_id) ? " running" : "")}>
                      <img src={jouleLogo} alt="Joule" />
                      <div><b>{agent.agent_label.replace(" Assistant", "")}</b><small>{workingTeams.has(agent.agent_id) ? "Review in progress" : active.has(agent.agent_id) ? "Handoff complete" : agent.skill_id.replaceAll("_", " · ")}</small></div>
                      <i>{active.has(agent.agent_id) ? "●" : "○"}</i>
                    </article>
                  ))}
                </div>
                <div className="graph-connector final-rpt-connector"><span>final review check</span></div>
                <article className={"graph-node rpt final-rpt " + rptStatus.state + (humanReviewRequired ? " human-required" : "")}>
                  <span className="rpt-node-icon">◈</span>
                  <div>
                    <b>FINAL RPT DECISION MODEL</b>
                    <small>{rptStatus.state === "complete" ? (humanReviewRequired ? "Human review recommended" : "Final assessment complete") : rptStatus.state === "running" ? "Evaluating completed Team evidence" : rptStatus.state === "failed" ? "Unavailable · Safe error" : "Awaiting final Chat answer"}</small>
                  </div>
                  {rptStatus.state === "complete" && <em className={humanReviewRequired ? "hitl-badge required" : "hitl-badge"}>{humanReviewRequired ? "REVIEW ADVISED" : "ASSESSED"}</em>}
                </article>
                {humanReviewRequired && <section className="human-loop" role="note">
                  <div className="human-loop__heading"><div><b>HUMAN REVIEW RECOMMENDED</b><small>HITL input is not connected in this demo.</small></div></div>
                  <p className="human-loop__notice">The RPT result is advisory. Human input submission and Task resumption are not connected.</p>
                </section>}
              </div>
              <div className="graph-legend"><span><i /> Active handoff</span><span>{events.length} events</span></div>
            </>
          )}
          {section === "agents" && (
            <>
              <h2>Agent network</h2>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, margin: "0 0 12px" }}>
                <button type="button" className="panel-action" style={{ margin: 0, textAlign: "center", background: agentNetworkTab === "local" ? "var(--green-tile)" : undefined }} onClick={() => setAgentNetworkTab("local")}>Local</button>
                <button type="button" className="panel-action" style={{ margin: 0, textAlign: "center", background: agentNetworkTab === "joule" ? "var(--green-tile)" : undefined }} onClick={() => setAgentNetworkTab("joule")}>Joule</button>
              </div>
              {agentNetworkTab === "local" ? <>
              <div className="agent-hierarchy">
                <button
                  type="button"
                  className={selectedPromptId === "orchestrator" ? "hierarchy-node orchestrator selected" : "hierarchy-node orchestrator"}
                  onClick={() => { setSelectedPromptId("orchestrator"); setPromptModalOpen(true); }}
                >
                  <img src={sapLogo} alt="SAP" /><span><em>ORCHESTRATOR</em><b>{prompts?.orchestrator.label ?? "Orchestration Agent"}</b><small>Routes requests and evaluates returned Artifacts</small></span>
                </button>
                <div className="hierarchy-connector"><span>delegates to</span></div>
                <div className="team-hierarchy-list">
                  {agents.map((agent) => (
                    <section className={(active.has(agent.agent_id) ? "team-hierarchy active" : "team-hierarchy")} key={agent.agent_id}>
                      <button
                        type="button"
                        className={`${selectedPromptId === agent.agent_id ? "hierarchy-node team selected" : "hierarchy-node team"}${workingTeams.has(agent.agent_id) ? " running" : ""}`}
                        onClick={() => { setSelectedPromptId(agent.agent_id); setPromptModalOpen(true); }}
                      >
                        <img src={jouleLogo} alt="Joule" /><span><em>TEAM ASSISTANT</em><b>{agent.agent_label}</b><small>{workingTeams.has(agent.agent_id) ? "Review in progress" : agent.description}</small></span>
                      </button>
                      <div className="specialist-hierarchy">
                        {agent.sub_agents.map((specialist) => <button type="button" className={(activeSpecialists.has(specialist) ? "specialist-node active" : "specialist-node") + (selectedPromptId === `specialist:${specialist}` ? " selected" : "")} key={specialist} onClick={() => { setSelectedPromptId(`specialist:${specialist}`); setPromptModalOpen(true); }}>
                          <img src={jouleLogo} alt="Joule" /><span><em>SPECIALIST AGENT</em><b>{specialist}</b></span>
                        </button>)}
                      </div>
                    </section>
                  ))}
                </div>
              </div>
              </> : <>
              <p>Inspect the deployed Joule Studio Work Agent connection and Agent Card.</p>
              <div className="mini-agent-list">
                <article className={jouleCardVerified ? "active" : ""}>
                  <i /> <b>Joule Work Agent</b>
                  <small>{jouleCardVerified ? "Agent Card verified · external" : "Fixed external A2A target"}</small>
                  {jouleCard ? (
                    <details className="joule-card" open>
                      <summary>Agent Card JSON</summary>
                      <pre>{JSON.stringify(jouleCard, null, 2)}</pre>
                    </details>
                  ) : jouleCardLoading ? <small className="joule-card-empty">Checking the deployed Agent Card…</small> : jouleCardError ? (
                    <button type="button" className="panel-action" style={{ marginTop: 10 }} onClick={() => void loadJouleCard()}>Check connection again</button>
                  ) : <small className="joule-card-empty">Open this tab to retrieve the deployed Agent Card.</small>}
                </article>
              </div>
              </>}
            </>
          )}
          {section === "toolCalling" && (
            <>
              <h2>Tool Calling <span>{tools.length}</span></h2>
              <div className="tool-calling-list">
                {tools.map((tool) => (
                  <button type="button" className="tool-call-card" key={tool.name} onClick={() => { setSelectedTool(tool); setToolModalOpen(true); }}>
                    <b>{tool.name}</b>
                    <em>Details →</em>
                  </button>
                ))}
                {!tools.length && <p>Loading the Tool Catalog…</p>}
              </div>
            </>
          )}
          {section === "data" && (
            <>
              <h2>Business data <span>{dataSnapshots.length}</span></h2>
              <div className="data-snapshot-list">
                {dataSnapshots.map((snapshot) => (
                  <button type="button" key={snapshot.name} className="cds-view-card" onClick={() => void openSnapshot(snapshot.name)}>
                    <span>CDS VIEW</span>
                    <b>{snapshot.view_name}</b>
                    <strong>{snapshot.domain}</strong>
                    <p>{snapshot.description}</p>
                    <small>{snapshot.rows} records · {snapshot.columns.length} fields</small>
                    <em>{snapshot.name}</em>
                  </button>
                ))}
                {!dataSnapshots.length && <p>Loading CSV snapshots…</p>}
              </div>
            </>
          )}
        </aside>
      </section>
      {snapshotModalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setSnapshotModalOpen(false)}>
          <section className="modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="snapshot-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <p className="kicker">CDS VIEW · READ ONLY SNAPSHOT</p>
                <h2 id="snapshot-modal-title">{selectedSnapshot?.view_name ?? "Loading CDS View…"}</h2>
                {selectedSnapshot && <p className="snapshot-source">{selectedSnapshot.name} · first {selectedSnapshot.limit} rows</p>}
              </div>
              <button type="button" aria-label="Close data snapshot" onClick={() => setSnapshotModalOpen(false)}>×</button>
            </header>
            {snapshotLoading && <p className="prompt-status">Loading read-only snapshot…</p>}
            {snapshotError && <div className="prompt-error"><p>{snapshotError}</p></div>}
            {selectedSnapshot && !snapshotLoading && (
              <>
                <section className="data-product-summary">
                  <div><span>DATA PRODUCT</span><b>{selectedSnapshot.product_name}</b></div>
                  <div><span>DOMAIN / OWNER</span><b>{selectedSnapshot.domain} · {selectedSnapshot.owner}</b></div>
                  <div><span>REFRESH</span><b>{selectedSnapshot.refresh}</b></div>
                  <p>{selectedSnapshot.description}</p>
                </section>
                <div className="snapshot-table-wrap">
                  <table>
                    <thead><tr>{selectedSnapshot.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                    <tbody>{selectedSnapshot.rows.map((row, index) => <tr key={index}>{selectedSnapshot.columns.map((column) => <td key={column}>{row[column] || "—"}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        </div>
      )}
      {toolModalOpen && selectedTool && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setToolModalOpen(false)}>
          <section className="modal tool-detail-modal" role="dialog" aria-modal="true" aria-labelledby="tool-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <p className="kicker">TOOL CALLING · {selectedTool.mode.toUpperCase()}</p>
                <h2 id="tool-modal-title">{selectedTool.name}</h2>
              </div>
              <button type="button" aria-label="Close tool details" onClick={() => setToolModalOpen(false)}>×</button>
            </header>
            <p className="tool-detail-description">{selectedTool.description}</p>
            <dl className="tool-detail-spec">
              <div><dt>Required input</dt><dd><code>{selectedTool.required_parameter}</code></dd></div>
              {(selectedTool.inputs ?? []).map((input) => <div key={input.name}><dt><code>{input.name}</code> · {input.type}</dt><dd>{input.description}<br /><small>Required: {input.required ? "Yes" : "No"} · Example: <code>{input.example}</code></small></dd></div>)}
              <div><dt>Access mode</dt><dd>Read only</dd></div>
              <div><dt>Catalog source</dt><dd>{selectedTool.source}</dd></div>
            </dl>
            <section className="tool-detail-boundary"><span>EXECUTION BOUNDARY</span><p>{selectedTool.policy_note ?? "The Specialist Agent selects this Tool from its allow-list. This screen does not execute the Tool."}</p></section>
          </section>
        </div>
      )}
      {promptModalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setPromptModalOpen(false)}>
          <section className="modal prompt-modal" role="dialog" aria-modal="true" aria-labelledby="prompt-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <p className="kicker">{selectedPromptId === "orchestrator" ? "ORCHESTRATION AGENT · READ ONLY" : selectedPromptId.startsWith("specialist:") ? "SPECIALIST AGENT · READ ONLY" : "TEAM AGENT · READ ONLY"}</p>
                <h2 id="prompt-modal-title">{selectedPrompt?.label ?? "System prompt"}</h2>
              </div>
              <button type="button" aria-label="Close system prompt" onClick={() => setPromptModalOpen(false)}>×</button>
            </header>
            {promptsLoading && <p className="prompt-status">Loading system prompts…</p>}
            {promptsError && (
              <div className="prompt-error">
                <p>{promptsError}</p>
                <button className="panel-action" onClick={() => void loadPrompts()}>Retry</button>
              </div>
            )}
            {!promptsLoading && !promptsError && selectedPrompt && (
              <>
                <p className="prompt-label">System prompt</p>
                {selectedPrompt.prompt_key && <p className="prompt-resource">TOML · {selectedPrompt.prompt_key}</p>}
                <SystemPromptText prompt={selectedPrompt.system_prompt} />
              </>
            )}
            {!promptsLoading && !promptsError && !selectedPrompt && <p className="prompt-status">The system prompt for this Agent is unavailable.</p>}
          </section>
        </div>
      )}
    </main>
  );
}

export default function App() {
  const [learningRoute, setLearningRoute] = useState(() => window.location.hash === "#/harness");

  useEffect(() => {
    const onHashChange = () => setLearningRoute(window.location.hash === "#/harness");
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return <>
    <div hidden={learningRoute}>
      <HarnessConsole />
    </div>
    {learningRoute && <HarnessLearningPage />}
  </>;
}
