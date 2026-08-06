"""Schema contracts for {@ project_name @}.

Pandera models at the code boundary, so a contract break surfaces where the
stack trace is still meaningful rather than three transformations later.

Contracts are versioned: a change that removes or retypes a field is breaking
for every consumer, and the consumers are not all in this project.
"""
