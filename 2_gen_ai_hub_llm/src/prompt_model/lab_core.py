"""Core workflow for 01_prompt_and_model.ipynb."""

from __future__ import annotations

import ast
import json
import operator
import re
from collections.abc import Iterator
from typing import Any, Callable, Sequence

from .lesson_support.llm import chat_text, chat_text_stream, chat_tool_completion
from .lesson_support.config import Settings
from .prompts import (
    DEFAULT_COMPARISON_SYSTEM_PROMPT,
    REACT_SYSTEM_INSTRUCTION,
)

MAX_CHAT_HISTORY_MESSAGES = 12
MAX_CHAT_HISTORY_CHARACTERS = 12_000
MAX_REACT_TOOL_TURNS = 3
CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "사칙연산과 괄호가 있는 수식을 정확히 계산합니다.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
}
def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _response_message(response: Any) -> Any:
    choices = _field(response, "choices", [])
    if not choices:
        raise RuntimeError("ReAct 에이전트 응답에 choice가 없습니다.")
    return _field(choices[0], "message")


def _public_reasoning_and_answer(content: str) -> tuple[str, str, str]:
    """Read the concise, model-authored public reasoning from a ReAct turn."""
    thinking = re.search(r"<thinking>\s*(.*?)\s*</thinking>", content, flags=re.DOTALL)
    answer = re.search(r"<answer>\s*(.*?)\s*</answer>", content, flags=re.DOTALL)
    evaluation = re.search(r"<evaluation>\s*(.*?)\s*</evaluation>", content, flags=re.DOTALL)
    public_reasoning = thinking.group(1).strip() if thinking else ""
    final_answer = answer.group(1).strip() if answer else content.strip()
    if not answer:
        final_answer = re.sub(
            r"<(?:thinking|evaluation)>.*?</(?:thinking|evaluation)>",
            "",
            content,
            flags=re.DOTALL,
        ).strip()
    return public_reasoning, final_answer, evaluation.group(1).strip() if evaluation else ""


def _structured_react_reply(thinking: str, answer: str, evaluation: str) -> str:
    """Build a parser-friendly, public summary of a completed ReAct turn."""
    parts = [
        f"<thinking>{thinking.strip()}</thinking>",
        f"<answer>{answer.strip()}</answer>",
    ]
    if evaluation.strip():
        parts.append(f"<evaluation>{evaluation.strip()}</evaluation>")
    return "\n".join(parts)


