import { useEffect, useState } from "react";
import jouleLogo from "./assets/joule.png";
import sapLogo from "./assets/sap_logo.png";
import "./harness-learning.css";

type Step = {
  eyebrow: string;
  title: string;
  description: string;
  detail: string;
  control: string;
  active: string[];
};

const steps: Step[] = [
  {
    eyebrow: "01 · INPUT",
    title: "현장 요청을 안전하게 접수합니다",
    description: "현장 운영자가 CIP 펌프 메커니컬 실 키트의 구매 검토를 요청합니다. Harness는 요청을 실행 지시가 아닌 검토 입력으로 취급합니다.",
    detail: "",
    control: "",
    active: ["request", "orchestrator"],
  },
  {
    eyebrow: "02 · DISCOVER",
    title: "등록된 Agent Card를 발견합니다",
    description: "Custom Extension Assistant는 사용할 수 있는 Team Agent의 공개 카드와 역할을 확인합니다. 요청에 맞는 후보만 다음 판단에 남깁니다.",
    detail: "카드는 각 Team의 역할과 A2A 입력·출력 방식을 설명하지만, Harness가 카드 자체를 바꾸지는 않습니다.",
    control: "Agent Card는 등록 정보이며 runtime overlay로 변경하지 않음",
    active: ["orchestrator", "cards"],
  },
  {
    eyebrow: "03 · OBSERVE",
    title: "SOP 문서에서 업무 근거를 확인합니다",
    description: "Grounding이 SOP Data Documents에서 요청과 관련된 절차와 운영 기준을 찾습니다. Custom Extension Assistant는 이 근거를 요청 및 대화 맥락과 함께 확인합니다.",
    detail: "확인한 SOP 근거는 다음 단계에서 Team Agent에 전달할 검토 맥락이 됩니다.",
    control: "대화 이력은 길이와 문자 수를 제한해 전달",
    active: ["orchestrator", "grounding-return"],
  },
  {
    eyebrow: "04 · A2A HANDOFF",
    title: "Team Agent에 검토를 위임합니다",
    description: "선택된 Team에 목적, 요청, Grounding, 누적 Artifact를 담은 A2A Message와 Task를 전달합니다. 예시에서는 설비·구매 관점의 Team이 후보가 됩니다.",
    detail: "전달 봉투에는 대상 Agent ID와 purpose가 필요합니다. 등록되지 않은 대상은 즉시 거부됩니다.",
    control: "A2A 계약과 JSON 형식은 변경 불가",
    active: ["orchestrator", "team", "handoff"],
  },
  {
    eyebrow: "05 · TEAM EXECUTION",
    title: "전문가와 읽기 전용 도구가 근거를 만듭니다",
    description: "Team Agent는 필요한 Specialist를 선택합니다. Specialist는 역할별 allow-list 안에서만 로컬 CSV/HANA snapshot 도구를 호출하고, Team은 결과를 하나의 Artifact로 합성합니다.",
    detail: "예: 구매조달 Agent와 재고·수급 Agent가 공급·재고 근거를 수집한 뒤 Team review를 반환합니다.",
    control: "Sub-agent별 Tool allow-list · 데이터는 읽기 전용",
    active: ["team", "specialist", "data", "artifact"],
  },
  {
    eyebrow: "06 · LOOP + COMPLETE",
    title: "Artifact를 검토하고 다음 작업을 분기합니다",
    description: "A2A Artifact를 받은 Custom Extension Assistant는 ReAct로 근거를 다시 검토합니다. 추가 검토가 필요하면 Team Assistant에 재위임하고, 근거가 충분하면 최종 Synthesis Artifact를 만듭니다.",
    detail: "실선은 Artifact 반환과 최종 Synthesis, 점선은 추가 근거가 필요할 때의 재위임 경로입니다. 반복은 최대 8회입니다.",
    control: "반복 횟수 상한 · 승인 대기 상태를 명시",
    active: ["artifact", "orchestrator", "team", "loop", "redelegate", "synthesis"],
  },
  {
    eyebrow: "07 · RPT + HITL",
    title: "RPT 판단 후 사람 검토를 연결합니다",
    description: "최종 Artifact는 RPT Decision Model로 전달됩니다. 검토가 필요하다고 판단되면 Human-in-the-Loop에 승인 또는 추가 의견을 요청합니다.",
    detail: "HITL 입력은 최종 응답의 근거로만 반영되며, 외부 시스템을 직접 변경하지 않습니다.",
    control: "RPT 판단 근거 공개 · 사람 승인 전 외부 실행 없음",
    active: ["artifact", "rpt", "hitl"],
  },
];

