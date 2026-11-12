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


def build_embedding_ui(comparison_cluster_runner: Callable[..., dict[str, Any]]):
    """Create a comparison UI with a session-local interactive cluster chart."""
    gr = _gradio()
    load_settings()
    configured_model = os.getenv("EMBED_MODEL", "amazon--titan-embed-image")

    def cluster_view(state: object) -> object:
        entries = state.get("entries", []) if isinstance(state, dict) else []
        if not entries:
            return None
        try:
            import plotly.graph_objects as go
        except ImportError as error:
            raise RuntimeError(
                "2D cluster 표시에 plotly가 필요합니다. requirements.txt를 다시 설치하세요."
            ) from error

        palette = ["#5B8FF9", "#61DDAA", "#F6BD16", "#7262FD", "#E8684A"]
        figure = go.Figure()
        for cluster_id in sorted({int(entry["cluster"]) for entry in entries}):
            members = [entry for entry in entries if int(entry["cluster"]) == cluster_id]
            figure.add_trace(
                go.Scatter(
                    x=[float(entry["x"]) for entry in members],
                    y=[float(entry["y"]) for entry in members],
                    mode="markers+text",
                    name=f"Cluster {cluster_id}",
                    text=[str(entry["text"]).replace("\n", " ")[:24] for entry in members],
                    textposition="top center",
                    textfont={"size": 11, "color": "#344054"},
                    customdata=[[int(entry["index"]), str(entry["text"])] for entry in members],
                    hovertemplate=(
                        "<b>%{customdata[1]}</b><br>Entry %{customdata[0]} · Cluster "
                        + str(cluster_id)
                        + "<br>UMAP 1 %{x:.3f}<br>UMAP 2 %{y:.3f}<extra></extra>"
                    ),
                    marker={
                        "size": 15, "color": palette[cluster_id % len(palette)],
                        "line": {"color": "#FFFFFF", "width": 2}, "opacity": 0.95,
                    },
                )
            )
        figure.update_layout(
            template="plotly_white", height=460,
            margin={"l": 50, "r": 30, "t": 64, "b": 48},
            paper_bgcolor="#FFFFFF", plot_bgcolor="#F8FAFC",
            title={
                "text": (
                    "Embedding space · fixed-reference UMAP"
                    if state.get("projection") == "reference_umap"
                    else "Embedding space · UMAP"
                ),
                "x": 0.02,
                "xanchor": "left",
            },
            font={"family": "Inter, Arial, sans-serif", "color": "#344054"},
            legend={"orientation": "h", "y": 1.05, "x": 1, "xanchor": "right"},
            hoverlabel={"bgcolor": "#101828", "font": {"color": "white"}},
        )

        def padded_range(values: list[float], padding_ratio: float = 0.45) -> list[float]:
            low, high = min(values), max(values)
            padding = max((high - low) * padding_ratio, 0.1)
            return [low - padding, high + padding]

        def autoscaled_range(axis: str, values: list[float]) -> list[float]:
            """Keep the reference map visible and zoom out for new outliers."""
            reference_range = (
                state.get("coordinate_range", {}).get(axis)
                if isinstance(state, dict)
                else None
            )
            if isinstance(reference_range, list) and len(reference_range) == 2:
                return padded_range(
                    [float(reference_range[0]), float(reference_range[1]), *values],
                    padding_ratio=0.22,
                )
            return padded_range(values)

        figure.update_xaxes(
            title="UMAP 1",
            range=autoscaled_range("x", [float(entry["x"]) for entry in entries]),
            zeroline=True,
            zerolinecolor="#D0D5DD",
            gridcolor="#EAECF0",
        )
        figure.update_yaxes(
            title="UMAP 2",
            range=autoscaled_range("y", [float(entry["y"]) for entry in entries]),
            zeroline=True,
            zerolinecolor="#D0D5DD",
            gridcolor="#EAECF0",
        )
        return figure

    def compare_and_add(text_a: str, text_b: str, state: object) -> tuple[dict[str, Any], object, object]:
        try:
            outcome = comparison_cluster_runner(
                text_a=text_a, text_b=text_b, state=state, settings=load_settings(), model=None,
                use_reference_umap=True,
            )
            cluster = outcome["cluster"]
            return outcome["comparison"], cluster, cluster_view(cluster)
        except Exception as error:
            return {"error": f"{type(error).__name__}: {error}"}, state, cluster_view(state)

    layout_css = """
    #embedding-comparison-row { flex-wrap: nowrap !important; gap: 16px !important; }
    #embedding-comparison-row > * { min-width: 0 !important; }
    """
    with gr.Blocks(css=layout_css, fill_width=True, theme=_light_theme(gr)) as app:
        gr.Markdown(f"Embedding model: `{configured_model}` (`.env`의 `EMBED_MODEL`)")
        with gr.Row(equal_height=True, elem_id="embedding-comparison-row"):
            with gr.Column(scale=1, min_width=0):
                first = gr.Textbox(label="Text A", value="apple")
                second = gr.Textbox(label="Text B", value="orange")
                run = gr.Button("Compare", variant="primary")
            with gr.Column(scale=1, min_width=0):
                output = gr.JSON(label="Result", min_height=260)
        cluster_state = gr.State(value=None)
        cluster_plot = gr.Plot(label=None, show_label=False)
        run.click(
            compare_and_add,
            inputs=[first, second, cluster_state],
            outputs=[output, cluster_state, cluster_plot],
        )
    return app


