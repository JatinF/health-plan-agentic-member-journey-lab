"""Optional wording pass. The default path returns the computed template unchanged.

A model call runs only when MEMBERCARE_NARRATION=llm and XAI_API_KEY are both set.
The call uses the xAI Responses API with store disabled. Dollar amounts in the
model text must be the same set as the template, or the template is kept.
"""

from __future__ import annotations

import os

import httpx

from membercare.explain import dollars_in_text

_SYSTEM = (
    "Rewrite the member explanation for clarity. Keep every dollar amount and every "
    "source citation exactly as written. Do not add dollar amounts, visit counts, "
    "provider names, or clinical advice. If you cannot comply, return the text unchanged."
)


def narrate(template: str, allowed: set[int]) -> tuple[str, str]:
    del allowed  # the allowed set is the dollar amounts already present in the template
    if os.environ.get("MEMBERCARE_NARRATION") != "llm" or not os.environ.get("XAI_API_KEY"):
        return template, "template"
    try:
        text = rewrite(template, os.environ["XAI_API_KEY"])
    except Exception:
        return template, "template_after_error"
    if set(dollars_in_text(text)) != set(dollars_in_text(template)):
        return template, "template_after_guard"
    return text, "llm"


def rewrite(template: str, api_key: str) -> str:
    payload = {
        "model": os.environ.get("MEMBERCARE_XAI_MODEL", "grok-4.7"),
        "store": False,
        "input": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": template},
        ],
    }
    with httpx.Client(timeout=60) as client:
        response = client.post(
            "https://api.x.ai/v1/responses",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        body = response.json()
    parts: list[str] = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") == "output_text" and block.get("text"):
                parts.append(block["text"])
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("model response did not include output text")
    return text
