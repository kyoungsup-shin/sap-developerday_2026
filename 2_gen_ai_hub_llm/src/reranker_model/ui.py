"""Gradio views specific to the Gen AI Hub LLM notebooks.

The functions create UI blocks but never launch a public share link.  A notebook
explicitly calls ``launch(inline=True)`` when the learner is ready.
"""
from __future__ import annotations

import os
from html import escape
from collections.abc import Iterator
from typing import Any, Callable

from .lesson_support.config import load_settings
from .demo_cases import ORDER_RISK_DEMO_CASES


def _gradio():
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError("Gradio가 없습니다. python3 -m pip install --user -r requirements.txt 를 실행하세요.") from error
    return gr


def _light_theme(gr):
    """Keep notebook-local Gradio UIs light regardless of OS appearance."""
    base = gr.themes.Base(primary_hue=gr.themes.colors.blue)
    values = base.to_dict()["theme"]
    return base.set(**{
        f"{name}_dark": value
        for name, value in values.items()
        if not name.endswith("_dark") and f"{name}_dark" in values
    })


def _history_messages(history: list[Any] | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in history or []:
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
            messages.append({"role": item["role"], "content": str(item.get("content", ""))})
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            messages.extend([
                {"role": "user", "content": str(item[0])},
                {"role": "assistant", "content": str(item[1])},
            ])
    return messages


def build_decision_reranker_ui(
    decision_runner: Callable[..., dict[str, Any]],
    candidates: list[dict[str, str]],
    default_min_margin: float = 0.0,
    default_min_score: float = 0.0,
    embedding_comparison_runner: Callable[..., dict[str, Any]] | None = None,
):
    """Create a read-only decision view backed by one public core API."""
    gr = _gradio()
    default_behavior = ORDER_RISK_DEMO_CASES[0]["case"]
    example_scenarios = [(case["name"], case["case"]) for case in ORDER_RISK_DEMO_CASES]
    candidate_summary = "\n".join(
        f"- **{candidate['label']}** — {candidate['description']}"
        for candidate in candidates
    )
    modal_css = """
    #decision-settings-modal {
      position: fixed !important; inset: 18vh 24vw auto !important; z-index: 1000 !important;
      max-width: 620px !important; padding: 20px !important; border: 1px solid #d0d7de !important;
      border-radius: 14px !important; background: white !important; box-shadow: 0 18px 60px rgba(0,0,0,.22) !important;
    }
    #decision-main-row { flex-wrap: nowrap !important; gap: 20px !important; align-items: stretch !important; }
    #decision-main-row > * { min-width: 0 !important; }
    .decision-panel { padding: 18px !important; border: 1px solid #d9e2f0 !important; border-radius: 14px !important; background: #fff !important; }
    #decision-example-card { margin-top: 14px !important; border: 1px solid #d9e2f0 !important; border-radius: 12px !important; background: #f8fbff !important; }
    #decision-example-card > .label-wrap { font-weight: 700 !important; }
    .decision-example-button { min-height: 42px !important; text-align: left !important; }
    .decision-result-empty, .decision-result { border: 1px solid #d9e2f0; border-radius: 14px; padding: 18px; background: #fff; }
    .decision-result-empty { color: #5f6368; background: #f8fbff; }
    .decision-result.review { border-left: 5px solid #f9ab00; }
    .decision-result.approve { border-left: 5px solid #1e8e3e; }
    .decision-result.decline { border-left: 5px solid #d93025; }
    .decision-result.error { border-left: 5px solid #d93025; background: #fff8f7; }
    .decision-result-header { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
    .decision-result-kicker { margin: 0; font-size: .78rem; font-weight: 700; color: #5f6368; letter-spacing: .04em; }
    .decision-result-title { margin: 4px 0 0; font-size: 1.45rem; color: #202124; }
    .decision-badge { display: inline-block; padding: 6px 10px; border-radius: 999px; font-size: .82rem; font-weight: 700; white-space: nowrap; }
    .decision-badge.review { background: #fef7e0; color: #8a5300; }
    .decision-badge.approve { background: #e6f4ea; color: #137333; }
    .decision-badge.decline { background: #fce8e6; color: #b3261e; }
    .decision-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }
    .decision-metric { padding: 12px; border-radius: 10px; background: #f8f9fa; }
    .decision-metric span { display: block; font-size: .78rem; color: #5f6368; }
    .decision-metric strong { display: block; margin-top: 4px; font-size: 1.25rem; color: #202124; }
    .decision-evidence { margin-top: 14px; padding-top: 14px; border-top: 1px solid #edf0f2; }
    .decision-evidence h4 { margin: 0 0 5px; font-size: .88rem; color: #3c4043; }
    .decision-evidence p { margin: 0; color: #5f6368; line-height: 1.55; }
    .decision-rankings { margin-top: 14px; }
    .decision-rankings h3 { margin: 0 0 10px; font-size: 1rem; color: #202124; }
    .decision-rank-row { display: grid; grid-template-columns: 28px minmax(90px, 1fr) minmax(100px, 2fr) 50px; align-items: center; gap: 8px; margin: 9px 0; }
    .decision-rank-label { color: #3c4043; font-size: .9rem; }
    .decision-progress { overflow: hidden; height: 9px; border-radius: 999px; background: #e8eaed; }
    .decision-progress > span { display: block; height: 100%; border-radius: inherit; background: #1a73e8; }
    .decision-rank-score { text-align: right; font-variant-numeric: tabular-nums; color: #3c4043; }
    .analysis-result { margin: 0; padding: 0; border: 0; background: transparent; }
    .analysis-result h3 { margin: 0 0 6px; font-size: 1rem; }
    .analysis-result p { margin: 0 0 10px; color: #5f6368; font-size: .88rem; line-height: 1.5; }
    .method-result-panel--embedding .analysis-result h3 { color: #1967d2; }
    .method-result-panel--reranker .analysis-result h3 { color: #7b1fa2; }
    .reranker-result .decision-badge { margin-left: 6px; vertical-align: middle; }
    .embedding-rank-row { display: grid; grid-template-columns: 28px minmax(90px, 1fr) minmax(100px, 2fr) 50px; align-items: center; gap: 8px; margin: 8px 0; }
    .embedding-progress { overflow: hidden; height: 9px; border-radius: 999px; background: #dce8fb; }
    .embedding-progress > span { display: block; height: 100%; border-radius: inherit; background: #4285f4; }
    #method-results-row { flex-wrap: nowrap !important; gap: 14px !important; align-items: stretch !important; }
    #method-results-row > * { min-width: 0 !important; }
    .method-result-panel { padding: 14px !important; border-radius: 14px !important; }
    .method-result-panel--embedding { border: 1px solid #8ab4f8 !important; background: #eef6ff !important; }
    .method-result-panel--reranker { border: 1px solid #c58af9 !important; background: #fbf3ff !important; }
    .method-result-card { width: 100%; }
    .method-result-heading { margin: 0 0 4px !important; font-size: 1.02rem !important; font-weight: 700 !important; }
    .method-result-heading--embedding { color: #1967d2 !important; }
    .method-result-heading--reranker { color: #7b1fa2 !important; }
    .method-result-caption { margin: 0 0 12px !important; color: #5f6368 !important; font-size: .84rem !important; }
    .reranker-summary { padding: 0; background: transparent; }
    @media (max-width: 760px) {
      #decision-main-row { flex-wrap: wrap !important; }
      #method-results-row { flex-wrap: wrap !important; }
      .decision-metrics { grid-template-columns: 1fr; }
      .decision-rank-row { grid-template-columns: 24px minmax(75px, 1fr) minmax(72px, 1fr) 44px; gap: 5px; }
    }
    """

    def decide(customer_behavior: str, min_margin: float, min_score: float) -> dict[str, Any]:
        if not customer_behavior.strip():
            return {"error": "고객 행동을 입력하세요."}
        try:
            if embedding_comparison_runner is not None:
                compared = embedding_comparison_runner(
                    customer_behavior, load_settings(), top_k=len(candidates),
                    min_margin=float(min_margin), min_score=float(min_score),
                )
                return {
                    **compared["reranker"],
                    "embedding": compared["embedding"],
                    "comparison_rows": compared["comparison_rows"],
                }
            return decision_runner(
                case_text=customer_behavior,
                settings=load_settings(),
                min_margin=float(min_margin),
                min_score=float(min_score),
            )
        except Exception as error:
            return {"error": f"{type(error).__name__}: {error}"}

    def render_outcome(outcome: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        if "error" in outcome:
            message = escape(str(outcome["error"]))
            return (
                (
                    '<section class="method-result-card"><p class="method-result-heading method-result-heading--reranker">Reranker 재정렬</p>'
                    '<p class="method-result-caption">후보 문서와 원문을 함께 읽은 관련도 순위</p>'
                    f'<section class="decision-result error"><p class="decision-result-kicker">호출 실패</p><h2 class="decision-result-title">추천을 생성하지 못했습니다</h2><p>{message}</p></section></section>'
                ),
                "",
                outcome,
            )

        ranked = list(outcome.get("ranked_candidates", []))
        top = ranked[0] if ranked else {}
        recommendation = str(outcome.get("recommendation", ""))
        requires_review = bool(outcome.get("requires_human_review"))
        theme = "review" if requires_review else recommendation
        if theme not in {"approve", "decline", "review"}:
            theme = "review"
        recommendation_label = escape(str(outcome.get("recommendation_label", recommendation)))
        review_label = "사람 검토 필요" if requires_review else "자동 추천 가능"
        try:
            top_score = float(top.get("score", 0))
            margin = float(outcome.get("margin", 0))
        except (TypeError, ValueError):
            top_score, margin = 0.0, 0.0
        reason = escape(str(outcome.get("reason", "판단 근거가 없습니다."))).replace("\n", "<br>")
        result_html = f"""
        <section class="analysis-result reranker-result">
          <h3>재정렬 결과</h3>
          <p><b>추천 정책: {recommendation_label}</b><span class="decision-badge {theme}">{review_label}</span><br>{reason}</p>
          <div class="decision-metrics">
            <div class="decision-metric"><span>최고 관련도 점수</span><strong>{top_score:.3f}</strong></div>
            <div class="decision-metric"><span>1·2위 점수 차이 (margin)</span><strong>{margin:.3f}</strong></div>
          </div>
        </section>
        """
        ranking_rows = []
        for item in ranked:
            try:
                score = float(item.get("score", 0))
            except (TypeError, ValueError):
                score = 0.0
            width = min(100, max(0, score * 100))
            rank = escape(str(item.get("rank", "-")))
            label = escape(str(item.get("label", item.get("id", "후보"))))
            ranking_rows.append(
                f'<div class="decision-rank-row"><span>{rank}</span><span class="decision-rank-label">{label}</span><span class="decision-progress"><span style="width: {width:.1f}%"></span></span><strong class="decision-rank-score">{score:.3f}</strong></div>'
            )
        ranking_html = "".join(ranking_rows)
        embedding = outcome.get("embedding")
        embedding_html = (
            '<section class="method-result-card"><p class="method-result-heading method-result-heading--embedding">Embedding 검색</p>'
            '<p class="method-result-caption">각 정책 원형과의 벡터 유사도 순위</p>'
            '<section class="decision-result-empty">실행하면 검색 순위와 유사도 점수를 표시합니다.</section></section>'
        )
        if isinstance(embedding, dict):
            embedding_ranked = list(embedding.get("ranked_candidates", []))
            try:
                embedding_top_score = float(embedding_ranked[0].get("score", 0)) if embedding_ranked else 0.0
            except (AttributeError, TypeError, ValueError):
                embedding_top_score = 0.0
            rows = []
            for item in embedding_ranked:
                try:
                    score = float(item.get("score", 0))
                except (TypeError, ValueError):
                    score = 0.0
                rows.append(
                    f'<div class="embedding-rank-row"><span>{escape(str(item.get("rank", "-")))}</span>'
                    f'<span class="decision-rank-label">{escape(str(item.get("label", item.get("id", "후보"))))}</span>'
                    f'<span class="embedding-progress"><span style="width: {min(100, max(0, score * 100)):.1f}%"></span></span>'
                    f'<strong class="decision-rank-score">{score:.3f}</strong></div>'
                )
            embedding_html = (
                '<section class="method-result-card"><p class="method-result-heading method-result-heading--embedding">Embedding 검색</p>'
                '<p class="method-result-caption">각 정책 원형과의 벡터 유사도 순위</p>'
                '<section class="analysis-result"><h3>검색 결과</h3>'
                '<p>정책 원형을 각각 벡터화해 유사도로 순위를 정합니다. 이 순위는 Reranker 관련도 점수와 절대값을 비교하지 않습니다.</p>'
                '<div class="decision-metrics">'
                f'<div class="decision-metric"><span>최고 유사도 점수</span><strong>{embedding_top_score:.3f}</strong></div>'
                f'<div class="decision-metric"><span>비교한 정책 원형</span><strong>{len(embedding_ranked)}개</strong></div>'
                '</div>'
                + "".join(rows) + "</section></section>"
            )
        reranker_html = (
            '<section class="method-result-card"><p class="method-result-heading method-result-heading--reranker">Reranker 재정렬</p>'
            '<p class="method-result-caption">후보 문서와 원문을 함께 읽은 관련도 순위</p>'
            + result_html + ranking_html + "</section>"
        )
        return reranker_html, embedding_html, outcome

    def decide_and_render(
        customer_behavior: str, min_margin: float, min_score: float,
    ) -> tuple[str, str, dict[str, Any]]:
        return render_outcome(decide(customer_behavior, min_margin, min_score))

    with gr.Blocks(css=modal_css, fill_width=True, theme=_light_theme(gr)) as app:
        with gr.Row(equal_height=True):
            with gr.Column(scale=9):
                gr.Markdown(
                    "# Reranker Decision Playground\n"
                    "사례와 정책 후보를 비교해 추천을 만듭니다. 실제 업무 상태는 변경하지 않습니다."
                )
            with gr.Column(scale=1, min_width=90):
                open_settings = gr.Button("⚙️ 설정", size="sm")
        with gr.Row(equal_height=False, elem_id="decision-main-row"):
            with gr.Column(scale=5, min_width=320, elem_classes=["decision-panel"]):
                gr.Markdown("### ① 고객 행동\n주문 흐름과 인증·결제·한도 관련 사실을 입력하세요.")
                customer_behavior = gr.Textbox(
                    label="고객 행동",
                    value=default_behavior,
                    lines=7,
                    placeholder="예: 1분 동안 3회 주문을 시도했고, 인증 실패는 없었습니다.",
                )
                run = gr.Button("추천 생성", variant="primary")
                with gr.Accordion(f"예시 시나리오 ({len(example_scenarios)}개)", open=False, elem_id="decision-example-card"):
                    gr.Markdown("예시를 선택하면 고객 행동 입력란에 적용됩니다.")
                    for row_start in range(0, len(example_scenarios), 2):
                        with gr.Row():
                            for label, scenario in example_scenarios[row_start:row_start + 2]:
                                example = gr.Button(
                                    label,
                                    variant="secondary",
                                    size="sm",
                                    elem_classes=["decision-example-button"],
                                )
                                example.click(
                                    lambda value=scenario: value,
                                    outputs=customer_behavior,
                                )
                with gr.Accordion("정책 후보 보기", open=False):
                    gr.Markdown(candidate_summary)
            with gr.Column(scale=7, min_width=380, elem_classes=["decision-panel"]):
                gr.Markdown("### ② 분석 결과")
                with gr.Row(equal_height=True, elem_id="method-results-row"):
                    with gr.Column(scale=1, elem_classes=["method-result-panel", "method-result-panel--embedding"]):
                        embedding_overview = gr.HTML(
                            value=(
                                '<section class="method-result-card"><p class="method-result-heading method-result-heading--embedding">Embedding 검색</p>'
                                '<p class="method-result-caption">각 정책 원형과의 벡터 유사도 순위</p>'
                                '<section class="decision-result-empty">실행하면 검색 순위와 유사도 점수를 표시합니다.</section></section>'
                            ),
                        )
                    with gr.Column(scale=1, elem_classes=["method-result-panel", "method-result-panel--reranker"]):
                        result_overview = gr.HTML(
                            value=(
                                '<section class="method-result-card"><p class="method-result-heading method-result-heading--reranker">Reranker 재정렬</p>'
                                '<p class="method-result-caption">후보 문서와 원문을 함께 읽은 관련도 순위</p>'
                                '<section class="decision-result-empty">실행하면 추천·관련도 점수·순위를 표시합니다.</section></section>'
                            ),
                        )
                with gr.Accordion("상세 응답 (JSON)", open=False):
                    output = gr.JSON(label="원본 응답", min_height=220)
        with gr.Column(visible=False, elem_id="decision-settings-modal") as settings_modal:
            gr.Markdown("### Reranker 설정")
            gr.Markdown("### 사람 검토 게이트")
            with gr.Row():
                min_margin = gr.Slider(
                    minimum=0,
                    maximum=1,
                    value=default_min_margin,
                    step=0.005,
                    label="최소 margin",
                    info="1·2위 score 차이가 이 값보다 작으면 manual-review입니다.",
                )
                min_score = gr.Slider(
                    minimum=0,
                    maximum=1,
                    value=default_min_score,
                    step=0.01,
                    label="최소 score",
                    info="최고 score가 이 값보다 작으면 manual-review입니다.",
                )
            close_settings = gr.Button("닫기")
        open_settings.click(lambda: gr.update(visible=True), outputs=settings_modal)
        close_settings.click(lambda: gr.update(visible=False), outputs=settings_modal)
        run.click(
            decide_and_render,
            inputs=[customer_behavior, min_margin, min_score],
            outputs=[result_overview, embedding_overview, output],
        )
    return app
