import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import DelimitedInput from "./DelimitedInput";

type Scenario = { id: string; title: string; request: string; required_tools: string[]; required_contexts: string[]; answer_contains: string[] };
type EvaluationConfig = { timeout_seconds: number; minimum_score: number; weights: Record<string, number>; scenarios: Scenario[] };
type Check = { name: string; passed: boolean; evidence: string; weight: number };
type Result = { id: string; title: string; score: number; passed: boolean; categories: Record<string, Check[]>; scenario_checks: Check[]; events: { count: number; duration_seconds: number }; tool_trace: { specialist: string; name: string; state: string; context_ids: string[]; domains: string[] }[]; final_chat_answer: string; final_rpt: unknown; rpt_status?: Record<string, { event: string; provider: string; reason: string }>; joule: { status: string; reason?: string }; sse_trace: unknown[]; error?: string; transport_error?: string };
type Run = { id: string; state: string; revision: number; started_at: number; scenario_count: number; message?: string; report?: { overall_score: number; scenarios: Result[] } };
const labels: Record<string, string> = { tool_a2a: "Tool / A2A integration", grounding_context: "Grounding & context", agent_collaboration: "Agent collaboration", chat_quality: "Chat quality", rpt_completion: "RPT completion" };

export default function EvaluationPanel({ onSaved, settingsEpoch }: { onSaved: () => void; settingsEpoch: number }) {
  const [config, setConfig] = useState<EvaluationConfig>();
  const [original, setOriginal] = useState<EvaluationConfig>();
  const [revision, setRevision] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run>();
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef<AbortController | undefined>(undefined);
  const selectedRun = useRef<string | undefined>(undefined);
  selectedRun.current = run?.id;
  const draftRef = useRef({ config, original });
  draftRef.current = { config, original };
  const load = useCallback(async (discard = false) => {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setLoading(true); setError("");
    try {
      const [configuration, history] = await Promise.all([fetch("/api/harness/configuration", { signal: controller.signal }), fetch("/api/harness/evaluations", { signal: controller.signal })]);
      if (!configuration.ok || !history.ok) throw new Error();
      const value = await configuration.json() as { revision: number; sections: { evaluation: EvaluationConfig } };
      const recorded = await history.json() as { runs: Run[] };
      if (controller.signal.aborted) return;
      const current = draftRef.current;
      const edited = JSON.stringify(current.config) !== JSON.stringify(current.original);
      if (discard || !edited) {
        setConfig(value.sections.evaluation); setOriginal(value.sections.evaluation); setRevision(value.revision);
        setSelected(value.sections.evaluation.scenarios.map((item) => item.id));
      } else if (JSON.stringify(current.original) === JSON.stringify(value.sections.evaluation)) setRevision(value.revision);
      setRuns(recorded.runs);
      if (recorded.runs[0]) setRun((current) => current ?? recorded.runs[0]);
    } catch { if (!controller.signal.aborted) setError("Could not load evaluation settings or history. Retry the Gateway connection."); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => { void load(); return () => pending.current?.abort(); }, [load, settingsEpoch]);
  const refresh = useCallback(async (identity: string) => {
    try {
      const response = await fetch("/api/harness/evaluations/" + identity);
      if (!response.ok) throw new Error();
      const result = await response.json() as Run;
      if (selectedRun.current === identity) setRun(result);
      setRuns((current) => current.map((item) => item.id === identity ? result : item));
    } catch { setError("Could not retrieve this evaluation. Partial evidence remains on the server."); }
  }, []);
  useEffect(() => {
    if (!run?.id) return;
    void refresh(run.id);
    if (run.state !== "running") return;
    const timer = window.setInterval(() => void refresh(run.id), 2000);
    return () => window.clearInterval(timer);
  }, [run?.id, run?.state, refresh]);
  const edit = (change: (next: EvaluationConfig) => void) => { if (config) { const copy = structuredClone(config); change(copy); setConfig(copy); setNotice(""); } };
  const dirty = JSON.stringify(config) !== JSON.stringify(original);
  const save = async () => {
    if (!config || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await fetch("/api/harness/configuration", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: "evaluation", value: config, expected_revision: revision }) });
      const value = await response.json() as { revision: number; sections: { evaluation: EvaluationConfig }; error?: { message?: string } };
      if (!response.ok) throw new Error(value.error?.message ?? "Could not save evaluation settings.");
      setRevision(value.revision); setConfig(value.sections.evaluation); setOriginal(value.sections.evaluation); setSelected(value.sections.evaluation.scenarios.map((item) => item.id));
      setNotice("Saved evaluation configuration revision " + value.revision + "."); onSaved();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save evaluation settings."); }
    finally { setSaving(false); }
  };
  const start = async () => {
    setStarting(true); setError("");
    try {
      const response = await fetch("/api/harness/evaluations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_ids: selected, expected_revision: revision }) });
      const value = await response.json() as Run & { error?: { message?: string } };
      if (!response.ok) throw new Error(value.error?.message ?? "Could not start the evaluation.");
      setRun(value); setRuns((current) => [value, ...current]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start the evaluation."); }
    finally { setStarting(false); }
  };
  if (loading) return <div className="harness-studio__state" role="status"><p>Loading evaluations…</p></div>;
  if (!config) return <div className="harness-studio__state" role="alert"><p>{error}</p><button type="button" onClick={() => void load()}>Retry</button></div>;
  return <section className="harness-editor harness-config" aria-label="Harness evaluation">
    <div className="harness-editor__revision"><span>Evaluation configuration revision {revision}</span><p>Each run uses an isolated Chat session per scenario and one pinned settings revision.</p></div>
    <h2>Scenario evaluation</h2><p>Evaluate Tool Registry / A2A integration, SOP context, collaboration, English Chat and RPT completion. Joule availability is reported separately.</p>
    <div className="harness-config__checks">{config.scenarios.map((scenario) => <label className="harness-config__checkbox" key={scenario.id}><input type="checkbox" checked={selected.includes(scenario.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, scenario.id] : current.filter((id) => id !== scenario.id))} />{scenario.title}</label>)}</div>
    <button type="button" className="run-button" disabled={starting || run?.state === "running" || dirty || !selected.length} onClick={() => void start()}>{starting ? "Starting…" : run?.state === "running" ? "Evaluation running…" : "Run selected scenarios"}</button>
    {dirty && <p>Save the evaluation settings before starting a run.</p>}
    <details className="harness-config__card"><summary>Evaluation settings</summary><fieldset disabled={saving}>
      <div className="harness-config__grid"><label className="harness-config__field">Scenario timeout (seconds)<input type="number" min="10" max="900" value={config.timeout_seconds} onChange={(event) => edit((next) => { next.timeout_seconds = Number(event.target.value); })} /></label><label className="harness-config__field">Minimum score<input type="number" min="0" max="100" value={config.minimum_score} onChange={(event) => edit((next) => { next.minimum_score = Number(event.target.value); })} /></label></div>
      <h3>Rubric weights · total 100</h3><div className="harness-config__grid">{Object.entries(config.weights).map(([key, weight]) => <label className="harness-config__field" key={key}>{labels[key]}<input type="number" min="0" max="100" value={weight} onChange={(event) => edit((next) => { next.weights[key] = Number(event.target.value); })} /></label>)}</div>
      {config.scenarios.map((scenario, index) => <section className="harness-config__card" key={index}><div className="harness-config__grid">{(["id", "title"] as const).map((key) => <label className="harness-config__field" key={key}>{key === "id" ? "Scenario ID" : "Title"}<input value={scenario[key]} onChange={(event) => edit((next) => { next.scenarios[index][key] = event.target.value; })} /></label>)}</div><label className="harness-config__field">Operational request<textarea value={scenario.request} onChange={(event) => edit((next) => { next.scenarios[index].request = event.target.value; })} /></label>{(["required_tools", "required_contexts", "answer_contains"] as const).map((key) => <DelimitedInput key={key} label={key.replaceAll("_", " ") + " (comma separated)"} value={scenario[key]} onChange={(values) => edit((next) => { next.scenarios[index][key] = values; })} />)}<button type="button" disabled={config.scenarios.length < 2} onClick={() => edit((next) => { next.scenarios.splice(index, 1); })}>Remove scenario</button></section>)}
      <button type="button" onClick={() => edit((next) => { next.scenarios.push({ id: "custom_" + (next.scenarios.length + 1), title: "Custom scenario", request: "Review the documented operational evidence.", required_tools: [], required_contexts: [], answer_contains: [] }); })}>Add scenario</button>
      <div className="harness-editor__actions"><button type="button" disabled={!dirty} onClick={() => { setConfig(original); setError(""); }}>Discard changes</button><button type="button" className="run-button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save evaluation settings"}</button></div>
    </fieldset></details>
    {error && <div className="harness-editor__error" role="alert"><p>{error}</p><button type="button" onClick={() => void load(true)}>Reload saved settings</button>{run && <button type="button" onClick={() => void refresh(run.id)}>Retry result</button>}</div>}
    {notice && <p className="harness-editor__success" role="status">{notice}</p>}
    {runs.length > 0 && <label className="harness-editor__select">Run history<select value={run?.id ?? ""} onChange={(event) => { setRun(runs.find((item) => item.id === event.target.value)); }}>{runs.map((item) => <option key={item.id} value={item.id}>{new Date(item.started_at * 1000).toLocaleString("en-US")} · revision {item.revision} · {item.state}</option>)}</select></label>}
    {run && <section className="harness-config__card" aria-label="Evaluation results"><h3>{run.state === "running" ? "Live evaluation" : "Evaluation " + run.state}</h3><p role="status">Revision {run.revision} · {run.report?.scenarios.length ?? 0} / {run.scenario_count} scenarios recorded{run.message ? " · " + run.message : ""}</p>{run.report && <><b>Overall score: {run.report.overall_score.toFixed(1)} / 100</b>{run.report.scenarios.map((result) => <details className="harness-config__card" key={result.id}><summary>{result.title} · {result.score} / 100 · {result.passed ? "PASS" : "FAIL"}</summary><p>{result.events.duration_seconds}s · {result.events.count} events</p>{(result.error || result.transport_error) && <p>{result.error ?? result.transport_error}</p>}<div className="harness-config__grid">{Object.entries(result.categories).map(([key, checks]) => <section key={key}><h4>{labels[key]}</h4>{checks.map((item) => <p key={item.name}>{item.passed ? "PASS" : "FAIL"} · {item.name}<br /><small>{item.evidence}</small></p>)}</section>)}</div><h4>Scenario assertions</h4>{result.scenario_checks.map((item) => <p key={item.name}>{item.passed ? "PASS" : "FAIL"} · {item.name}</p>)}<h4>Tool trace</h4>{result.tool_trace.map((item, index) => <p key={index}><code>{item.name}</code> · {item.specialist}<br />{item.context_ids.join(", ")} · {item.domains.join(", ")} · {item.state}</p>)}<h4>Final Chat</h4><ReactMarkdown remarkPlugins={[remarkGfm]}>{result.final_chat_answer || "No final Chat answer."}</ReactMarkdown><h4>RPT provider status</h4>{Object.entries(result.rpt_status ?? {}).map(([key, item]) => <p key={key}>{key}: {item.event} · {item.provider ?? "Unavailable"}<br />{item.reason}</p>)}<details><summary>Final RPT decision</summary><pre>{JSON.stringify(result.final_rpt, null, 2)}</pre></details><p>Joule: {result.joule.status} · {result.joule.reason}</p><details><summary>SSE event trace</summary><pre>{JSON.stringify(result.sse_trace, null, 2)}</pre></details></details>)}</>}</section>}
  </section>;
}