const englishSteps: Step[] = [
  { eyebrow: "01 · INPUT", title: "Receive the field request safely", description: "An operator asks to review the purchase of a CIP pump mechanical seal kit. The Harness treats this as review input, not an execution instruction.", detail: "", control: "", active: ["request", "orchestrator"] },
  { eyebrow: "02 · DISCOVER", title: "Discover registered Agent Cards", description: "The Custom Extension Assistant inspects the public cards and roles of available Team Agents, retaining only candidates relevant to the request.", detail: "Cards describe each Team's role and A2A input and output contract. The Harness never changes a card.", control: "Agent Cards are registered metadata · No runtime mutation", active: ["orchestrator", "cards"] },
  { eyebrow: "03 · OBSERVE", title: "Ground the request with SOP documents", description: "Grounding finds relevant procedures and operating criteria in SOP Data Documents. The Custom Extension Assistant reviews this evidence alongside the request and conversation context.", detail: "The SOP evidence becomes part of the review context passed to the Team Agent in the next step.", control: "Conversation history is bounded by length and character count", active: ["orchestrator", "grounding-return"] },
  { eyebrow: "04 · A2A HANDOFF", title: "Delegate the review to a Team Agent", description: "The selected Team receives an A2A Message and Task containing the purpose, request, grounding, and accumulated Artifacts.", detail: "The handoff envelope requires a registered target Agent ID and purpose. Unknown targets are rejected immediately.", control: "A2A contract and JSON schema are immutable", active: ["orchestrator", "team", "handoff"] },
  { eyebrow: "05 · TEAM EXECUTION", title: "Create evidence with specialists and read-only tools", description: "The Team Agent selects the required Specialists. Each Specialist can only use the tools in its role-specific allow-list, then the Team synthesizes one Artifact.", detail: "For example, procurement and inventory specialists collect supply and stock evidence before returning their Team review.", control: "Per-specialist tool allow-list · Read-only data", active: ["team", "specialist", "data", "artifact"] },
  { eyebrow: "06 · LOOP + COMPLETE", title: "Review the Artifact and branch the next action", description: "The Custom Extension Assistant receives the A2A Artifact and re-evaluates the evidence with ReAct. It re-delegates to the Team Assistant when more review is needed, or creates a final Synthesis Artifact when the evidence is sufficient.", detail: "Solid lines show Artifact return and final synthesis. The dashed line shows re-delegation when more evidence is needed. The loop is capped at eight iterations.", control: "Iteration limit · Explicit approval-pending state", active: ["artifact", "orchestrator", "team", "loop", "redelegate", "synthesis"] },
  { eyebrow: "07 · RPT + HITL", title: "Connect human review after the RPT decision", description: "The final Artifact is passed to the RPT Decision Model. When review is required, Human-in-the-Loop receives an approval or additional-evidence request.", detail: "HITL input is used only as evidence for the final response and never changes an external system directly.", control: "Visible RPT evidence · No external execution before human approval", active: ["artifact", "rpt", "hitl"] },
];

