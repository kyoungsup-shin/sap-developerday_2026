import { useEffect, useRef, useState } from "react";
import "./harness-studio.css";
import PromptModelEditor from "./PromptModelEditor";
import EvaluationPanel from "./EvaluationPanel";
import ConfigurationEditor, { ConfigurationSection } from "./ConfigurationEditor";

type StudioSection = ConfigurationSection | "prompts" | "evaluation";
const settings: { id: StudioSection; title: string; description: string }[] = [
  { id: "agents", title: "Agents & A2A", description: "Configure Teams, Specialists and external Agents." },
  { id: "prompts", title: "Prompts & Models", description: "Edit Agent instructions and choose deployed models." },
  { id: "tools", title: "Tools", description: "Define Tool descriptions and Specialist permissions." },
  { id: "data", title: "Business Data", description: "Edit sample records and preview CSV datasets." },
  { id: "grounding", title: "Grounding", description: "Configure the SOP repository and evidence prompts." },
  { id: "runtime", title: "Runtime", description: "Set execution limits, timeouts and human review." },
  { id: "rpt", title: "RPT Decision", description: "Customize decision criteria, examples and prompts." },
  { id: "joule", title: "Joule", description: "Connect and verify a deployed Joule Work Agent." },
  { id: "evaluation", title: "Evaluation", description: "Manage scenarios, run evaluations and review results." },
];

export default function HarnessStudio({ onSettingsSaved }: { onSettingsSaved: () => void }) {
  const [active, setActive] = useState<StudioSection | null>(null);
  const [promptsVisited, setPromptsVisited] = useState(false);
  const [evaluationVisited, setEvaluationVisited] = useState(false);
  const [configVisited, setConfigVisited] = useState(false);
  const [configSection, setConfigSection] = useState<ConfigurationSection>("agents");
  const [settingsEpoch, setSettingsEpoch] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const cards = useRef<Partial<Record<StudioSection, HTMLButtonElement | null>>>({});
  const lastCard = useRef<StudioSection | null>(null);
  const selected = settings.find((item) => item.id === active);
  const configVisible = active !== null && active !== "prompts" && active !== "evaluation";

  const open = (section: StudioSection) => {
    lastCard.current = section;
    if (section === "prompts") setPromptsVisited(true);
    else if (section === "evaluation") setEvaluationVisited(true);
    else { setConfigSection(section); setConfigVisited(true); }
    setActive(section);
  };
  const saved = () => { setSettingsEpoch((value) => value + 1); onSettingsSaved(); };

  useEffect(() => {
    if (active !== null) {
      heading.current?.focus();
      heading.current?.closest(".harness-studio-container")?.scrollTo({ top: 0 });
    } else if (lastCard.current !== null) {
      cards.current[lastCard.current]?.focus();
    }
  }, [active]);

  return <section className="harness-studio" aria-labelledby="harness-studio-title">
    <header className="harness-studio__heading">
      {selected
        ? <><button type="button" className="ghost-button icon-button" aria-label="Back to settings" title="Back to settings" onClick={() => setActive(null)}><span aria-hidden="true">←</span></button><h1 ref={heading} tabIndex={-1} id="harness-studio-title">{selected.title}</h1></>
        : <div><h1 id="harness-studio-title">Harness Studio</h1><p>Choose a setting to customize your Harness.</p></div>}
    </header>
    <div className="harness-studio__cards" hidden={active !== null}>
      {settings.map((item) => <button type="button" className="harness-studio__card" key={item.id}
        ref={(element) => { cards.current[item.id] = element; }}
        aria-labelledby={"studio-card-" + item.id} aria-describedby={"studio-description-" + item.id}
        onClick={() => open(item.id)}>
        <span className="harness-studio__card-title" id={"studio-card-" + item.id}>{item.title}</span>
        <span className="harness-studio__card-description" id={"studio-description-" + item.id}>{item.description}</span>
      </button>)}
    </div>
    {/* Keep visited editors mounted so navigation preserves drafts and evaluation polling. */}
    {promptsVisited && <div hidden={active !== "prompts"}><PromptModelEditor onSaved={saved} settingsEpoch={settingsEpoch} /></div>}
    {configVisited && <div hidden={!configVisible}><ConfigurationEditor section={configSection} onSaved={saved} settingsEpoch={settingsEpoch} /></div>}
    {evaluationVisited && <div hidden={active !== "evaluation"}><EvaluationPanel onSaved={saved} settingsEpoch={settingsEpoch} /></div>}
  </section>;
}
