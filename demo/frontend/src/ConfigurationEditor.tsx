import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import DelimitedInput from "./DelimitedInput";

type Specialist = { name: string; domains: string[]; tools: string[] };
type Team = { agent_id: string; agent_label: string; description: string; skill_id: string; sub_agents: string[]; tags: string[]; keywords: string[]; examples: string[] };
type External = { agent_id: string; label: string; base_url: string; enabled: boolean };
type Tool = { name: string; description: string; required_parameter: string; inputs: { name: string; type: string; required: boolean; description: string; example: string }[]; policy_note?: string };
type Decision = { next_agent: { instructions: string; criteria: Record<string, string> }; handoff_mode: { instructions: string; criteria: Record<string, string> }; risk: { instructions: string; criteria: Record<string, string> }; priority: { instructions: string; criteria: string[] }; examples: { state: string; answers: Record<string, string> }[] };
type Sections = {
  agents: { teams: Team[]; specialists: Specialist[]; external_agents: External[] };
  tools: { contracts: Tool[]; specialist_permissions: Specialist[] };
  data: Record<string, Record<string, string>[]>;
  grounding: { repository_id: string; prompts: Record<string, string>; sop_required: boolean };
  runtime: { max_handoffs: number; max_tool_turns: number; timeouts: Record<string, number>; context_limits: Record<string, number>; hitl_mode: "advisory" | "require_input" };
  rpt: { decision: Decision; prompts: Record<string, string> };
  joule: { solution_id: string; asset_name: string };
};
export type ConfigurationSection = keyof Sections;
type Manifest = { revision: number; sections: Sections; application: string };
type Draft = { value: Sections[ConfigurationSection]; revision: number; original: Sections[ConfigurationSection] };
const titles: Record<ConfigurationSection, string> = { agents: "Agent registry", tools: "Tool contracts & permissions", data: "Business Data", grounding: "SOP Grounding", runtime: "Runtime controls", rpt: "RPT Decision", joule: "Joule connection" };
const label = (key: string) => key.replaceAll("_", " ");

