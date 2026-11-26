import { useCallback, useEffect, useRef, useState } from "react";
import "./harness-editor.css";

type Model = { name: string; deployment_id: string };
type AgentSetting = { agent_id: string; label: string; role: "orchestrator" | "team" | "specialist"; prompt: string; default_prompt: string; model: Model | null; variables: string[] };
type Manifest = { revision: number; shared_model: string; agents: AgentSetting[]; application: string };
type Draft = { prompt: string; model: Model | null; revision: number; savedPrompt: string; savedModel: Model | null };
const modelKey = (model: Model | null) => model ? model.name + ":" + model.deployment_id : "shared";
const initialDraft = (agent: AgentSetting, revision: number): Draft => ({ prompt: agent.prompt, model: agent.model ?? null, revision, savedPrompt: agent.prompt, savedModel: agent.model ?? null });

export default function PromptModelEditor({ onSaved, settingsEpoch }: { onSaved: () => void; settingsEpoch: number }) {
  const [manifest, setManifest] = useState<Manifest>();
  const [models, setModels] = useState<Model[]>([]);
  const [modelError, setModelError] = useState("");
  const [modelLoading, setModelLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState("orchestrator");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [view, setView] = useState<"edit" | "compare">("edit");
  const live = useRef(true);
  const pending = useRef<AbortController | undefined>(undefined);
  const modelPending = useRef<AbortController | undefined>(undefined);

  const load = useCallback(async () => {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/harness/prompts", { signal: controller.signal });
      if (!response.ok) throw new Error();
      const value = await response.json() as Manifest;
      if (!value || !Array.isArray(value.agents) || typeof value.revision !== "number") throw new Error();
      if (live.current && !controller.signal.aborted) {
        setManifest(value);
        setDrafts((current) => Object.fromEntries(Object.entries(current).map(([key, item]) => {
          const saved = value.agents.find((agent) => agent.agent_id === key);
          return [key, saved && item.savedPrompt === saved.prompt && modelKey(item.savedModel) === modelKey(saved.model) ? { ...item, revision: value.revision } : item];
        })));
      }
      return live.current && !controller.signal.aborted;
    } catch { if (live.current && !controller.signal.aborted) setError("Could not load Agent settings. Check the Gateway connection and retry."); return false; }
    finally { if (live.current && !controller.signal.aborted) setLoading(false); }
  }, []);
  const loadModels = useCallback(async () => {
    modelPending.current?.abort(); const controller = new AbortController(); modelPending.current = controller;
    setModelLoading(true); setModelError("");
    try {
      const response = await fetch("/api/harness/models", { signal: controller.signal });
      if (!response.ok) throw new Error();
      const value = await response.json() as { models: Model[] };
      if (!Array.isArray(value.models)) throw new Error();
      if (live.current && !controller.signal.aborted) setModels(value.models);
    } catch { if (live.current && !controller.signal.aborted) setModelError("Model deployments are unavailable. Prompt editing and the shared model remain available."); }
    finally { if (live.current && !controller.signal.aborted) setModelLoading(false); }
  }, []);
  useEffect(() => { live.current = true; void load(); void loadModels(); return () => { live.current = false; pending.current?.abort(); modelPending.current?.abort(); }; }, [load, loadModels]);
  useEffect(() => { if (settingsEpoch) void load(); }, [load, settingsEpoch]);

  const selected = manifest?.agents.find((agent) => agent.agent_id === selectedId) ?? manifest?.agents[0];
  const draft = selected && manifest ? drafts[selected.agent_id] ?? initialDraft(selected, manifest.revision) : undefined;
  const dirty = !!draft && (draft.prompt !== draft.savedPrompt || modelKey(draft.model) !== modelKey(draft.savedModel));
  const change = (values: Partial<Draft>) => {
    if (!selected || !draft) return;
    setDrafts((current) => ({ ...current, [selected.agent_id]: { ...draft, ...values } }));
    setSaveError(""); setSuccess("");
  };
  const discard = () => {
    if (!selected) return;
    setDrafts((current) => { const next = { ...current }; delete next[selected.agent_id]; return next; });
    setSaveError(""); setSuccess("");
  };
  const save = async () => {
    if (!selected || !draft || !dirty || saving) return;
    setSaving(true); setSaveError(""); setSuccess("");
    try {
      const payload: Record<string, unknown> = { agent_id: selected.agent_id, expected_revision: draft.revision };
      if (draft.prompt !== draft.savedPrompt) payload.prompt = draft.prompt === selected.default_prompt ? null : draft.prompt;
      if (modelKey(draft.model) !== modelKey(draft.savedModel)) payload.model = draft.model;
      const response = await fetch("/api/harness/prompts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const value = await response.json() as Manifest & { error?: { message?: string } };
      if (!response.ok) throw new Error(value.error?.message ?? "Could not save settings. Your draft is preserved.");
      setManifest(value);
      setDrafts((current) => { const next = { ...current }; delete next[selected.agent_id]; for (const [key, item] of Object.entries(next)) { const saved = value.agents.find((agent) => agent.agent_id === key); if (saved && saved.prompt === item.savedPrompt && modelKey(saved.model) === modelKey(item.savedModel)) next[key] = { ...item, revision: value.revision }; } return next; });
      setSuccess("Saved revision " + value.revision + ". New requests use these settings; running requests keep their original revision.");
      onSaved();
    } catch (cause) { setSaveError(cause instanceof Error ? cause.message : "Could not save settings. Your draft is preserved."); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="harness-studio__state" role="status"><span className="harness-studio__loader" /><p>Loading Prompts &amp; Models…</p></div>;
  if (error) return <div className="harness-studio__state" role="alert"><p>{error}</p><button type="button" className="panel-action icon-button" aria-label="Retry" title="Retry" onClick={() => void load()}><span aria-hidden="true">↻</span></button></div>;
  if (!manifest || !selected || !draft) return <p>No Agent settings available.</p>;
  const savedKey = modelKey(draft.model);
  return <section className="harness-editor" aria-label="Prompt and model editor">
    <div className="harness-editor__revision"><span>Saved revision {manifest.revision}</span><p>{manifest.application}</p></div>
    <div className="harness-editor__selection-layout">
      <nav className="harness-editor__selection-nav" aria-label="Agent selection">
        {(["orchestrator", "team", "specialist"] as const).map((role) => <section key={role} className="harness-editor__selection-group"><h3>{{ orchestrator: "Custom Extension Assistant", team: "Team Assistants", specialist: "Specialists" }[role]}</h3>{manifest.agents.filter((agent) => agent.role === role).map((agent) => <button key={agent.agent_id} type="button" className="harness-editor__selection-item" aria-pressed={selected.agent_id === agent.agent_id} disabled={saving} onClick={() => { setSelectedId(agent.agent_id); setSaveError(""); setSuccess(""); }}><span>{agent.label}</span>{drafts[agent.agent_id] && <small>Draft</small>}</button>)}</section>)}
      </nav>
      <div className="harness-editor__selection-content">
    <section className="harness-editor__model">
      <label className="harness-editor__select">Model deployment<select aria-label="Model deployment" value={savedKey} disabled={saving || modelLoading} onChange={(event) => change({ model: models.find((model) => modelKey(model) === event.target.value) ?? null })}>
        <option value="shared">Shared environment model · {manifest.shared_model}</option>
        {models.map((model) => <option key={modelKey(model)} value={modelKey(model)}>{model.name} · {model.deployment_id}</option>)}
        {draft.model && !models.some((model) => modelKey(model) === savedKey) && <option value={savedKey}>{draft.model.name} · saved deployment</option>}
      </select></label>
      {modelLoading && <p role="status">Discovering running AI Core deployments…</p>}
      {modelError && <div className="harness-editor__notice"><p>{modelError}</p><button type="button" className="icon-button" aria-label="Check models again" title="Check models again" onClick={() => void loadModels()}><span aria-hidden="true">↻</span></button></div>}
    </section>
    <div className="harness-editor__toolbar"><h2>{selected.label}</h2><div><button type="button" className="icon-button" aria-label="Edit" title="Edit" aria-pressed={view === "edit"} onClick={() => setView("edit")}><span aria-hidden="true">✎</span></button><button type="button" className="icon-button" aria-label="Compare changes" title="Compare changes" aria-pressed={view === "compare"} onClick={() => setView("compare")}><span aria-hidden="true">⇄</span></button></div></div>
    <p className="harness-editor__hint">{selected.variables.length ? "Optional variables: " + selected.variables.map((name) => "{" + name + "}").join(", ") + ". " : "This role has no template variables. "}Use double braces for literal JSON braces.</p>
    {view === "edit" ? <label className="harness-editor__prompt">System prompt<textarea value={draft.prompt} disabled={saving} spellCheck={false} onChange={(event) => change({ prompt: event.target.value })} /></label>
      : <div className="harness-editor__compare"><section><h3>Saved prompt</h3><pre>{draft.savedPrompt.split(String.fromCharCode(10)).map((line, index) => <span key={index} className={line !== draft.prompt.split(String.fromCharCode(10))[index] ? "removed" : ""}>{line || " "}{String.fromCharCode(10)}</span>)}</pre></section><section><h3>Your draft</h3><pre>{draft.prompt.split(String.fromCharCode(10)).map((line, index) => <span key={index} className={line !== draft.savedPrompt.split(String.fromCharCode(10))[index] ? "added" : ""}>{line || " "}{String.fromCharCode(10)}</span>)}</pre></section></div>}
    <div className="harness-editor__actions"><div><button type="button" className="icon-button" aria-label="Use defaults" title="Use defaults" disabled={saving} onClick={() => change({ prompt: selected.default_prompt, model: null })}><span aria-hidden="true">↺</span></button><button type="button" className="icon-button" aria-label="Discard changes" title="Discard changes" disabled={saving || !dirty} onClick={discard}><span aria-hidden="true">×</span></button></div><button type="button" className="run-button icon-button" aria-label={saving ? "Saving" : "Save settings"} title={saving ? "Saving" : "Save settings"} disabled={saving || !dirty || !draft.prompt.trim()} onClick={() => void save()}><span aria-hidden="true">{saving ? "◌" : "✓"}</span></button></div>
    {saveError && <div className="harness-editor__error" role="alert"><p>{saveError}</p><button type="button" className="icon-button" aria-label="Reload saved version" title="Reload saved version" disabled={saving} onClick={async () => { if (await load()) discard(); }}><span aria-hidden="true">↻</span></button></div>}
    {success && <p className="harness-editor__success" role="status">{success}</p>}
      </div>
    </div>
  </section>;
}
