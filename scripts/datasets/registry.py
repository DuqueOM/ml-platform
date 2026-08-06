"""Dataset registry — the single machine-readable source for acquisition.

`docs/datasets/register.md` explains *why* each dataset was chosen. This module
declares *how* to obtain it, and under what licence. The two must agree, which
`test_dataset_registry.py` enforces: a dataset documented but not declared is a
download nobody can reproduce, and one declared but not documented is data with
no recorded reason to exist.

Two rules the whole module exists to enforce:

1. **Raw data is never committed.** Everything lands under ``data/``, which is
   gitignored, and is versioned by reference.
2. **Redistribution is not the same as use.** Several sources permit use but
   forbid redistribution. That distinction is a field here, not a footnote, so
   a pipeline can refuse to publish derived artifacts it is not allowed to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Access(StrEnum):
    """How a dataset is obtained, which determines what can be automated."""

    #: Direct HTTP(S). Fully automatable.
    PUBLIC_HTTP = "public_http"
    #: Requires an authenticated CLI the user must configure (e.g. Kaggle).
    AUTHENTICATED_CLI = "authenticated_cli"
    #: Installed as a Python package that fetches on first use.
    PYTHON_PACKAGE = "python_package"
    #: Requires a signed data use agreement. Never automated — by design.
    DATA_USE_AGREEMENT = "data_use_agreement"


class Redistribution(StrEnum):
    """What may be published from this data.

    The pipeline reads this before writing any artifact to a public location.
    Getting it wrong is a licence breach, not a style issue.
    """

    #: Public domain or an open licence permitting redistribution.
    ALLOWED = "allowed"
    #: Use permitted, redistribution forbidden. Derived artifacts must stay private
    #: unless they are aggregate enough not to constitute redistribution.
    FORBIDDEN = "forbidden"
    #: Permitted with attribution and matching terms (e.g. CC BY-NC-SA).
    SHARE_ALIKE_NONCOMMERCIAL = "share_alike_noncommercial"


@dataclass(frozen=True)
class Dataset:
    """One registered dataset.

    Attributes:
        key: Stable identifier; also the directory name under ``data/``.
        title: Human name, matching `docs/datasets/register.md`.
        project: Which project consumes it, or ``"shared"``.
        access: How it is obtained.
        redistribution: What may be published from it.
        licence: Licence name as stated by the source.
        urls: Direct download URLs, for ``PUBLIC_HTTP`` sources.
        source_hint: For non-HTTP sources, the exact command or page needed.
        notes: Hazards worth knowing before the first run.
        sample_only: When True, the fetcher pulls a bounded sample by default.
            The full history is opt-in, because a first run should not silently
            download hundreds of gigabytes.
    """

    key: str
    title: str
    project: str
    access: Access
    redistribution: Redistribution
    licence: str
    urls: list[str] = field(default_factory=list)
    source_hint: str = ""
    notes: str = ""
    sample_only: bool = False

    @property
    def automatable(self) -> bool:
        """True when this dataset can be fetched without human setup."""
        return self.access in (Access.PUBLIC_HTTP, Access.PYTHON_PACKAGE)


# NYC TLC publishes one parquet file per month per service. Two months is
# enough to exercise partitioning, schema evolution and an incremental append;
# the full history is a deliberate, separate action.
_TLC_BASE = "https://d37ci6vzurychx.cloudfront.net/trip-data"
_TLC_SAMPLE_MONTHS = ["2024-01", "2024-02"]

REGISTRY: dict[str, Dataset] = {
    "nyc-tlc": Dataset(
        key="nyc-tlc",
        title="NYC TLC Trip Records",
        project="demand-forecast",
        access=Access.PUBLIC_HTTP,
        redistribution=Redistribution.ALLOWED,
        licence="Public domain / NYC open data",
        urls=[f"{_TLC_BASE}/yellow_tripdata_{month}.parquet" for month in _TLC_SAMPLE_MONTHS],
        sample_only=True,
        notes=(
            "Schema evolves across years — a feature for exercising Iceberg schema "
            "evolution, a trap for anyone assuming stability. Some months contain "
            "implausible coordinates and durations; cleaning rules belong in the "
            "data contract, not in undocumented preprocessing."
        ),
    ),
    "folktables": Dataset(
        key="folktables",
        title="Folktables (ACS PUMS)",
        project="credit-risk",
        access=Access.PYTHON_PACKAGE,
        redistribution=Redistribution.ALLOWED,
        licence="US Census public use",
        source_hint="pip install folktables; data is fetched by the package on first use",
        notes=(
            "Partitioned by state and year, so distribution shift is built in rather "
            "than manufactured by splitting. Fairness results are sensitive to the "
            "task definition and threshold: document both in the model card."
        ),
    ),
    "home-credit": Dataset(
        key="home-credit",
        title="Home Credit Default Risk",
        project="credit-risk",
        access=Access.AUTHENTICATED_CLI,
        redistribution=Redistribution.FORBIDDEN,
        licence="Kaggle competition terms — use permitted, redistribution NOT",
        source_hint="kaggle competitions download -c home-credit-default-risk",
        notes=(
            "Multiple related tables with per-applicant history — the shape that makes "
            "point-in-time correctness a requirement rather than a lecture. Never commit "
            "derived files without checking the terms."
        ),
    ),
    "olist": Dataset(
        key="olist",
        title="Olist Brazilian E-Commerce",
        project="shared",
        access=Access.AUTHENTICATED_CLI,
        redistribution=Redistribution.SHARE_ALIKE_NONCOMMERCIAL,
        licence="CC BY-NC-SA — non-commercial, attribution required",
        source_hint="kaggle datasets download -d olistbr/brazilian-ecommerce",
        notes="Nine related tables with real timestamps; small enough for a free-tier database.",
    ),
    "funsd": Dataset(
        key="funsd",
        title="FUNSD (form understanding)",
        project="doc-intelligence",
        access=Access.PUBLIC_HTTP,
        redistribution=Redistribution.FORBIDDEN,
        licence="Research use; check terms before publishing derived artifacts",
        urls=["https://guillaumejaume.github.io/FUNSD/dataset.zip"],
        notes="Small; fits comfortably in the available VRAM for LoRA fine-tuning.",
    ),
    "sec-edgar": Dataset(
        key="sec-edgar",
        title="SEC EDGAR filings",
        project="rag-assistant",
        access=Access.PUBLIC_HTTP,
        redistribution=Redistribution.ALLOWED,
        licence="US public record",
        urls=["https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/form.idx"],
        sample_only=True,
        notes=(
            "EDGAR REQUIRES a declared User-Agent with a contact address and enforces "
            "rate limits (10 requests/second). The fetcher honours both; a client that "
            "does not will be blocked."
        ),
    ),
    "mimic-iv": Dataset(
        key="mimic-iv",
        title="MIMIC-IV",
        project="not-adopted",
        access=Access.DATA_USE_AGREEMENT,
        redistribution=Redistribution.FORBIDDEN,
        licence="PhysioNet credentialed access — CITI training + signed DUA",
        source_hint="https://physionet.org/content/mimiciv/ — requires credentialing",
        notes=(
            "Registered but NOT adopted. Listed so the reason is recorded rather than "
            "rediscovered: it needs credentialing that takes weeks. Revisit only if "
            "healthcare becomes a target domain."
        ),
    ),
}


def get(key: str) -> Dataset:
    """Look up a dataset, failing with the valid keys rather than a KeyError."""
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown dataset {key!r}; registered: {sorted(REGISTRY)}") from None