export default function ConfigurationEditor({ section, onSaved, settingsEpoch }: { section: ConfigurationSection; onSaved: () => void; settingsEpoch: number }) {
  const [manifest, setManifest] = useState<Manifest>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [success, setSuccess] = useState("");
  const [drafts, setDrafts] = useState<Partial<Record<ConfigurationSection, Draft>>>({});
  const [index, setIndex] = useState(0);
  const [dataset, setDataset] = useState("business_context.csv");
  const [promptKey, setPromptKey] = useState("system_en");
  const [compare, setCompare] = useState(false);
  const [card, setCard] = useState<unknown>();
  const [checking, setChecking] = useState(false);
  const pending = useRef<AbortController | undefined>(undefined);
  const load = useCallback(async () => {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/harness/configuration", { signal: controller.signal });
      if (!response.ok) throw new Error();
      const value = await response.json() as Manifest;
      if (!value.sections || typeof value.revision !== "number") throw new Error();
      if (!controller.signal.aborted) {
        setManifest(value);
        setDrafts((current) => Object.fromEntries(Object.entries(current).map(([key, item]) => [key, item && JSON.stringify(item.original) === JSON.stringify(value.sections[key as ConfigurationSection]) ? { ...item, revision: value.revision } : item])));
      }
      return !controller.signal.aborted;
    } catch { if (!controller.signal.aborted) setError("Could not load Harness configuration. Retry the Gateway connection."); return false; }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => { void load(); return () => pending.current?.abort(); }, [load, settingsEpoch]);
  useEffect(() => { setIndex(0); setSaveError(""); setSuccess(""); setCompare(false); setCard(undefined); }, [section]);
  const draft = manifest ? drafts[section] ?? { value: manifest.sections[section], original: manifest.sections[section], revision: manifest.revision } : undefined;
  const value = draft?.value;
  const dirty = !!draft && JSON.stringify(draft.value) !== JSON.stringify(draft.original);
  const update = (next: Sections[ConfigurationSection]) => {
    if (!draft) return;
    setDrafts((current) => ({ ...current, [section]: { ...draft, value: next } })); setSaveError(""); setSuccess("");
  };
  const edit = (action: (copy: Sections[ConfigurationSection]) => void) => { if (value) { const next = structuredClone(value); action(next); update(next); } };
  const discard = () => { setDrafts((current) => { const next = { ...current }; delete next[section]; return next; }); setSaveError(""); setSuccess(""); };
  const save = async () => {
    if (!draft || !dirty || saving) return;
    setSaving(true); setSaveError(""); setSuccess("");
    try {
      const response = await fetch("/api/harness/configuration", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section, value: draft.value, expected_revision: draft.revision }) });
      const result = await response.json() as Manifest & { error?: { message?: string } };
      if (!response.ok) throw new Error(result.error?.message ?? "Could not save. Your draft is preserved.");
      setManifest(result); setDrafts((current) => { const next = { ...current }; delete next[section]; for (const [key, item] of Object.entries(next)) if (item && JSON.stringify(item.original) === JSON.stringify(result.sections[key as ConfigurationSection])) item.revision = result.revision; return next; });
      setSuccess("Saved revision " + result.revision + ". " + result.application); onSaved();
    } catch (cause) { setSaveError(cause instanceof Error ? cause.message : "Could not save. Your draft is preserved."); }
    finally { setSaving(false); }
  };
  const check = async (agentId?: string) => {
    setChecking(true); setCard(undefined);
    try {
      const response = await fetch(agentId ? "/api/harness/agent-card?agent_id=" + encodeURIComponent(agentId) : "/api/joule-agent-card");
      const result = await response.json() as { card?: unknown };
      if (!response.ok || !result.card) throw new Error();
      setCard(result.card);
    } catch { setCard("Connection could not be verified. Save the target first and check its deployed Card."); }
    finally { setChecking(false); }
  };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const response = await fetch("/api/harness/data/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: dataset, csv: await file.text() }) });
      const result = await response.json() as { rows: Record<string, string>[]; error?: { message?: string } };
      if (!response.ok) throw new Error(result.error?.message ?? "Invalid CSV.");
      edit((copy) => { (copy as Sections["data"])[dataset] = result.rows; });
    } catch (cause) { setSaveError(cause instanceof Error ? cause.message : "Could not preview CSV."); }
    event.target.value = "";
  };
  if (loading) return <div className="harness-studio__state" role="status"><p>Loading configuration…</p></div>;
  if (error) return <div className="harness-studio__state" role="alert"><p>{error}</p><button type="button" onClick={() => void load()}>Retry</button></div>;
  if (!manifest || !value || !draft) return null;
  const input = (title: string, text: string, onChange: (next: string) => void, multiline = false) => <label className="harness-config__field">{title}{multiline ? <textarea value={text} disabled={saving} onChange={(event) => onChange(event.target.value)} /> : <input value={text} disabled={saving} onChange={(event) => onChange(event.target.value)} />}</label>;
  let form;
  if (section === "agents") {
    const registry = value as Sections["agents"];
    const team = registry.teams[index] ?? registry.teams[0];
    form = <div className="harness-editor__selection-layout">
      <nav className="harness-editor__selection-nav" aria-label="Team selection">
        <h3>Teams</h3>
        {registry.teams.map((item, position) => <button key={item.agent_id} type="button" className="harness-editor__selection-item" aria-pressed={index === position} onClick={() => setIndex(position)}><span>{item.agent_label}</span></button>)}
        <button type="button" className="harness-editor__selection-add" onClick={() => { edit((copy) => { const teams = (copy as Sections["agents"]).teams; teams.push({ agent_id: "new-team-" + (teams.length + 1), agent_label: "New Team " + (teams.length + 1), description: "Review assigned operational evidence.", skill_id: "custom_review_" + (teams.length + 1), sub_agents: registry.specialists.slice(0, 1).map((item) => item.name), tags: ["a2a", "read-only"], keywords: ["custom"], examples: ["Review operational evidence."] }); }); setIndex(registry.teams.length); }}>Add Team</button>
      </nav>
      <div className="harness-editor__selection-content">
      {team && <div className="harness-config__grid">{input("Agent ID", team.agent_id, (text) => edit((copy) => { (copy as Sections["agents"]).teams[index].agent_id = text; }))}{input("Name", team.agent_label, (text) => edit((copy) => { (copy as Sections["agents"]).teams[index].agent_label = text; }))}{input("Skill ID", team.skill_id, (text) => edit((copy) => { (copy as Sections["agents"]).teams[index].skill_id = text; }))}{<DelimitedInput label="Specialists (comma separated)" value={team.sub_agents} onChange={(names) => edit((copy) => { (copy as Sections["agents"]).teams[index].sub_agents = names; })} />}{<DelimitedInput label="Skill tags (comma separated)" value={team.tags} onChange={(names) => edit((copy) => { (copy as Sections["agents"]).teams[index].tags = names; })} />}{<DelimitedInput label="Example requests (comma separated)" value={team.examples} onChange={(names) => edit((copy) => { (copy as Sections["agents"]).teams[index].examples = names; })} />}{input("Role description", team.description, (text) => edit((copy) => { (copy as Sections["agents"]).teams[index].description = text; }), true)}</div>}
      <div className="harness-config__row"><button type="button" disabled={registry.teams.length < 2} onClick={() => { edit((copy) => { (copy as Sections["agents"]).teams.splice(index, 1); }); setIndex(0); }}>Remove Team</button></div>
      <h3>Specialist roles</h3><p>Register roles here, then assign their Tools and evidence domains under Tools.</p>
      {registry.specialists.map((item, position) => <div className="harness-config__row" key={position}>{input("Specialist name", item.name, (text) => edit((copy) => { const data = copy as Sections["agents"]; const before = data.specialists[position].name; data.specialists[position].name = text; for (const current of data.teams) current.sub_agents = current.sub_agents.map((name) => name === before ? text : name); }))}<button type="button" onClick={() => edit((copy) => { const data = copy as Sections["agents"]; data.specialists.splice(position, 1); for (const current of data.teams) current.sub_agents = current.sub_agents.filter((name) => name !== item.name); })}>Remove role</button></div>)}
      <button type="button" onClick={() => edit((copy) => { (copy as Sections["agents"]).specialists.push({ name: "Custom Specialist " + (registry.specialists.length + 1), domains: ["facility"], tools: ["search_business_context", "retrieve_business_evidence"] }); })}>Add Specialist</button>
      <h3>External A2A Agents</h3><p>Register an existing JSON-RPC streaming Agent base URL. Card discovery validates its interface before handoff.</p>
      {registry.external_agents.map((agent, position) => <section className="harness-config__card" key={position}><div className="harness-config__grid">{input("Agent ID", agent.agent_id, (text) => edit((copy) => { (copy as Sections["agents"]).external_agents[position].agent_id = text; }))}{input("Name", agent.label, (text) => edit((copy) => { (copy as Sections["agents"]).external_agents[position].label = text; }))}{input("Base URL", agent.base_url, (text) => edit((copy) => { (copy as Sections["agents"]).external_agents[position].base_url = text; }))}</div><label className="harness-config__checkbox"><input type="checkbox" checked={agent.enabled} onChange={(event) => edit((copy) => { (copy as Sections["agents"]).external_agents[position].enabled = event.target.checked; })} />Enabled for discovery</label><div className="harness-config__row"><button type="button" disabled={checking} onClick={() => void check(agent.agent_id)}>Check saved connection</button><button type="button" onClick={() => edit((copy) => { (copy as Sections["agents"]).external_agents.splice(position, 1); })}>Remove external Agent</button></div></section>)}
      <button type="button" onClick={() => edit((copy) => { (copy as Sections["agents"]).external_agents.push({ agent_id: "external-agent-" + (registry.external_agents.length + 1), label: "External Agent", base_url: "http://localhost:9000/agent", enabled: false }); })}>Add external Agent</button>
      {team && <button type="button" disabled={checking || dirty} onClick={() => void check(team.agent_id)}>Check Team Card</button>}
      </div>
    </div>;
  } else if (section === "tools") {
    const config = value as Sections["tools"], tool = config.contracts[index] ?? config.contracts[0];
    form = <><label className="harness-editor__select">Tool<select value={index} onChange={(event) => setIndex(Number(event.target.value))}>{config.contracts.map((item, position) => <option key={item.name} value={position}>{item.name}</option>)}</select></label>{input("LLM Tool description", tool.description, (text) => edit((copy) => { (copy as Sections["tools"]).contracts[index].description = text; }), true)}{input("Input description: " + tool.required_parameter, tool.inputs[0].description, (text) => edit((copy) => { (copy as Sections["tools"]).contracts[index].inputs[0].description = text; }), true)}<p>Tool names, required inputs and implementations are registered by the runtime. Descriptions guide native function calling.</p><h3>Specialist permissions</h3>{config.specialist_permissions.map((specialist, position) => <section className="harness-config__card" key={specialist.name}><h4>{specialist.name}</h4>{<DelimitedInput label="Evidence domains (comma separated)" value={specialist.domains} onChange={(names) => edit((copy) => { (copy as Sections["tools"]).specialist_permissions[position].domains = names; })} />}<div className="harness-config__checks">{config.contracts.map((item) => <label className="harness-config__checkbox" key={item.name}><input type="checkbox" checked={specialist.tools.includes(item.name)} onChange={(event) => edit((copy) => { const row = (copy as Sections["tools"]).specialist_permissions[position]; row.tools = event.target.checked ? [...row.tools, item.name] : row.tools.filter((name) => name !== item.name); })} />{item.name}</label>)}</div></section>)}</>;
  } else if (section === "data") {
    const data = value as Sections["data"], datasetNames = Object.keys(data), activeDataset = data[dataset] ? dataset : datasetNames[0], active = data[activeDataset] ?? [], columns = Object.keys(active[0] ?? manifest.sections.data[activeDataset]?.[0] ?? {});
    form = <div className="harness-editor__selection-layout harness-data-layout">
      <nav className="harness-editor__selection-nav" aria-label="Dataset selection"><h3>Datasets</h3>{datasetNames.map((name) => <button key={name} type="button" className="harness-editor__selection-item" aria-pressed={name === activeDataset} onClick={() => setDataset(name)}><span>{name}</span><small>{data[name].length}</small></button>)}</nav>
      <div className="harness-editor__selection-content">
        <div className="harness-data__header"><div><h3>{activeDataset}</h3><p>{active.length} records · {columns.length} columns</p></div><label className="harness-config__upload">Preview replacement CSV<input type="file" accept=".csv,text/csv" disabled={saving} onChange={(event) => void upload(event)} /></label></div>
        <p>Edit records directly in the table. Save validates Context relationships and cost assumptions across all datasets.</p>
        <div className="harness-config__table harness-data__table"><table><caption className="sr-only">{activeDataset} records</caption><thead><tr><th scope="col" aria-label="Row number">#</th>{columns.map((column) => <th scope="col" key={column}>{column}</th>)}<th scope="col">Action</th></tr></thead><tbody>{active.map((row, position) => <tr key={position}><th scope="row">{position + 1}</th>{columns.map((column) => <td key={column}><input aria-label={column + " row " + (position + 1)} value={row[column]} onChange={(event) => edit((copy) => { (copy as Sections["data"])[activeDataset][position][column] = event.target.value; })} /></td>)}<td><button type="button" className="icon-button" aria-label={"Remove row " + (position + 1)} title={"Remove row " + (position + 1)} onClick={() => edit((copy) => { (copy as Sections["data"])[activeDataset].splice(position, 1); })}><span aria-hidden="true">×</span></button></td></tr>)}</tbody></table></div>
        <button type="button" className="icon-button" aria-label="Add record" title="Add record" onClick={() => edit((copy) => { (copy as Sections["data"])[activeDataset].push(Object.fromEntries(columns.map((column) => [column, ""]))); })}><span aria-hidden="true">+</span></button>
      </div>
    </div>;
  } else if (section === "grounding") {
    const config = value as Sections["grounding"], key = config.prompts[promptKey] !== undefined ? promptKey : Object.keys(config.prompts)[0];
    form = <><p>Verified SOP evidence is required for every operational review. The server-managed grounding source is not exposed in this editor.</p><label className="harness-editor__select">Grounding Prompt<select value={key} onChange={(event) => setPromptKey(event.target.value)}>{Object.keys(config.prompts).map((name) => <option key={name}>{name}</option>)}</select></label>{input("Prompt text", config.prompts[key], (text) => edit((copy) => { (copy as Sections["grounding"]).prompts[key] = text; }), true)}</>;
  } else if (section === "runtime") {
    const config = value as Sections["runtime"];
    form = <><div className="harness-config__grid">{["max_handoffs", "max_tool_turns"].map((key) => <label className="harness-config__field" key={key}>{label(key)}<input type="number" min="1" value={config[key as "max_handoffs" | "max_tool_turns"]} onChange={(event) => edit((copy) => { (copy as Sections["runtime"])[key as "max_handoffs" | "max_tool_turns"] = Number(event.target.value); })} /></label>)}</div><h3>Context limits</h3><div className="harness-config__grid">{Object.entries(config.context_limits).map(([key, number]) => <label className="harness-config__field" key={key}>{label(key)}<input type="number" min="1" value={number} onChange={(event) => edit((copy) => { (copy as Sections["runtime"]).context_limits[key] = Number(event.target.value); })} /></label>)}</div><h3>Timeouts (seconds)</h3><p>Existing server timeout environment overrides retain precedence.</p><div className="harness-config__grid">{Object.entries(config.timeouts).map(([key, number]) => <label className="harness-config__field" key={key}>{label(key)}<input type="number" min="0.01" step="any" value={number} onChange={(event) => edit((copy) => { (copy as Sections["runtime"]).timeouts[key] = Number(event.target.value); })} /></label>)}</div><label className="harness-editor__select">Human review<select value={config.hitl_mode} onChange={(event) => edit((copy) => { (copy as Sections["runtime"]).hitl_mode = event.target.value as Sections["runtime"]["hitl_mode"]; })}><option value="advisory">Show RPT advice</option><option value="require_input">Pause after the final RPT assessment until human input</option></select></label><p>Input starts a new root reassessment in the same session with prior Artifacts and the pinned settings revision. Completed Team Tasks are not resumed.</p></>;
  } else if (section === "rpt") {
    const config = value as Sections["rpt"], key = config.prompts[promptKey] !== undefined ? promptKey : Object.keys(config.prompts)[0];
    form = <><p>Decision criteria guide the RPT model. The Custom Extension Assistant retains Team routing authority.</p>{(["next_agent", "handoff_mode", "risk"] as const).map((field) => <section className="harness-config__card" key={field}><h3>{label(field)}</h3>{input("Instructions", config.decision[field].instructions, (text) => edit((copy) => { (copy as Sections["rpt"]).decision[field].instructions = text; }), true)}{Object.entries(config.decision[field].criteria).map(([name, text]) => input(name, text, (next) => edit((copy) => { (copy as Sections["rpt"]).decision[field].criteria[name] = next; }), true))}</section>)}{input("Priority instructions", config.decision.priority.instructions, (text) => edit((copy) => { (copy as Sections["rpt"]).decision.priority.instructions = text; }), true)}{config.decision.priority.criteria.map((text, position) => input("Priority " + position, text, (next) => edit((copy) => { (copy as Sections["rpt"]).decision.priority.criteria[position] = next; })))}<h3>Decision examples</h3>{config.decision.examples.map((example, position) => <section className="harness-config__card" key={position}>{input("Task state " + (position + 1), example.state, (text) => edit((copy) => { (copy as Sections["rpt"]).decision.examples[position].state = text; }), true)}<div className="harness-config__grid">{Object.entries(example.answers).map(([field, text]) => input(label(field), text, (next) => edit((copy) => { (copy as Sections["rpt"]).decision.examples[position].answers[field] = next; })))}</div></section>)}<label className="harness-editor__select">RPT Prompt<select value={key} onChange={(event) => setPromptKey(event.target.value)}>{Object.keys(config.prompts).map((name) => <option key={name}>{name}</option>)}</select></label>{input("Prompt text", config.prompts[key], (text) => edit((copy) => { (copy as Sections["rpt"]).prompts[key] = text; }), true)}</>;
  } else {
    const config = value as Sections["joule"];
    form = <><p>Connect an existing deployed Joule Work Agent. Authentication and CLI credentials remain on the server.</p>{input("Solution ID", config.solution_id, (text) => edit((copy) => { (copy as Sections["joule"]).solution_id = text; }))}{input("Asset name", config.asset_name, (text) => edit((copy) => { (copy as Sections["joule"]).asset_name = text; }))}<button type="button" disabled={checking || dirty} onClick={() => void check()}>Check saved connection</button></>;
  }
  return <section className="harness-editor harness-config" aria-label={titles[section]}><div className="harness-editor__revision"><span>Saved revision {manifest.revision}</span><p>{manifest.application}</p></div><div className="harness-editor__toolbar"><h2>{titles[section]}</h2><button type="button" aria-pressed={compare} onClick={() => setCompare((current) => !current)}>{compare ? "Back to editor" : "Compare changes"}</button></div>{compare ? <div className="harness-editor__compare"><section><h3>Saved configuration</h3><pre>{JSON.stringify(draft.original, null, 2)}</pre></section><section><h3>Your draft</h3><pre>{JSON.stringify(value, null, 2)}</pre></section></div> : <fieldset disabled={saving}>{form}</fieldset>}{card !== undefined && <div className="harness-config__card" role="status">{typeof card === "string" ? <p>{card}</p> : <details><summary>Verified Agent Card</summary><pre>{JSON.stringify(card, null, 2)}</pre></details>}</div>}<div className="harness-editor__actions"><button type="button" disabled={!dirty || saving} onClick={discard}>Discard changes</button><button type="button" className="run-button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save configuration"}</button></div>{saveError && <div className="harness-editor__error" role="alert"><p>{saveError}</p><button type="button" onClick={async () => { if (await load()) discard(); }}>Reload saved version</button></div>}{success && <p className="harness-editor__success" role="status">{success}</p>}</section>;
}
