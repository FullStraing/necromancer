"""Model clients.

SubQ Snap (decision model, never generates text): scores hypotheses and picks experiments over the FULL
evidence dump in its long context.  Meta Muse Spark (generative): proposes hypotheses / experiments and
writes the replacement server.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError

from .evidence import ROOT

load_dotenv(ROOT / ".env")


class ModelUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------- SubQ
class NoulQ(BaseModel):
    instructions: str = Field(min_length=3, max_length=2000)
    true: str
    false: str

    def wire(self) -> dict:
        return {"type": "noul", "instructions": self.instructions, "criteria": {"true": self.true, "false": self.false}}


class ChoiceQ(BaseModel):
    instructions: str = Field(min_length=3, max_length=2000)
    options: dict[str, str | None] = Field(min_length=2, max_length=32)

    def wire(self) -> dict:
        return {"type": "choice", "instructions": self.instructions, "criteria": self.options}


@dataclass(frozen=True)
class SubQAnswer:
    kind: str
    noul: float | None = None
    choice: str | None = None
    probabilities: dict | None = None
    confidence: float | None = None


class SubQ:
    MAX_QUESTIONS = 128

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("SUBQ_API_KEY", "")
        self.model = model or os.getenv("SUBQ_MODEL", "subq-snap-1.1")
        self.base_url = (base_url or os.getenv("SUBQ_BASE_URL", "https://api.subq.ai/v1")).rstrip("/")
        self.input_tokens = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def ask(self, state: str, questions: dict[str, NoulQ | ChoiceQ], retries: int = 3) -> dict[str, SubQAnswer]:
        if not self.available:
            raise ModelUnavailable("SUBQ_API_KEY not configured")
        out: dict[str, SubQAnswer] = {}
        items = list(questions.items())
        for i in range(0, len(items), self.MAX_QUESTIONS):
            chunk = dict(items[i:i + self.MAX_QUESTIONS])
            out = {**out, **await self._call(state, chunk, retries)}
        return out

    async def _call(self, state: str, questions: dict, retries: int) -> dict[str, SubQAnswer]:
        body = {"model": self.model, "state": state, "questions": {k: q.wire() for k, q in questions.items()}}
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(retries):
                try:
                    r = await client.post(f"{self.base_url}/systemone", json=body,
                                          headers={"Authorization": f"Bearer {self.api_key}"})
                    if r.status_code in (429, 500, 502, 503, 504):
                        raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                    if r.status_code >= 400:
                        detail = r.json().get("detail", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
                        raise ModelUnavailable(f"SubQ {r.status_code}: {detail.get('message', r.text[:200])}")
                    data = r.json()
                    self.input_tokens += data.get("usage", {}).get("input_tokens", 0)
                    return {k: _parse_answer(v) for k, v in data["answers"].items()}
                except (httpx.TransportError, httpx.HTTPStatusError) as e:
                    last = e
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise ModelUnavailable(f"SubQ unreachable after {retries} attempts: {last}")


def _parse_answer(raw: dict) -> SubQAnswer:
    return SubQAnswer(kind=raw.get("type", ""), noul=raw.get("noul"), choice=raw.get("choice"),
                      probabilities=raw.get("probabilities"), confidence=raw.get("confidence"))


# ---------------------------------------------------------------- Generative model (Meta Muse Spark, or ASI1)
PROVIDERS = (
    # (provider, key env, base-url env, default base url, model env, default model)
    ("meta", "MODEL_API_KEY", "META_BASE_URL", "https://api.meta.ai/v1", "META_MODEL", "muse-spark-1.3"),
    ("asi1", "ASI1_API_KEY", "ASI1_BASE_URL", "https://api.asi1.ai/v1", "ASI1_MODEL", "asi1"),
)


class Meta:
    """OpenAI-compatible generative client. Prefers Meta Muse Spark; falls back to ASI1 (Fetch.ai) when only that key exists."""

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        chosen = next(((p, os.getenv(k, "")) for p in PROVIDERS for k in [p[1]] if api_key or os.getenv(k, "")), None)
        self.provider, self.model, self.client = "none", model or "unavailable", None
        if chosen:
            (name, _, url_env, url_default, model_env, model_default), env_key = chosen
            self.provider = name
            self.model = model or os.getenv(model_env, model_default)
            self.client = AsyncOpenAI(api_key=api_key or env_key, base_url=base_url or os.getenv(url_env, url_default),
                                      timeout=180, max_retries=2)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        if not self.client:
            raise ModelUnavailable("no generative model key (MODEL_API_KEY or ASI1_API_KEY)")
        try:
            r = await self.client.chat.completions.create(
                model=self.model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except OpenAIError as e:
            raise ModelUnavailable(f"{self.provider} API error: {e}") from e
        text = r.choices[0].message.content or ""
        if not text.strip():
            raise ModelUnavailable(f"{self.provider} returned an empty completion")
        return text

    async def complete_json(self, system: str, user: str, schema: type[BaseModel], max_tokens: int = 4000) -> BaseModel:
        prompt = user + "\n\nReturn ONLY one JSON object matching this JSON schema, no prose:\n" + json.dumps(schema.model_json_schema())
        text = await self.complete(system, prompt, max_tokens)
        for attempt in range(2):
            try:
                return schema.model_validate_json(_extract_json(text))
            except (ValidationError, ValueError) as e:
                if attempt == 1:
                    raise ModelUnavailable(f"Meta returned invalid JSON: {e}") from e
                text = await self.complete(system, f"{prompt}\n\nYour previous answer was invalid ({e}). Fix it.", max_tokens)
        raise AssertionError("unreachable")


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model output")
    return text[start:end + 1]


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return m.group(1) if m else text