const stepFlows = [
  ["Field Request", "Custom Extension Assistant"],
  ["Skills + Agent Cards", "Custom Extension Assistant"],
  ["SOP Documents", "Grounding", "Custom Extension Assistant"],
  ["Custom Extension Assistant", "Team Assistant"],
  ["Team Assistant", "Read-only Tools", "Business Data", "A2A Artifact"],
  ["A2A Artifact", "Custom Extension Assistant", "Team Assistant · more evidence", "A2A Artifact · final synthesis"],
  ["A2A Artifact", "RPT Decision Model", "Human in the Loop"],
];

const stepConnections = [
  [{ en: "Request intake", ko: "요청 접수" }],
  [{ en: "Card discovery", ko: "Agent Card 조회" }],
  [{ en: "SOP retrieval", ko: "SOP 검색" }, { en: "SOP evidence", ko: "SOP 근거 전달" }],
  [{ en: "A2A: Delegation · Handoff", ko: "A2A: 검토 위임 · Handoff" }],
  [{ en: "Tool calling", ko: "도구 호출" }, { en: "Data lookup", ko: "업무 데이터 조회" }, { en: "Artifact synthesis", ko: "Artifact 생성" }],
  [{ en: "A2A: Artifact return", ko: "A2A: Artifact 반환" }, { en: "More evidence: Re-delegate", ko: "추가 검토 필요 시 재위임" }, { en: "Evidence sufficient: Final synthesis", ko: "근거 충분: 최종 Synthesis" }],
  [{ en: "RPT decision", ko: "RPT 판단" }, { en: "Human review", ko: "사람 검토 요청" }],
];

