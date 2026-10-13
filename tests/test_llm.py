from __future__ import annotations

import pytest

from juniper.config import load_config
from juniper.llm import StructuredCallFailed, call_structured
from juniper.models import (
    Agent1Output,
    Agent2Output,
    Agent5Output,
    BaselineOutput,
    ThemeBrief,
)

MOCK_AGENTS = [
    ("agent1_tagger", Agent1Output),
    ("agent2_polarity", Agent2Output),
    ("agent4_brief", ThemeBrief),
    ("agent5_editor", Agent5Output),
    ("baseline", BaselineOutput),
]


@pytest.fixture
def mock_config():
    return load_config(provider_override="mock")


@pytest.mark.parametrize("agent_name,output_model", MOCK_AGENTS)
def test_t01_mock_fixture_validates(mock_config, agent_name, output_model):
    parsed, log = call_structured(agent_name, "unused in mock mode", output_model, config=mock_config, test_id="T01")

    assert isinstance(parsed, output_model)
    assert log.provider == "mock"
    assert log.ok is True
    assert log.latency_s == 0 or log.latency_s >= 0  # mock mode: effectively instant
    assert log.input_tokens == 0
    assert log.output_tokens == 0
    assert log.cost_eur == 0.0


def test_mock_mode_requires_test_id(mock_config):
    with pytest.raises(ValueError, match="test_id"):
        call_structured("agent1_tagger", "prompt", Agent1Output, config=mock_config)


def test_mock_mode_missing_fixture_raises_clear_error(mock_config):
    with pytest.raises(FileNotFoundError, match="Mock fixture not found"):
        call_structured("agent1_tagger", "prompt", Agent1Output, config=mock_config, test_id="T99_does_not_exist")


# ---------------------------------------------------------------------------
# Retry logic (no real network: a fake Adapter is injected)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Returns `responses[call_index]` each time generate() is called, so tests can
    script "fails once, then succeeds" without any real provider."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    def generate(self, prompt, output_model):
        text = self.responses[self.calls]
        self.calls += 1
        return text, 10, 5, "fake-model"


VALID_AGENT1 = (
    '{"items": [{"comment_id": "F01", "usable": true, '
    '"themes": [{"theme": "coffee_quality", "quote": "Lovely coffee"}], '
    '"new_theme_suggestion": null}]}'
)
INVALID_JSON = "not json at all"
VALID_BUT_WRONG_SHAPE = '{"not_items": []}'


def test_retry_recovers_after_one_failure():
    config = load_config(provider_override="gemini")
    fake = _FakeAdapter([INVALID_JSON, VALID_AGENT1])

    parsed, log = call_structured(
        "agent1_tagger", "tag these comments", Agent1Output, config=config, adapter=fake
    )

    assert fake.calls == 2
    assert log.ok is True
    assert log.retries == 1
    assert parsed.items[0].comment_id == "F01"


def test_retry_recovers_from_wrong_shape_too():
    config = load_config(provider_override="gemini")
    fake = _FakeAdapter([VALID_BUT_WRONG_SHAPE, VALID_AGENT1])

    parsed, log = call_structured(
        "agent1_tagger", "tag these comments", Agent1Output, config=config, adapter=fake
    )

    assert log.ok is True
    assert log.retries == 1


def test_exhausting_retries_raises_structured_call_failed():
    config = load_config(provider_override="gemini")
    fake = _FakeAdapter([INVALID_JSON] * (config.max_retries + 1))

    with pytest.raises(StructuredCallFailed) as exc_info:
        call_structured("agent1_tagger", "tag these comments", Agent1Output, config=config, adapter=fake)

    assert exc_info.value.call_log.ok is False
    assert exc_info.value.call_log.retries == config.max_retries
    assert fake.calls == config.max_retries + 1
