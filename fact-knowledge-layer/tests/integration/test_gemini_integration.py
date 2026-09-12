import os
from pathlib import Path
import pytest
from dotenv import dotenv_values
from fkl.config import get_settings
from fkl.domain.enums import BlockKind
from fkl.domain.models import SourceBlock
from fkl.providers.gemini_provider import GeminiProvider


def _get_real_api_key() -> str | None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    vals = dotenv_values(env_path) if env_path.exists() else {}
    key = vals.get("GEMINI_API_KEY") or os.environ.get("REAL_GEMINI_API_KEY")
    if not key:
        k = os.environ.get("GEMINI_API_KEY", "")
        if k and k != "fake-key-for-tests":
            key = k
    return key


def test_gemini_provider_fails_loudly_on_invalid_model():
    """GeminiProvider.__init__ must raise ValueError if the configured model does not exist."""
    api_key = _get_real_api_key()
    if not api_key:
        pytest.skip("No real GEMINI_API_KEY available — skipping loud failure test")

    with pytest.raises(ValueError, match="invalid or inaccessible"):
        GeminiProvider(api_key=api_key, model_name="nonexistent-model-name-xyz-999")


def test_gemini_provider_extract_facts_integration():
    """Instantiate real GeminiProvider with configured default model and extract a trivial fact."""
    api_key = _get_real_api_key()
    if not api_key:
        pytest.skip("No real GEMINI_API_KEY available in .env or environment — skipping live LLM integration test")

    settings = get_settings()
    provider = GeminiProvider(api_key=api_key, model_name=settings.llm_model)

    block = SourceBlock(
        id="blk_test_integration",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=BlockKind.PARAGRAPH,
        text="Solstice Robotics reported standalone revenue of Rs. 4,268 million for the year ended March 31, 2023.",
        text_normalised="solstice robotics reported standalone revenue of rs 4268 million for the year ended march 31 2023",
        content_hash="hash_integration_test",
    )

    candidates = provider.extract_facts(
        block=block,
        document_context="Financial Overview",
        canonical_entity="Solstice Robotics Limited",
    )

    assert len(candidates) > 0, "Real GeminiProvider should extract at least one fact candidate"
    first = candidates[0]
    assert first.entity_raw
    assert first.metric_raw
    assert "4,268" in first.value_raw or "4268" in first.value_raw
    assert first.evidence_quote
