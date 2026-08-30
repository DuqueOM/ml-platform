"""The store use-case: domain content for the agent core.

`llm-core` holds every mechanism — tier routing, the deterministic policy
engine, the tool registry, cross-tier verification, telemetry. This package
holds what the mechanisms act on: the tools, the prompts, the versioned policy
DATA, and the fixture inventory they read.

That split is ADR-002's placement decision, and this project is the test
ADR-001 rule 3 asks for — *"a library shaped by one caller is a library the
second caller bends around"*. Nothing here patches or subclasses the library.

**`USECASE_ROOT` is exported because the library no longer guesses.** The
source repository resolved a use-case by name against its own layout, which
made `llm-core` know that projects exist and where. Now the caller passes the
directory, and this is the caller.
"""

from pathlib import Path

from store_assistant.tools import build_registry

#: The use-case directory: `config.yaml` and the prompt, grammar, policy and
#: fixture files it names all live beside this module.
USECASE_ROOT = Path(__file__).resolve().parent

__all__ = ["USECASE_ROOT", "build_registry"]
