"""Fetch real filings from EDGAR, because the index is not the corpus.

`data/sec-edgar/` held `form.idx` — 57 MB cataloguing which filings exist and
where. Not one filing. Everything built on top of it until now was tested
against strings written by hand, and synthetic text is exactly what hid two
defects in the sibling project until real data arrived.

**SEC's terms are enforced here, not documented.** EDGAR requires a
`User-Agent` naming a real contact and rate-limits to 10 requests per second.
A scraper that ignores either gets the IP blocked, so the delay is not
politeness — it is the difference between a corpus and a ban.
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rag_assistant.contracts import FILING_INDEX

EDGAR = "https://www.sec.gov"

#: SEC requires a contact address. A generic string is a blocked IP.
USER_AGENT = "ml-platform-research DuqueOM (queenhollycruz@gmail.com)"

#: SEC allows 10 requests per second. Sitting at the limit is how a shared
#: address gets throttled for everyone behind it, so this runs at half.
REQUEST_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True)
class Filing:
    """One filing listed in the index.

    Attributes:
        form: Form type, e.g. `10-K`.
        company: Registrant name.
        cik: Central Index Key — the stable identifier. Company names change.
        filed: Filing date, `YYYY-MM-DD`.
        path: Archive path, relative to the EDGAR root.
    """

    form: str
    company: str
    cik: str
    filed: str
    path: str

    @property
    def url(self) -> str:
        """The archive URL.

        `/Archives/` is required and the index does not carry it: form.idx
        stores `edgar/data/...`, while the document lives at
        `/Archives/edgar/data/...`. Building the URL from the index path alone
        returns 404 for every filing — which it did, on the first request.
        """
        return f"{EDGAR}/Archives/{self.path.lstrip('/')}"

    @property
    def local_name(self) -> str:
        """CIK and date, not the company name — names contain slashes."""
        return f"{self.cik}-{self.filed}-{self.form.replace('/', '-')}.txt"


def _require_https(url: str) -> None:
    """Refuse a URL that is not HTTPS.

    `urllib.request.urlopen` honours `file://` and any registered scheme, so a
    URL that arrives from configuration or a registry can read local disk while
    looking like a download. Both call sites here fetch from one known public
    host; asserting that costs a line.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"refusing to fetch {url!r}: only https is permitted")


def parse_index(index_path: Path, *, form_type: str = "10-K") -> list[Filing]:
    """Read `form.idx` and return the filings of one type.

    The file is fixed-width with a header block. Parsed by splitting on runs of
    two or more spaces rather than by column offsets: the offsets differ
    between quarters, and a hardcoded slice silently mis-parses instead of
    failing.
    """
    rows = []
    for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = [field.strip() for field in line.split("  ") if field.strip()]
        if len(parts) != 5 or parts[0] != form_type:
            continue
        form, company, cik, filed, path = parts
        rows.append({"form": form, "company": company, "cik": cik, "filed": filed, "path": path})

    if not rows:
        return []

    # The contract replaces the inline `cik.isdigit()` check, and does one
    # thing that check could not: it REPORTS. A row that fails is returned as
    # a violation with the rule it broke, so a quarter whose fixed-width
    # layout changed produces a finding rather than a shorter list.
    frame = pl.DataFrame(rows)
    FILING_INDEX.validate(frame)

    digits = frame.filter(pl.col("cik").str.contains(r"^\d+$"))
    return [Filing(**row) for row in digits.iter_rows(named=True)]


def fetch_filings(filings: list[Filing], destination: Path, *, limit: int = 10) -> list[Path]:
    """Download filings, honouring SEC's contact and rate-limit requirements.

    Args:
        filings: Parsed from the index.
        destination: Directory to write into.
        limit: How many to fetch. Small on purpose — the corpus needs to be big
            enough to make retrieval non-trivial and small enough that a
            re-download is not an imposition on a public service.

    Returns:
        Paths written. Already-present files are not re-fetched, so a rerun
        after a failure resumes rather than starting over.
    """
    destination.mkdir(parents=True, exist_ok=True)
    written = []

    for filing in filings[:limit]:
        target = destination / filing.local_name
        if target.exists():
            written.append(target)
            continue

        _require_https(filing.url)
        request = urllib.request.Request(filing.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            target.write_bytes(response.read())
        written.append(target)
        time.sleep(REQUEST_INTERVAL_SECONDS)

    return written
