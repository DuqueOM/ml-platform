"""{@ project_name @}.

Owner: {@ owner @}
Kind: {@ project_kind @}

Imports may point DOWN into ``libs/`` and outward to third parties. They may
never point at another project — shared code moves down into ``libs/``, never
sideways (ADR-001 rule 2), enforced by ``tests/test_dependency_direction.py``.
"""

__version__ = "0.1.0"
