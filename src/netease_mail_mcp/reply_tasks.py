from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict


def load_extract_prompt() -> str:
    return (
        resources.files("netease_mail_mcp")
        .joinpath("prompts/extract_reply_tasks.md")
        .read_text(encoding="utf-8")
    )


def build_extract_reply_tasks_payload(
    thread_json: Dict[str, Any],
    output_language: str = "zh-CN",
) -> Dict[str, Any]:
    """MCP 内部不接 LLM，只返回固定 prompt 和结构化输出约束。"""
    prompt = load_extract_prompt()
    summary = {
        "thread_id": thread_json.get("thread_id"),
        "root_subject": thread_json.get("root_subject"),
        "message_count": thread_json.get("message_count"),
        "participants": thread_json.get("participants", []),
        "warnings": thread_json.get("warnings", []),
    }
    return {
        "output_language": output_language,
        "thread_summary": summary,
        "analysis_prompt": prompt.replace(
            "{{ thread_json }}",
            json.dumps(thread_json, ensure_ascii=False, indent=2),
        ),
        "recommended_next_step": "请把 analysis_prompt 交给当前 Codex 会话分析；MCP Server 第一版不接入外部 LLM API。",
        "expected_output_sections": [
            "需要我回复的事项",
            "仅需内部处理的事项",
            "已经被别人回复或解决的事项",
            "可能遗漏或需要人工确认的事项",
            "最终回复清单",
        ],
    }
