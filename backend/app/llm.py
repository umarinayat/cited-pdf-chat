"""One small interface over three providers: generate_json(system, user) -> dict.

Gemini is the default. Claude and OpenAI are drop-in alternatives (set LLM_PROVIDER).
With no key configured the app runs in extractive mode and never calls a model.
"""

from __future__ import annotations

import json
import time
import re

from . import config


class LLMError(RuntimeError):
    pass


def active() -> tuple[str, str] | None:
    """(provider, model) when a usable key is configured, else None."""
    p = config.LLM_PROVIDER
    if p == "gemini" and config.GEMINI_API_KEY:
        return "gemini", config.GEMINI_MODEL
    if p == "anthropic" and config.ANTHROPIC_API_KEY:
        return "anthropic", config.ANTHROPIC_MODEL
    if p == "openai" and config.OPENAI_API_KEY:
        return "openai", config.OPENAI_MODEL
    return None


_clients: dict[str, object] = {}


def _client(provider: str):
    if provider not in _clients:
        if provider == "gemini":
            from google import genai
            from google.genai import types

            _clients[provider] = genai.Client(
                api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=config.LLM_TIMEOUT_S * 1000))
        elif provider == "anthropic":
            import anthropic

            _clients[provider] = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        else:
            import openai

            _clients[provider] = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    return _clients[provider]


def _parse(text: str) -> dict:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace = re.search(r"\{.*\}", text, re.S)
        if brace:
            return json.loads(brace.group(0))
        raise


_TRANSIENT = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "timed out", "Timeout", "deadline")


def generate_json(system: str, user: str, schema: dict) -> dict:
    """Call the active provider and return (answer JSON, model used). Busy or rate-limited models
    are retried once, then the next model in the fallback chain is tried."""
    act = active()
    if act is None:
        raise LLMError("no LLM key configured")
    provider, model = act
    chain = [model] + (config.GEMINI_FALLBACK_MODELS if provider == "gemini" else [])
    last: Exception | None = None
    for m in chain:
        for attempt in range(2):
            try:
                out = _call(provider, m, system, user, schema)
                out["_model"] = m
                return out
            except LLMError as e:
                last = e
                if not any(t in str(e) for t in _TRANSIENT):
                    raise
                time.sleep(1.5 * (attempt + 1))
    raise last or LLMError("all models failed")


def _call(provider: str, model: str, system: str, user: str, schema: dict) -> dict:
    try:
        if provider == "gemini":
            from google.genai import types

            resp = _client("gemini").models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,  # default temperature: newer Gemini models degrade below it
                    response_mime_type="application/json",
                    response_json_schema=schema,
                ),
            )
            return _parse(resp.text)
        if provider == "anthropic":
            resp = _client("anthropic").messages.create(
                model=model,
                max_tokens=2000,
                temperature=0.0,
                system=system + "\n\nReply with a single JSON object that matches this schema, and nothing else:\n"
                + json.dumps(schema),
                messages=[{"role": "user", "content": user}],
            )
            return _parse("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
        resp = _client("openai").chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
        )
        return _parse(resp.choices[0].message.content)
    except LLMError:
        raise
    except Exception as e:  # network, quota, bad model name, unparsable output
        raise LLMError(f"{provider} call failed: {type(e).__name__}: {str(e)[:300]}") from e
