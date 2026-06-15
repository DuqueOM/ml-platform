"""Tests for the cross-tier verifier + bounded self-consistency (plan §F2.3).

Offline: a fake TierClient routes responses by the station's system prompt, so
tests are robust to loop ordering (plan/reflect/generate/critic).
"""

import pytest

from core import load_agent
from core.schemas import Route


def _reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": 3}}


class FakeTiers:
    def __init__(self, *, generate="respuesta", critic="APPROVED", critic_votes=None, regenerate=None):
        self.generate = generate
        self.critic = critic
        self.critic_votes = list(critic_votes) if critic_votes else None
        self.regenerate = regenerate
        self.critic_calls = 0
        self.gen_calls = 0
        self.judge_tiers: list[int] = []

    def call(self, tier, messages, **kwargs):
        system = messages[0]["content"]
        if "Planea" in system:
            return _reply("NONE")
        if "Reflexiona" in system:
            return _reply("ok")
        if "verificador" in system:
            self.critic_calls += 1
            self.judge_tiers.append(tier)
            if self.critic_votes is not None:
                return _reply(self.critic_votes.pop(0))
            return _reply(self.critic)
        # generation (system mentions WhatsApp)
        self.gen_calls += 1
        if self.gen_calls > 1 and self.regenerate is not None:
            return _reply(self.regenerate)
        return _reply(self.generate)


def _route(risk, tier=1):
    return Route(
        intent="complaint",
        tier=tier,
        confidence=0.95,
        risk=risk,
        ambiguity="low",
        tool_needed=False,
        finality="answer",
        expected_followup=False,
    )


@pytest.fixture
def agent():
    return load_agent("tienda")


def _with_route(agent, risk, tier=1):
    agent.router.route = lambda msg: _route(risk, tier)  # type: ignore[assignment]


def test_low_risk_skips_verifier(agent):
    _with_route(agent, "low")
    fake = FakeTiers()
    agent.tiers = fake
    result = agent.handle("hola")
    assert result["critic_verdict"] == "skipped"
    assert result["critic_outcome"] is None
    assert fake.critic_calls == 0


def test_verifier_runs_at_higher_tier(agent):
    _with_route(agent, "medium", tier=1)
    fake = FakeTiers(critic="APPROVED")
    agent.tiers = fake
    result = agent.handle("tengo una queja")
    assert result["critic_verdict"] == "approved"
    assert result["escalated"] is False
    assert result["critic_outcome"]["tier"] == 2  # gen tier 1 + offset 1
    assert fake.judge_tiers == [2]


def test_verifier_rejection_escalates_and_regenerates(agent):
    _with_route(agent, "medium", tier=1)
    fake = FakeTiers(critic="REJECTED", regenerate="respuesta corregida")
    agent.tiers = fake
    result = agent.handle("tengo una queja")
    assert result["critic_verdict"] == "rejected"
    assert result["escalated"] is True
    assert result["response"] == "respuesta corregida"


def test_self_consistency_majority_approves(agent):
    agent.config.verification["self_consistency_k"] = 3
    _with_route(agent, "high", tier=1)
    fake = FakeTiers(critic_votes=["APPROVED", "REJECTED", "APPROVED"])
    agent.tiers = fake
    result = agent.handle("esto es urgente")
    assert fake.critic_calls == 3
    assert result["critic_outcome"]["votes"] == [True, False, True]
    assert result["critic_verdict"] == "approved"


def test_self_consistency_minority_rejects(agent):
    agent.config.verification["self_consistency_k"] = 3
    _with_route(agent, "high", tier=1)
    fake = FakeTiers(critic_votes=["REJECTED", "APPROVED", "REJECTED"], regenerate="corregida")
    agent.tiers = fake
    result = agent.handle("esto es urgente")
    assert result["critic_outcome"]["votes"] == [False, True, False]
    assert result["critic_verdict"] == "rejected"
    assert result["escalated"] is True


def test_self_consistency_only_for_high_risk(agent):
    # k=3 configured but risk is medium and high_only is true -> single pass.
    agent.config.verification["self_consistency_k"] = 3
    _with_route(agent, "medium", tier=1)
    fake = FakeTiers(critic="APPROVED")
    agent.tiers = fake
    agent.handle("tengo una queja")
    assert fake.critic_calls == 1


def test_verification_can_be_disabled(agent):
    agent.config.verification["enabled"] = False
    _with_route(agent, "medium", tier=1)
    fake = FakeTiers()
    agent.tiers = fake
    result = agent.handle("tengo una queja")
    assert fake.critic_calls == 0
    assert result["critic_outcome"]["votes"] == []
    assert result["critic_verdict"] == "approved"
