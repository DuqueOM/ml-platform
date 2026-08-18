"""Schema contracts for {@ project_name @}.

Contracts sit at the code boundary, so a break surfaces where the stack trace
is still meaningful rather than three transformations later.

Contracts are versioned: a change that removes or retypes a field is breaking
for every consumer, and the consumers are not all in this project.

**This module imports `data_contracts`, and that is the point.** A generated
project used to DECLARE the shared libraries in its `pyproject.toml` and
import none of them — the exact dishonesty charter criterion C1 forbids,
shipped by the generator itself, so every new project began by failing
`scripts/check_library_reuse.py`. The fix was not to drop the declaration but
to honour it: a project scaffolded by this platform arrives using the
platform.

Replace the example below with the real schema. Keep the shape: every rule
carries a `rationale`, and `DataContract` refuses a rule without one — a bound
with no recorded reason is loosened by whoever it first blocks.
"""

from __future__ import annotations

import polars as pl
from data_contracts import ColumnRule, DataContract

#: The example contract. Two columns, because one is not a schema and ten is
#: a distraction from what the reader has to change.
EXAMPLE = DataContract(
    name="{@ project_slug @}_input",
    version="0.1.0",
    rules=[
        ColumnRule(
            name="entity_id",
            dtype=pl.Utf8,
            nullable=False,
            rationale="Rows with no entity cannot be joined to anything, and a null here silently drops them from every grouped aggregate.",
        ),
        ColumnRule(
            name="event_time",
            dtype=pl.Datetime,
            nullable=False,
            rationale="Every downstream split is temporal. A null timestamp cannot be ordered, so it lands on whichever side of the split the sort happens to put it.",
        ),
    ],
    primary_key=("entity_id", "event_time"),
)

__all__ = ["EXAMPLE"]
