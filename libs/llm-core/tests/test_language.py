"""A use-case's `language` decides which prompts it must bring (R11-6).

`UsecaseConfig.language` was loaded, documented as the language of the
customer-facing surface, set to `es` by store-assistant, and read by nothing.
A Spanish use-case that omitted `safe_fallback` answered its customers in
English, and setting the language changed nothing. Every prompt llm-core
defaults is English, so a use-case in another language must supply each one,
and the agent refuses to be built otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from llm_core import ToolRegistry, build_agent, load_usecase
from llm_core.agent import _DEFAULT_PROMPTS

SPANISH_PROMPTS = {
    "plan_system": "Decide qué herramientas usar.",
    "generate_system": "Responde de forma breve.",
    "reflect_system": "Reflexiona sobre los resultados.",
    "critic_system": "Valida la respuesta.",
    "safe_fallback": "Disculpa, no puedo procesar tu solicitud.",
}


def _with(probe_usecase: Path, **changes: Any) -> Path:
    path = probe_usecase / "config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config.update(changes)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return probe_usecase


def test_a_spanish_use_case_left_on_english_defaults_is_refused(probe_usecase: Path) -> None:
    config = load_usecase(_with(probe_usecase, language="es"))
    with pytest.raises(ValueError, match="customers would be answered in English") as refused:
        build_agent(config, ToolRegistry())
    for key in _DEFAULT_PROMPTS:
        assert key in str(refused.value), f"the refusal does not name {key}"


def test_one_missing_prompt_is_enough_to_refuse(probe_usecase: Path) -> None:
    prompts = {key: text for key, text in SPANISH_PROMPTS.items() if key != "safe_fallback"}
    config = load_usecase(_with(probe_usecase, language="es", prompts=prompts))
    with pytest.raises(ValueError, match="leaves safe_fallback to"):
        build_agent(config, ToolRegistry())


def test_a_spanish_use_case_with_its_own_prompts_answers_in_them(probe_usecase: Path) -> None:
    agent = build_agent(load_usecase(_with(probe_usecase, language="es", prompts=SPANISH_PROMPTS)), ToolRegistry())
    assert agent._prompt("safe_fallback") == SPANISH_PROMPTS["safe_fallback"]


def test_every_default_prompt_is_covered_by_the_rule() -> None:
    """A default added later without a Spanish counterpart here would leave this rule untested for it."""
    assert set(SPANISH_PROMPTS) == set(_DEFAULT_PROMPTS)


@pytest.mark.parametrize("language", ["en", "en-GB", "EN"])
def test_english_in_any_spelling_may_use_the_defaults(probe_usecase: Path, language: str) -> None:
    build_agent(load_usecase(_with(probe_usecase, language=language)), ToolRegistry())


def test_a_region_does_not_make_a_language_english(probe_usecase: Path) -> None:
    config = load_usecase(_with(probe_usecase, language="pt-BR"))
    with pytest.raises(ValueError, match="'pt-BR'"):
        build_agent(config, ToolRegistry())


def test_an_omitted_language_is_english(probe_usecase: Path) -> None:
    assert load_usecase(probe_usecase).language == "en"


@pytest.mark.parametrize("language", ["spanish", "es_CO", "", "e", "es-"])
def test_a_value_that_is_not_a_language_tag_fails_at_load(probe_usecase: Path, language: str) -> None:
    """A typo must not read as "not English" and pass for a language."""
    with pytest.raises(ValueError, match="not a language tag"):
        load_usecase(_with(probe_usecase, language=language))
