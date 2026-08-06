"""Versioned schema contracts with an explicit compatibility rule.

A schema says what the data looks like now. A contract says what consumers may
rely on and what a producer may change without asking — which is the part that
matters once more than one thing reads the data.

    from data_contracts import ColumnRule, Compatibility, DataContract
"""

from data_contracts.contract import (
    ColumnRule,
    Compatibility,
    ContractError,
    ContractViolation,
    DataContract,
)

__version__ = "0.1.0"

__all__ = [
    "ColumnRule",
    "Compatibility",
    "ContractError",
    "ContractViolation",
    "DataContract",
]
