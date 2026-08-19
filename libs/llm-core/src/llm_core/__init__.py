"""Retrieval evaluation, a document corpus, and a latent-semantic index.

The docstring here used to promise "tier routing, deterministic policy gate,
tool registry, evaluation harness" — the library ADR-002 plans to migrate,
not the one on disk. What is actually here is the instrument Phase 1e needed:
`retrieval_eval` (recall@k, MRR and a lexical baseline that is allowed to
win), `doc_corpus` (this repository's own documentation, enumerated by git),
and `semantic_index` (TF-IDF into truncated SVD, seeded, offline).

Naming contents that do not exist cost an external audit a critical finding
against `serving-core` for the same reason, in the same week. A package
docstring is the first thing a reader trusts, so it describes what is here —
the migration ADR-002 describes lands with the code, not before it.

Prompts and domain policy content belong to the consuming project, never here.
"""

__version__ = "0.1.0"
