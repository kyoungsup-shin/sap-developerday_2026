"""Gradio views specific to the Gen AI Hub LLM notebooks.

The functions create UI blocks but never launch a public share link.  A notebook
explicitly calls ``launch(inline=True)`` when the learner is ready.
"""
from __future__ import annotations

import os
from html import escape
from collections.abc import Iterator
from typing import Any, Callable

from .lab_core import (
    REACT_SYSTEM_INSTRUCTION,
)
from .prompts import CHAT_SYSTEM_PROMPT
from .lesson_support.config import load_settings


MODE_SYSTEM_PROMPTS = {
    "chat": CHAT_SYSTEM_PROMPT,
    "react": REACT_SYSTEM_INSTRUCTION,
}


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


def build_chat_ui(
    chat_runner: Callable[..., dict[str, str]],
    chat_stream_runner: Callable[..., Iterator[str]] | None = None,
    react_agent_runner: Callable[..., dict[str, Any]] | None = None,
):
    """Create a chat UI that can also run the bounded ReAct exercise."""
    gr = _gradio()

    def render_react_step(index: int, step: dict[str, Any]) -> str:
        plan = step.get("plan")
        if isinstance(plan, dict):
            subtasks = [
                str(task.get("goal") or task.get("id") or "작업")
                for task in plan.get("subtasks", [])
                if isinstance(task, dict)
            ]
            summary = ", ".join(subtasks) or "질문을 분석해 필요한 작업을 정했습니다."
            entries = [
                ("Plan", summary),
                ("Observation · &lt;observation&gt;", "작업 계획을 만들었습니다."),
            ]
        else:
            entries: list[tuple[str, str]] = []
            if thinking := str(step.get("thinking", "")).strip():
                entries.append(("Thought · &lt;thinking&gt;", thinking))
            if action := str(step.get("action", "")).strip():
                entries.append(("Action · &lt;action&gt;", action))
            if observation := str(step.get("observation", "")).strip():
                entries.append(("Observation · &lt;observation&gt;", observation))
            if evaluation := str(step.get("evaluation", "")).strip():
                entries.append(("Evaluation · &lt;evaluation&gt;", evaluation))
            if answer := str(step.get("answer", "")).strip():
                entries.append(("Final Answer · &lt;answer&gt;", answer))
            if not entries:
                entries.append(("실행 상태", "표시할 ReAct 실행 기록이 반환되지 않았습니다."))

        return "".join(
            '<li class="react-timeline__step react-timeline__step--completed">'
            '<span class="react-timeline__marker" aria-hidden="true"></span>'
            '<div class="react-timeline__content">'
            f'<div class="react-timeline__title">Step {index} · {label}</div>'
            f'<p>{escape(value).replace(chr(10), "<br>")}</p>'
            "</div></li>"
            for label, value in entries
        )

    def render_react_timeline(steps: list[Any]) -> str:
        trace = "".join(
            render_react_step(index, step)
            for index, step in enumerate(steps, start=1)
            if isinstance(step, dict)
        )
        return (
            '<section class="react-timeline" aria-label="ReAct Agent 실행 과정">'
            '<h3>ReAct Agent 실행 과정</h3>'
            '<p class="react-timeline__intro">공개 태그와 도구 호출을 실행 순서대로 표시합니다.</p>'
            f"<ol>{trace or '<li>수행한 작업이 없습니다.</li>'}</ol></section>"
        )

    def render_chat_view(history: list[dict[str, str]]) -> str:
        items: list[str] = []
        for item in history:
            role = item.get("role")
            content = str(item.get("content", ""))
            if role == "timeline":
                items.append(f'<div class="chat-feed__timeline">{content}</div>')
                continue
            if role not in {"user", "assistant"}:
                continue
            role_class = "chat-feed__message--user" if role == "user" else "chat-feed__message--assistant"
            items.append(
                f'<div class="chat-feed__message {role_class}">'
                f'<div class="chat-feed__bubble">{escape(content).replace(chr(10), "<br>")}</div></div>'
            )
        empty = "<p class=\"chat-feed__empty\">질문을 입력해 대화를 시작하세요.</p>"
        return f'<section class="chat-feed">{"".join(items) or empty}</section>'

    def reply(
        message: str, history: list[Any], chat_config: dict[str, str],
    ) -> Iterator[tuple[str, list[dict[str, str]], Any]]:
        visible_history = [
            {"role": item["role"], "content": str(item.get("content", ""))}
            for item in history or []
            if isinstance(item, dict) and item.get("role") in {"user", "assistant", "timeline"}
        ]
        if not message.strip():
            updated = [*visible_history, {"role": "assistant", "content": "질문을 입력하세요."}]
            yield "", updated, render_chat_view(updated)
            return
        next_history = [*visible_history, {"role": "user", "content": message}]
        settings = load_settings()
        selected_model = chat_config.get("model_name", "").strip() or settings.llm_model
        system_prompt = chat_config.get("system_prompt", "")
        try:
            if chat_config.get("mode") == "react":
                if react_agent_runner is None:
                    message = "ReAct 에이전트 실행기가 연결되지 않았습니다."
                    updated = [*next_history, {"role": "assistant", "content": message}]
                    yield "", updated, render_chat_view(updated)
                    return
                outcome = react_agent_runner(
                    message=message,
                    settings=settings,
                    history=_history_messages(history),
                    system_prompt=system_prompt,
                    model=selected_model,
                )
                steps = outcome.get("trace", [])
                timeline = render_react_timeline(steps)
                timeline_history = [*next_history, {"role": "timeline", "content": timeline}]
                yield "", timeline_history, render_chat_view(timeline_history)
                updated = [
                    *timeline_history,
                    {"role": "assistant", "content": str(outcome["reply"])},
                ]
                yield "", updated, render_chat_view(updated)
                return
            if chat_stream_runner is not None:
                accumulated = ""
                yield "", next_history, render_chat_view(next_history)
                for delta in chat_stream_runner(
                    message=message,
                    settings=settings,
                    history=_history_messages(history),
                    system_prompt=system_prompt,
                    model=selected_model,
                ):
                    accumulated += delta
                    yield "", [
                        *next_history,
                        {"role": "assistant", "content": accumulated},
                    ], render_chat_view([
                        *next_history,
                        {"role": "assistant", "content": accumulated},
                    ])
                return
            outcome = chat_runner(
                message=message,
                settings=settings,
                history=_history_messages(history),
                system_prompt=system_prompt,
                model=selected_model,
            )
            yield "", [
                *next_history,
                {"role": "assistant", "content": str(outcome["reply"])},
            ], render_chat_view([
                *next_history,
                {"role": "assistant", "content": str(outcome["reply"])},
            ])
        except Exception as error:
            yield "", [
                *next_history,
                {"role": "assistant", "content": f"호출 실패: {type(error).__name__}: {error}"},
            ], render_chat_view([
                *next_history,
                {"role": "assistant", "content": f"호출 실패: {type(error).__name__}: {error}"},
            ])

    settings = load_settings()
    modal_css = """
    #chat-settings-modal {
      position: fixed !important; top: 50% !important; left: 50% !important; right: auto !important; bottom: auto !important;
      transform: translate(-50%, -50%) !important; z-index: 1000 !important;
      width: min(760px, calc(100vw - 32px)) !important; max-width: none !important;
      max-height: calc(100vh - 48px) !important; box-sizing: border-box !important;
      padding: 20px !important; border: 1px solid #d0d7de !important;
      border-radius: 14px !important; background: white !important; box-shadow: 0 18px 60px rgba(0,0,0,.22) !important;
      overflow-y: auto !important;
    }
    #chat-settings-modal > .form,
    #chat-settings-modal .form {
      display: flex !important; flex-direction: column !important; flex-wrap: nowrap !important;
      align-items: stretch !important;
    }
    #chat-settings-modal .block {
      width: 100% !important; min-width: 0 !important;
    }
    #chat-settings-modal textarea {
      max-height: 34vh !important;
    }
    .chat-feed{height:420px;overflow-y:auto;padding:16px;border:1px solid #d7e3eb;border-radius:12px;background:#edf2f6}
    .chat-feed__empty{margin:0;color:#617586;font-size:13px}.chat-feed__message{display:flex;margin:0 0 12px}.chat-feed__message--user{justify-content:flex-end}.chat-feed__bubble{max-width:min(75%,680px);padding:10px 12px;border:1px solid #d7e0e8;border-radius:4px 13px 13px 13px;background:#fff;color:#25313d;font-size:13px;line-height:1.5;box-shadow:0 1px 2px rgba(40,58,74,.08)}
    .chat-feed__message--user .chat-feed__bubble{border-color:#d4cde3;border-radius:13px 4px 13px 13px;background:#f6f2ff}.chat-feed__timeline{margin:0 0 12px}
    .react-timeline{margin:0;padding:12px 14px;border:1px solid #d7e3eb;border-radius:12px;background:#f8fbff}
    .react-timeline h3{margin:0;color:#314b64;font-size:15px}.react-timeline__intro{margin:4px 0 10px;color:#617586;font-size:12px}
    .react-timeline ol{display:grid;gap:5px;margin:0;padding:0;list-style:none}.react-timeline__step{position:relative;padding:0 0 0 26px}
    .react-timeline__step:not(:last-child)::after{position:absolute;top:18px;bottom:-7px;left:8px;width:2px;background:#d6e2e9;content:""}
    .react-timeline__marker{position:absolute;z-index:1;top:8px;left:3px;width:14px;height:14px;border:3px solid #2f9368;border-radius:50%;background:#2f9368;box-shadow:0 0 0 3px #f8fbff}
    .react-timeline__marker::after{display:block;color:#fff;content:"✓";font-size:10px;font-weight:900;line-height:14px;text-align:center}
    .react-timeline__content{min-height:0;padding:7px 10px;border:1px solid #d7e3eb;border-radius:8px;background:#fff;box-shadow:0 1px 2px rgba(48,73,94,.05)}
    .react-timeline__title{color:#314b64;font-size:12px;font-weight:800}.react-timeline__content p{margin:3px 0 0;color:#25313d;font-size:12px;line-height:1.4;overflow-wrap:anywhere}
    """
    with gr.Blocks(css=modal_css, fill_width=True, theme=_light_theme(gr)) as app:
        gr.Markdown(
            "# LLM Chatbot UI\n"
            "대화 내용은 현재 Jupyter session의 브라우저 UI에만 유지됩니다. prompt, 모델, 실행 방식은 ⚙️ 설정에서 바꿀 수 있습니다."
        )
        chat_config = gr.State({
            "system_prompt": MODE_SYSTEM_PROMPTS["chat"],
            "model_name": settings.llm_model,
            "mode": "chat",
        })
        with gr.Row():
            gr.Markdown("질문을 입력해 대화를 시작하세요.")
            open_settings = gr.Button("⚙️ 설정", size="sm")
        chat_history = gr.State([])
        chat_view = gr.HTML(render_chat_view([]))
        with gr.Row(equal_height=True):
            textbox = gr.Textbox(
                placeholder="메시지를 입력하세요…", show_label=False, scale=8,
            )
            send = gr.Button("보내기", variant="primary", scale=1)
        clear = gr.Button("대화 지우기", size="sm")
        with gr.Column(visible=False, elem_id="chat-settings-modal") as settings_modal:
            gr.Markdown("### 채팅 설정")
            system_prompt = gr.Textbox(
                label="System prompt",
                value=MODE_SYSTEM_PROMPTS["chat"],
                lines=8,
            )
            model_name = gr.Textbox(label="Model (blank uses LLM_MODEL)", value=settings.llm_model)
            mode = gr.Radio(
                label="실행 방식",
                choices=[
                    ("일반 Chat", "chat"),
                    ("ReAct Agent (계산 도구)", "react"),
                ],
                value="chat",
                info="ReAct Agent는 계산 도구를 사용합니다.",
            )
            with gr.Row():
                save_settings_button = gr.Button("적용", variant="primary")
                close_settings = gr.Button("닫기")

        open_settings.click(lambda: gr.update(visible=True), outputs=settings_modal)
        close_settings.click(lambda: gr.update(visible=False), outputs=settings_modal)
        mode.change(
            lambda selected_mode: gr.update(
                value=MODE_SYSTEM_PROMPTS.get(selected_mode, MODE_SYSTEM_PROMPTS["chat"]),
            ),
            inputs=mode,
            outputs=system_prompt,
        )
        save_settings_button.click(
            lambda prompt, model, selected_mode: (
                {"system_prompt": prompt, "model_name": model, "mode": selected_mode},
                gr.update(visible=False),
            ),
            inputs=[system_prompt, model_name, mode],
            outputs=[chat_config, settings_modal],
        )
        chat_inputs = [textbox, chat_history, chat_config]
        chat_outputs = [textbox, chat_history, chat_view]
        textbox.submit(reply, inputs=chat_inputs, outputs=chat_outputs)
        send.click(reply, inputs=chat_inputs, outputs=chat_outputs)
        clear.click(
            lambda: ("", [], render_chat_view([])),
            outputs=chat_outputs,
        )
    return app

