"""The seam for what this platform adds AROUND a generated service — empty.

**This package holds no implementation, and saying so is the point.** Its
docstring used to describe "shared metric names, OpenTelemetry wiring, and the
health contract" in the present tense, as though they were here. They are not.
An external audit read that and reported the library as broken; it was reading
the docstring, which was the only thing wrong.

ADR-001 and ADR-003 place this package deliberately: the serving LOOP comes
from `ml-service-template`, and what the platform adds around it belongs here
rather than inside a project. That boundary is a decision worth keeping. The
contents are not written yet, because there is exactly one serving consumer,
and a library shaped by one caller is a library the second caller bends
around — the premature abstraction ADR-001 rule 3 warns about by name.

**What fills it, concretely.** The second project that needs to serve. At that
point the two have a shared metric vocabulary, a shared health contract, or
neither — and only then is it knowable which. Until then this package is
declared by nothing: `templates/project/pyproject.toml` used to list it for
every generated project while importing nothing from it, so every new project
began life failing charter criterion C1.

If the serving loop itself ever appears here, the boundary has failed.
"""

#: Kept so the distribution has a version. There is no API yet, and
#: `tests/test_empty_libraries_say_so.py` asserts this file keeps admitting it.
__version__ = "0.1.0"
