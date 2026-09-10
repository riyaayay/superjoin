"""Google Gemini provider — structured output for fact extraction.

Rate limit handling:
- Free tier: 5 RPM (requests per minute) per model
- Uses a token-bucket throttle: min 12s between calls by default (5 RPM = 60s/5)
- On 429: exponential backoff with jitter, up to 3 retries
- Per-document LLM call hard cap: configurable (default 30 to stay well within free tier)
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

import google.generativeai as genai
from pydantic import ValidationError

from fkl.domain.models import ComparisonResult, Fact, FactCandidate, SourceBlock

logger = logging.getLogger(__name__)

_EXTRACT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "entity_raw": {"type": "string"},
            "metric_raw": {"type": "string"},
            "value_raw": {"type": "string"},
            "unit_raw": {"type": "string"},
            "period_raw": {"type": "string"},
            "scope": {"type": "object"},
            "evidence_quote": {"type": "string"},
            "confidence_hint": {"type": "number"},
        },
        "required": ["entity_raw", "metric_raw", "value_raw", "evidence_quote"],
    },
}

_EXTRACT_SYSTEM = """You are a precise fact extractor for institutional financial/economic documents and corporate disclosures.

Rules:
1. Extract ONLY facts that are literally present in the supplied TEXT BLOCK.
2. For each fact, include the exact quote from the text as evidence_quote.
3. Return [] if there is no clear numerical or semantic fact in the block.
4. Never calculate a missing value or infer an unstated date/scope.
5. Do NOT use document filename, company name, or source-set-specific rules.
6. For numeric facts: capture the literal value including units/scale as written.
7. For percentage facts: capture the number and '%' as written.
8. Also extract semantic and governance facts (appointments, resignations, retirements, corporate actions, policy/status declarations), even with no numeric value. metric_raw must only use role/title/topic words that appear verbatim in the source text. Never substitute, infer, or embellish with a different or more senior-sounding title. value_raw is the key action or role/target described.
9. scope should be a dict, e.g. {"consolidation": "standalone"} or {}.
10. confidence_hint: 0.0-1.0, where 1.0 = the value is unambiguously stated."""

_EXTRACT_USER = """Extract facts from this text block. Return a JSON array of fact objects.

DOCUMENT CONTEXT (nearby heading): {context}

TEXT BLOCK:
{text}