def build_business_embedding_ui(
    lab_runner: Callable[..., dict[str, Any]],
    cases: list[dict[str, str]],
    n_clusters: int = 4,
):
    """Create a progressive, read-only business-routing view."""
    gr = _gradio()
    load_settings()  # Loads the repository .env before reading EMBED_MODEL for the view.
    configured_model = os.getenv("EMBED_MODEL", "amazon--titan-embed-image")
    queue_names = {
        "logistics": "물류·배송 팀",
        "payment": "결제 팀",
        "compliance": "컴플라이언스 팀",
        "technical": "기술 지원 팀",
    }

    def queue_name(label: object) -> str:
        value = str(label)
        return queue_names.get(value, value.replace("_", " ").title() + " 팀")

    def render_result(outcome: dict[str, Any]) -> tuple[str, str, str, dict[str, Any], object]:
        """Translate numeric evidence into a clear routing decision."""
        if "error" in outcome:
            message = escape(str(outcome["error"]))
            return (
                '<div class="routing-decision routing-decision--review"><span class="decision-kicker">분석할 수 없습니다</span>'
                f"<h2>입력 또는 연결을 확인해주세요</h2><p>{message}</p></div>",
                "",
                "",
                outcome,
                gr.update(visible=True),
            )

        recommendation = outcome["recommendation"]
        similarities = list(recommendation["label_similarity"].items())
        top_score = float(similarities[0][1]) if similarities else 0.0
        margin = top_score - float(similarities[1][1]) if len(similarities) > 1 else top_score
        needs_review = top_score < 0.55 or margin < 0.18
        status = "사람 검토 권장" if needs_review else "전달 추천"
        status_class = "routing-decision--review" if needs_review else "routing-decision--ready"
        queue = queue_name(recommendation["recommended_queue"])
        second_queue = queue_name(similarities[1][0]) if len(similarities) > 1 else None
        if needs_review:
            reason = (
                f"{queue}이 가장 가깝지만, {second_queue}과도 의미가 겹칠 수 있습니다."
                if second_queue
                else "추천 근거가 충분하지 않아 사람이 내용을 확인해야 합니다."
            )
            next_step = "담당자가 문의 내용을 확인한 뒤 최종 팀을 선택하세요."
        else:
            reason = f"입력한 문의가 {queue} 사례와 가장 뚜렷하게 유사합니다."
            next_step = "운영 정책에 따라 해당 팀 전달 전 최종 내용을 확인하세요."
        summary = f"""
        <div class="routing-decision {status_class}">
          <span class="decision-kicker">{status}</span>
          <h2>{escape(queue)}으로 전달하세요</h2>
          <p class="decision-reason">{escape(reason)}</p>
          <div class="decision-next"><b>다음 단계</b><span>{escape(next_step)}</span></div>
        </div>
        """
        confidence = "높음" if top_score >= 0.75 else "보통" if top_score >= 0.55 else "낮음"
        separation = "뚜렷함" if margin >= 0.18 else "애매함"
        interpretation = f"""
        <div class="interpretation">
          <div><span>결과 점수</span><strong>{top_score:.3f}</strong></div>
          <div><span>2순위와 차이</span><strong>{margin:.3f}</strong></div>
          <div><span>추천 확신도</span><strong>{confidence}</strong></div>
          <div><span>후보 간 구분</span><strong>{separation}</strong></div>
        </div>
        """
        bars = []
        for label, score in similarities:
            value = float(score)
            width = max(0, min(100, value * 100))
            bars.append(
                f"<div class=\"similarity-row\"><span>{escape(queue_name(label))}</span>"
                f"<div class=\"similarity-track\"><i style=\"width:{width:.1f}%\"></i></div>"
                f"<b>{value:.3f}</b></div>"
            )
        similarity_view = "<div class=\"similarity-panel\"><h3>다른 가능성</h3>" + "".join(bars) + "</div>"
        return summary, interpretation, similarity_view, outcome, gr.update(visible=True)

    def recommend(ticket: str) -> tuple[str, str, str, dict[str, Any], object]:
        if not ticket.strip():
            return render_result({"error": "새 업무 문의를 입력하세요."})
        try:
            outcome = lab_runner(
                ticket=ticket,
                cases=cases,
                settings=load_settings(),
                n_clusters=n_clusters,
            )
            return render_result(outcome)
        except Exception as error:
            return render_result({"error": f"{type(error).__name__}: {error}"})

    layout_css = """
    .business-routing { max-width: 1180px; margin: 0 auto; color: #1f2937; }
    .routing-header { margin: 4px 0 24px; }
    .routing-header h1 { margin: 0 0 5px; font-size: 1.5rem; letter-spacing: -.035em; }
    .routing-header p { margin: 0; color: #6b7280; font-size: .94rem; }
    .routing-input { padding: 24px; border: 1px solid #e5e7eb; border-radius: 16px; background: #fff; box-shadow: 0 6px 24px rgba(31,41,55,.04); }
    .example-label { margin: 18px 0 8px; color: #6b7280; font-size: .82rem; font-weight: 650; }
    #example-row { gap: 8px !important; }
    #routing-actions { margin-top: 18px; align-items: center; }
    #routing-actions > *:first-child { flex-grow: 1 !important; }
    #routing-main-row { flex-wrap: nowrap !important; gap: 24px !important; align-items: flex-start !important; }
    #routing-main-row > * { min-width: 0 !important; }
    #routing-result { margin-top: 0; }
    .routing-decision { padding: 26px 28px; border: 1px solid; border-radius: 16px; }
    .routing-decision--ready { border-color: #b9d7ff; background: #f3f8ff; }
    .routing-decision--review { border-color: #f1ce91; background: #fff9ef; }
    .decision-kicker { display: block; margin-bottom: 8px; color: #8a5b0a; font-size: .78rem; font-weight: 750; letter-spacing: .06em; }
    .routing-decision--ready .decision-kicker { color: #2563b8; }
    .routing-decision h2 { margin: 0; font-size: 1.55rem; letter-spacing: -.03em; }
    .decision-reason { margin: 10px 0 22px; color: #4b5563; font-size: 1rem; line-height: 1.55; }
    .decision-next { display: flex; gap: 12px; padding-top: 16px; border-top: 1px solid rgba(99,102,110,.18); font-size: .9rem; }
    .decision-next b { white-space: nowrap; }
    .decision-next span { color: #596579; }
    .interpretation { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0 2px; }
    .interpretation div { padding: 13px 14px; border: 1px solid #e6eaf0; border-radius: 12px; background: #fff; }
    .interpretation span { display: block; margin-bottom: 3px; color: #697586; font-size: .78rem; }
    .interpretation strong { font-size: 1rem; }
    .similarity-panel { padding: 4px 2px 10px; }
    .similarity-panel h3 { margin: 0 0 12px; font-size: .95rem; }
    .similarity-row { display: grid; grid-template-columns: 116px 1fr 48px; align-items: center; gap: 10px; margin: 9px 0; font-size: .85rem; }
    .similarity-track { height: 8px; overflow: hidden; border-radius: 999px; background: #e7ecf3; }
    .similarity-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #4185e6, #6aa9ff); }
    .similarity-row b { color: #43516a; font-size: .8rem; text-align: right; }
    @media (max-width: 900px) {
      #routing-main-row { flex-wrap: wrap !important; }
      #routing-result { margin-top: 4px; }
      .routing-input { padding: 18px; }
      .routing-decision { padding: 20px; }
      .interpretation { grid-template-columns: repeat(2, 1fr); }
      .similarity-row { grid-template-columns: 95px 1fr 45px; gap: 7px; }
    }
    """
    with gr.Blocks(css=layout_css, fill_width=True, theme=_light_theme(gr)) as app:
        with gr.Column(elem_classes="business-routing"):
            gr.HTML(
                '<div class="routing-header"><h1>업무 문의 라우팅</h1>'
                '<p>문의 내용을 바탕으로 담당 팀을 추천합니다.</p></div>'
            )
            with gr.Row(elem_id="routing-main-row"):
                with gr.Column(scale=1, min_width=400, elem_classes="routing-input"):
                    ticket = gr.Textbox(
                        label="어떤 문의인가요?",
                        value="운송장에는 배송 완료로 나오지만 고객이 물건을 받지 못했습니다.",
                        lines=4,
                        placeholder="고객의 문제와 요청을 구체적으로 입력하세요.",
                    )
                    gr.HTML('<div class="example-label">예시로 시작하기</div>')
                    with gr.Row(elem_id="example-row"):
                        delivery_example = gr.Button("📦 배송 문제", size="sm")
                        payment_example = gr.Button("💳 결제 문제", size="sm")
                        security_example = gr.Button("🔒 계정·개인정보", size="sm")
                        technical_example = gr.Button("🛠 기술 지원", size="sm")
                    with gr.Row(elem_id="routing-actions"):
                        run = gr.Button("라우팅 분석하기 →", variant="primary")
                        reset = gr.Button("새 문의")
                with gr.Column(scale=1, min_width=400, visible=False, elem_id="routing-result") as result_area:
                    summary = gr.HTML()
                    interpretation = gr.HTML()
                    with gr.Accordion("추천 근거와 상세 분석 보기", open=False):
                        similarity = gr.HTML()
                        gr.Markdown(
                            f"모델: `{escape(configured_model)}` · 학습 사례: {len(cases)}건 · 탐색 cluster: {n_clusters}개"
                        )
                        detail = gr.JSON(label="원본 분석 결과", min_height=260)

        example_values = {
            delivery_example: "운송장에는 배송 완료로 나오지만 고객이 물건을 받지 못했습니다.",
            payment_example: "결제는 완료되었는데 주문이 생성되지 않았고 카드 청구만 확인됩니다.",
            security_example: "내 계정 정보가 동의 없이 변경된 것 같습니다. 접근 기록을 확인해주세요.",
            technical_example: "앱에서 로그인 후 화면이 계속 멈추고 오류 메시지가 표시됩니다.",
        }
        for button, example in example_values.items():
            button.click(lambda value=example: value, outputs=ticket)
        run.click(
            recommend,
            inputs=ticket,
            outputs=[summary, interpretation, similarity, detail, result_area],
        )
        reset.click(
            lambda: ("", "", "", "", {}, gr.update(visible=False)),
            outputs=[ticket, summary, interpretation, similarity, detail, result_area],
        )
    return app