def _calculator(expression: str) -> float | int:
    """Evaluate a deliberately small arithmetic grammar without eval()."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 200:
        raise ValueError("계산식은 1~200자 문자열이어야 합니다.")
    operators = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    def evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError("허용되지 않은 계산식입니다. 숫자, 괄호, + - * / // % ** 만 사용하세요.")

    return evaluate(ast.parse(expression, mode="eval").body)


def compare_prompts(
    question: str,
    settings: Settings,
    chat_caller: Callable[
        [Settings, list[dict[str, str]], str | None], str
    ] = chat_text,
    system_prompt: str = DEFAULT_COMPARISON_SYSTEM_PROMPT,
) -> dict[str, str]:
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("질문을 입력하세요.")
    constrained_system_prompt = system_prompt.strip()
    if not constrained_system_prompt:
        raise ValueError("비교할 system prompt를 입력하세요.")
    baseline = chat_caller(settings, [{"role": "user", "content": cleaned}], None)
    constrained = chat_caller(
        settings,
        [
            {
                "role": "system",
                "content": constrained_system_prompt,
            },
            {"role": "user", "content": cleaned},
        ],
        None,
    )
    return {"question": cleaned, "baseline": baseline, "constrained": constrained}


def _chat_messages(
    message: str, history: Sequence[dict[str, str]] = (), system_prompt: str = ""
) -> tuple[str, list[dict[str, str]]]:
    cleaned = message.strip()
    if not cleaned:
        raise ValueError("질문을 입력하세요.")
    normalized: list[dict[str, str]] = []
    for item in history:
        role, content = item.get("role"), str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            raise ValueError(
                "대화 history에는 내용이 있는 user 또는 assistant 메시지만 넣을 수 있습니다."
            )
        normalized.append({"role": role, "content": content})
    retained: list[dict[str, str]] = []
    remaining = MAX_CHAT_HISTORY_CHARACTERS
    for item in reversed(normalized[-MAX_CHAT_HISTORY_MESSAGES:]):
        if len(item["content"]) <= remaining:
            retained.append(item)
            remaining -= len(item["content"])
    messages = (
        [{"role": "system", "content": system_prompt.strip()}]
        if system_prompt.strip()
        else []
    )
    messages.extend(reversed(retained))
    messages.append({"role": "user", "content": cleaned})
    return cleaned, messages


def run_chat(
    message: str,
    settings: Settings,
    history: Sequence[dict[str, str]] = (),
    system_prompt: str = "",
    model: str | None = None,
    chat_caller: Callable[
        [Settings, list[dict[str, str]], str | None], str
    ] = chat_text,
) -> dict[str, str]:
    cleaned, messages = _chat_messages(message, history, system_prompt)
    selected_model = model.strip() if model and model.strip() else settings.llm_model
    return {
        "message": cleaned,
        "model": selected_model,
        "reply": chat_caller(settings, messages, selected_model),
    }


def run_chat_stream(
    message: str,
    settings: Settings,
    history: Sequence[dict[str, str]] = (),
    system_prompt: str = "",
    model: str | None = None,
    chat_stream_caller: Callable[
        [Settings, list[dict[str, str]], str | None], Iterator[str]
    ] = chat_text_stream,
) -> Iterator[str]:
    _, messages = _chat_messages(message, history, system_prompt)
    selected_model = model.strip() if model and model.strip() else settings.llm_model
    yield from chat_stream_caller(settings, messages, selected_model)


def run_react_agent(
    message: str,
    settings: Settings,
    history: Sequence[dict[str, str]] = (),
    system_prompt: str = "",
    model: str | None = None,
    agent_caller: Callable[..., Any] = chat_tool_completion,
    tool_runner: Callable[[str], float | int] = _calculator,
    _instruction: str = REACT_SYSTEM_INSTRUCTION,
    _max_tool_turns: int = MAX_REACT_TOOL_TURNS,
) -> dict[str, Any]:
    """Run a bounded ReAct loop with one local, read-only calculator tool.

    The returned observations are public UI evidence; private model reasoning is
    never collected or displayed.
    """
    supplied_system_prompt = system_prompt.strip()
    # The UI exposes the actual agent instruction for editing. Avoid sending it
    # twice, while callers that supply only an extra instruction still receive
    # the mandatory ReAct behavior.
    combined_system_prompt = supplied_system_prompt
    if _instruction and _instruction not in supplied_system_prompt:
        combined_system_prompt = "\n\n".join(
            part for part in (supplied_system_prompt, _instruction) if part
        )
    cleaned, messages = _chat_messages(message, history, combined_system_prompt)
    selected_model = model.strip() if model and model.strip() else settings.llm_model
    observations: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    for turn in range(_max_tool_turns + 1):
        response = agent_caller(
            settings,
            messages,
            [CALCULATOR_TOOL],
            selected_model,
            "none" if turn == _max_tool_turns else "auto",
        )
        assistant = _response_message(response)
        raw_calls = list(_field(assistant, "tool_calls", []) or [])
        content = str(_field(assistant, "content", "") or "")
        public_reasoning, final_answer, agent_evaluation = _public_reasoning_and_answer(content)
        if not raw_calls:
            final_reply = final_answer or "에이전트가 최종 답변을 반환하지 않았습니다."
            public_summary = public_reasoning or (
                "도구가 필요한 요청인지 확인했습니다. 현재 질문은 도구 없이 답할 수 있습니다."
                if not observations else "도구 관찰값을 바탕으로 사용자에게 전달할 답을 정리합니다."
            )
            evaluation_summary = agent_evaluation or (
                "질문에 필요한 도구가 없음을 확인하고 최종 답변을 생성했습니다."
                if not observations else "도구 실행 결과를 사용한 최종 응답 단계를 마쳤습니다."
            )
            if not observations:
                trace.append({
                    "thinking": public_summary,
                    "action": "도구 호출 없음",
                    "observation": "도구가 호출되지 않아 반환된 관찰값이 없습니다.",
                    "evaluation": evaluation_summary,
                    "answer": final_reply,
                })
            else:
                trace.append({
                    "thinking": public_summary,
                    "evaluation": evaluation_summary,
                    "answer": final_reply,
                })
            return {
                "message": cleaned,
                "model": selected_model,
                "reply": final_reply,
                "structured_reply": _structured_react_reply(
                    public_summary, final_reply, evaluation_summary,
                ),
                "tool_calls": observations,
                "trace": trace,
            }

        if turn == _max_tool_turns:
            raise RuntimeError(f"ReAct 도구 호출은 최대 {_max_tool_turns}회까지 허용됩니다.")

        assistant_calls: list[dict[str, Any]] = []
        tool_messages: list[dict[str, str]] = []
        for raw_call in raw_calls:
            function = _field(raw_call, "function")
            name = _field(function, "name")
            call_id = _field(raw_call, "id")
            raw_arguments = _field(function, "arguments", "{}")
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except json.JSONDecodeError as error:
                raise RuntimeError("도구 호출 arguments가 유효한 JSON이 아닙니다.") from error
            if not isinstance(name, str) or not isinstance(call_id, str) or not isinstance(arguments, dict):
                raise RuntimeError("도구 호출 형식이 올바르지 않습니다.")
            if name != "calculate":
                result: dict[str, Any] = {"error": f"허용되지 않은 도구입니다: {name}"}
            else:
                try:
                    result = {"expression": arguments.get("expression"), "value": tool_runner(arguments.get("expression"))}
                except (TypeError, ValueError, ZeroDivisionError, OverflowError) as error:
                    result = {"error": f"{type(error).__name__}: {error}"}
            observations.append({"name": name, "arguments": arguments, "result": result})
            succeeded = "error" not in result
            trace.append({
                "thinking": public_reasoning or (
                    "정확한 수치 계산이 필요해 계산 도구로 식을 확인합니다."
                    if name == "calculate"
                    else "요청을 처리하기 위해 선택한 도구를 실행합니다."
                ),
                "action": f"{name}({json.dumps(arguments, ensure_ascii=False)})",
                "observation": json.dumps(result, ensure_ascii=False),
                "evaluation": agent_evaluation or (
                    "도구 결과를 받았습니다. 이 관찰값을 다음 응답 생성에 사용합니다."
                    if succeeded
                    else "도구 실행에 실패했습니다. 오류를 반영해 다음 단계를 결정합니다."
                ),
            })
            assistant_calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            })
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        messages.extend([
            {"role": "assistant", "content": content, "tool_calls": assistant_calls},
            *tool_messages,
        ])

    raise RuntimeError("ReAct 에이전트가 종료되지 않았습니다.")