Return ONLY a JSON array. If no clear facts, return [].
Each fact must have: entity_raw, metric_raw, value_raw, evidence_quote.
Optional: unit_raw, period_raw, scope (dict), confidence_hint (0-1)."""


def _parse_retry_delay(error_str: str) -> float:
    """Extract retry delay seconds from a 429 error message, default 15s."""
    import re
    m = re.search(r'retry_delay \{.*?seconds:\s*(\d+)', str(error_str), re.DOTALL)
    if m:
        return float(m.group(1)) + random.uniform(0.5, 2.0)
    # Look for milliseconds
    m = re.search(r'(\d+(?:\.\d+)?)\s*ms', str(error_str))
    if m:
        return float(m.group(1)) / 1000 + random.uniform(0.5, 1.5)
    return 15.0 + random.uniform(0, 5)


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.5-flash-lite",
        rpm_limit: int = 15,
        max_retries: int = 3,
    ):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=_EXTRACT_SYSTEM,
        )
        self._model_name = model_name
        self._rpm_limit = rpm_limit
        self._max_retries = max_retries
        # Minimum interval between API calls (seconds). Add 10% headroom.
        self._min_interval = (60.0 / rpm_limit) * 1.1
        self._last_call_time: float = 0.0
        self._metric_cache: dict[tuple[str, str], dict] = {}

    def _throttle(self) -> None:
        """Block until enough time has passed to stay within RPM limit."""
        elapsed = time.monotonic() - self._last_call_time
        wait = self._min_interval - elapsed
        if wait > 0:
            logger.debug("Rate-limit throttle: sleeping %.1fs", wait)
            time.sleep(wait)
        self._last_call_time = time.monotonic()

    def _generate_with_retry(self, prompt: str, generation_config) -> str:
        """Call generate_content with throttle + exponential backoff on 429."""
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._model.generate_content(prompt, generation_config=generation_config)
                return response.text.strip()
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    retry_secs = min(_parse_retry_delay(err_str), 25.0)
                    if attempt < self._max_retries:
                        logger.warning(
                            "429 rate limit on attempt %d/%d — waiting %.1fs before retry",
                            attempt + 1, self._max_retries, retry_secs,
                        )
                        time.sleep(retry_secs)
                        self._last_call_time = 0  # reset throttle so retry goes immediately after wait
                    else:
                        logger.error("429 rate limit — exhausted %d retries, skipping block", self._max_retries)
                        raise
                else:
                    raise
        raise RuntimeError("Unreachable")

    def extract_facts(
        self,
        *,
        block: SourceBlock,
        document_context: str,
        canonical_entity: str | None = None,
    ) -> list[FactCandidate]:
        """Extract facts from a single SourceBlock using Gemini with JSON mode."""
        prompt = _EXTRACT_USER.format(
            context=document_context or "General Document",
            text=block.text,
        )

        try:
            raw = self._generate_with_retry(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=1024,
                ),
            )
            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            data = json.loads(raw)
            if not isinstance(data, list):
                logger.warning("LLM returned non-list: %s", type(data))
                return []
            fallback_entity = canonical_entity or "Entity"
            candidates = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if not item.get("entity_raw"):
                    item["entity_raw"] = fallback_entity
                if not item.get("metric_raw"):
                    continue
                if not item.get("value_raw"):
                    continue
                try:
                    candidates.append(FactCandidate(**item))
                except (ValidationError, TypeError) as e:
                    logger.warning("Candidate validation failed: %s | item: %s", e, item)
            return candidates
        except Exception as e:
            logger.error("Gemini extract_facts error: %s", e)
            return []

    def canonicalise_metric(self, *, left: Fact, right: Fact) -> dict:
        l_str = (left.metric_raw or "").strip().lower()
        r_str = (right.metric_raw or "").strip().lower()
        if not l_str or not r_str:
            return {"same": False, "canonical": left.metric_raw, "similarity": 0.0}
        if l_str == r_str:
            return {
                "same": True,
                "canonical": left.metric_raw,
                "canonical_label": left.metric_raw,
                "similarity": 1.0,
            }

        cache_key = tuple(sorted([l_str, r_str]))
        if cache_key in self._metric_cache:
            return self._metric_cache[cache_key]

        prompt = (
            f"Are these two metric descriptions referring to the same underlying measurement? "
            f"Left: '{left.metric_raw}'. Right: '{right.metric_raw}'. "
            f"Reply with JSON: {{\"same\": true/false, \"canonical\": \"<shared label or left>\", \"similarity\": 0-1}}"
        )
        try:
            raw = self._generate_with_retry(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=128,
                ),
            )
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            res = json.loads(raw)
            if not isinstance(res, dict):
                res = {"same": False, "canonical": left.metric_raw, "similarity": 0.0}
            if "canonical" in res and "canonical_label" not in res:
                res["canonical_label"] = res["canonical"]
            self._metric_cache[cache_key] = res
            return res
        except Exception as e:
            logger.error("Gemini canonicalise_metric error: %s", e)
            fallback = {"same": False, "canonical": left.metric_raw, "similarity": 0.0}
            self._metric_cache[cache_key] = fallback
            return fallback

    def explain_relationship(self, *, comparison: ComparisonResult) -> str:
        """Generate a concise human explanation grounded in the comparison fields."""
        try:
            cmp_json = comparison.model_dump_json(indent=2)
            prompt = (
                f"Given this comparison result between two facts, write a single concise sentence "
                f"(max 60 words) explaining the verdict. Use only values in the JSON. "
                f"Do not mention document filenames or company names.\n\nComparison:\n{cmp_json}"
            )
            raw = self._generate_with_retry(
                prompt,
                generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=128),
            )
            return raw
        except Exception as e:
            logger.error("Gemini explain_relationship error: %s", e)
            return "Explanation unavailable."