function Diagram({ active, sequence, connectionLabels, language }: { active: string[]; sequence: string[]; connectionLabels: string[]; language: "ko" | "en" }) {
  const isActive = (id: string) => active.includes(id);
  const routes = [
    { id: "request", path: "M270 85H330Q350 85 365 100L395 120", x: 330, y: 68 },
    { id: "cards", path: "M270 195H390", x: 330, y: 177 },
    { id: "grounding-return", path: "M800 115V165", x: 820, y: 144, side: true },
    { id: "grounding-return", path: "M690 195H562", x: 626, y: 177 },
    { id: "handoff", path: "M462 240Q420 275 290 275Q210 275 210 295", x: 325, y: 254 },
    { id: "specialist", path: "M287 365H335Q350 365 350 380H380", x: 333, y: 345 },
    { id: "data", path: "M600 380H690", x: 645, y: 363 },
    { id: "data", path: "M800 410V500", x: 820, y: 457, side: true },
    { id: "loop", path: "M910 530H935V285H600Q562 285 562 195", x: 750, y: 268 },
    { id: "redelegate", path: "M462 240Q420 275 290 275Q210 275 210 295", x: 325, y: 254, conditional: true },
    { id: "synthesis", path: "M562 195C630 255 646 420 720 500", x: 685, y: 450 },
    { id: "rpt", path: "M690 530H600", x: 645, y: 513 },
    { id: "hitl", path: "M380 530H270", x: 325, y: 513 },
  ];
  const activeRoutes = routes.filter((route) => isActive(route.id));
  const nodes = [
    { id: "request", label: "FIELD REQUEST", x: 50, y: 55 },
    { id: "cards", label: "SKILLS + AGENT CARDS", x: 50, y: 165 },
    { id: "grounding-return", label: "SOP DATA DOCUMENTS", x: 690, y: 55 },
    { id: "grounding-return", label: "GROUNDING", x: 690, y: 165 },
    { id: "specialist", label: "READ-ONLY TOOLS", x: 380, y: 350 },
    { id: "data", label: "BUSINESS DATA", x: 690, y: 350 },
    { id: "artifact", label: "A2A ARTIFACT", x: 690, y: 500 },
    { id: "rpt", label: "RPT DECISION MODEL", x: 380, y: 500 },
    { id: "hitl", label: "HUMAN IN THE LOOP", x: 50, y: 500 },
  ];
  return (
    <div className="learning-diagram">
      <svg className="iso-diagram" viewBox="0 0 960 595" role="img" aria-label="A2A Custom Extension Assistant flow">
        <defs>
          <linearGradient id="server-top" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#edf6ff"/><stop offset="1" stopColor="#cadff6"/></linearGradient>
          <linearGradient id="server-side" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#adc9e9"/><stop offset="1" stopColor="#87acd8"/></linearGradient>
          <marker id="arrow" viewBox="0 0 10 10" markerWidth="7" markerHeight="7" refX="9" refY="5" orient="auto"><path d="M0 1L9 5L0 9Z" fill="var(--green-strong)"/></marker>
        </defs>
        {activeRoutes.map((route, index) => (
          <g key={route.path}>
            <path className={route.conditional ? "iso-link active conditional" : "iso-link active"} d={route.path} markerEnd="url(#arrow)" />
            {!route.conditional && <circle className="flow-particle" r="4" visibility="hidden">
              <set attributeName="visibility" to="visible" begin={`${index * .35}s`} />
              <animateMotion dur="2.4s" begin={`${index * .35}s`} repeatCount="indefinite" path={route.path} />
            </circle>}
          </g>
        ))}
        {isActive("redelegate") && <text className="iso-route-label react-label" x="480" y="267" textAnchor="middle">{language === "en" ? "ReAct: Re-evaluate" : "ReAct: 근거 재판단"}</text>}
        {activeRoutes.map((route, index) => (
          <text key={route.path} className="iso-route-label" x={route.x} y={route.y} textAnchor={route.side ? "start" : "middle"}>
            {connectionLabels[index]}
          </text>
        ))}
        <g transform="translate(30 15) scale(.85)" className={`iso-node people ${isActive("team") ? "active" : ""}`}>
          <path d="M65 393L188 323L302 390L179 467Z" fill="#f5f0e8" stroke="#282523" strokeWidth="4"/><path d="M65 393V419L179 493V467Z" fill="#e5ddd1" stroke="#282523" strokeWidth="4"/><path d="M179 467L302 390V416L179 493Z" fill="#d4cabd" stroke="#282523" strokeWidth="4"/>
          {[ [128,377,"#a98ad4"], [172,355,"#83afd7"], [216,382,"#f4be67"], [151,419,"#f0a367"], [198,424,"#95c987"], [241,410,"#a98ad4"] ].map(([x,y,color], index) => <g key={index} className="person"><circle cx={Number(x)} cy={Number(y)-16} r="10" fill="#fffaf2" stroke="#282523" strokeWidth="4"/><path d={`M${x} ${Number(y)-5}q-13 8-10 27h20q3-19-10-27Z`} fill={String(color)} stroke="#282523" strokeWidth="4"/></g>)}
          <text x="183" y="526" className="iso-label" textAnchor="middle">TEAM ASSISTANT</text>
        </g>
        <g transform="translate(140 -20) scale(.7)" className={`iso-node server ${isActive("orchestrator") ? "active" : ""}`}>
          <path d="M430 128Q480 96 530 128L602 170V285Q602 310 580 322L500 370Q480 382 460 370L380 322Q358 310 358 285V170Z" fill="url(#server-side)" stroke="#282523" strokeWidth="5"/>
          <path d="M358 170L458 226Q480 238 502 226L602 170L530 128Q480 96 430 128Z" fill="url(#server-top)" stroke="#282523" strokeWidth="5"/>
          <image href={sapLogo} x="448" y="184" width="64" height="36" preserveAspectRatio="xMidYMid meet"/>
          <text x="480" y="282" className="iso-label" textAnchor="middle">CUSTOM EXTENSION ASSISTANT</text>
        </g>
        {nodes.map((node) => (
          <g key={node.label} className={`iso-node ${isActive(node.id) ? "active" : ""}`}>
            <rect x={node.x} y={node.y} width="220" height="60" rx="16" fill="#fffaf2" stroke="#282523" strokeWidth="2.5" />
            <text x={node.x + 110} y={node.y + 31} className="iso-label" textAnchor="middle" dominantBaseline="middle">{node.label}</text>
          </g>
        ))}
      </svg>
      <ol className="learning-mobile-flow">
        {sequence.map((label, index) => (
          <li key={label} className={isActive("redelegate") && index === 2 ? "conditional" : isActive("synthesis") && index === 3 ? "alternative" : undefined}>
            {index > 0 && <span className="learning-mobile-connection"><span>{connectionLabels[index - 1]}</span><span aria-hidden="true">↓</span></span>}
            {label}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function HarnessLearningPage({ language = "en" }: { language?: "ko" | "en" } = {}) {
  const [step, setStep] = useState(0);
  const activeSteps = language === "en" ? englishSteps : steps;
  const current = activeSteps[step];
  const connectionLabels = stepConnections[step].map((connection) => connection[language]);
  const copy = language === "en"
    ? {
        previous: "← Previous",
        next: "Next →",
        diagram: "Step",
        navigation: "Select a step",
      }
    : {
        previous: "← 이전",
        next: "다음 →",
        diagram: "단계",
        navigation: "단계 선택",
      };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select, [contenteditable=true]")) return;
      if (event.key === "ArrowRight") setStep((value) => Math.min(value + 1, steps.length - 1));
      if (event.key === "ArrowLeft") setStep((value) => Math.max(value - 1, 0));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <main className="harness-learning">
      <header className="learning-header">
        <a href="#/" className="learning-brand"><img src={jouleLogo} alt="Joule" /><span><b>Custom Extension Assistant Harness</b><small>INTERACTIVE ARCHITECTURE</small></span></a>
        <div className="learning-header-actions">
          <a className="back-to-console" href="#/">← {language === "en" ? "Back to console" : "콘솔로 돌아가기"}</a>
        </div>
      </header>
      <section className="learning-shell">
        <section className="learning-copy">
          <nav className="learning-step-list" aria-label={copy.navigation}>
            {activeSteps.map((item, index) => (
              <button key={item.eyebrow} type="button" aria-label={item.eyebrow + ": " + item.title} aria-current={index === step ? "step" : undefined} onClick={() => setStep(index)}>
                {String(index + 1).padStart(2, "0")}
              </button>
            ))}
          </nav>
          <p className="learning-eyebrow">{current.eyebrow}</p>
          <h1>{current.title}</h1>
          <p className="learning-description">{current.description}</p>
          {current.detail && <p className="learning-detail">{current.detail}</p>}
          <nav className="step-controls" aria-label={copy.navigation}>
            <button type="button" onClick={() => setStep((value) => Math.max(value - 1, 0))} disabled={step === 0}>{copy.previous}</button>
            <button type="button" className="next" onClick={() => setStep((value) => Math.min(value + 1, steps.length - 1))} disabled={step === steps.length - 1}>{copy.next}</button>
            <span className="static-flow-label">{copy.diagram} {step + 1} / {steps.length}</span>
          </nav>
        </section>
        <section className="learning-canvas">
          <div className="canvas-header"><span>A2A CUSTOM EXTENSION ASSISTANT FLOW</span><span className="demo-chip">STEP {String(step + 1).padStart(2, "0")} · {current.eyebrow.replace(/^\d+ · /, "")}</span></div>
          <ol className="learning-flow" aria-label={current.title}>
            {stepFlows[step].map((label, index) => <li key={label} className={current.active.includes("redelegate") && index === 2 ? "conditional" : current.active.includes("synthesis") && index === 3 ? "alternative" : undefined}>{label}</li>)}
          </ol>
          <Diagram active={current.active} sequence={stepFlows[step]} connectionLabels={connectionLabels} language={language} />
        </section>
      </section>
    </main>
  );
}
