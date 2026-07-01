"""FastAPI surface for the agent platform (thin transport layer).

Version lives in ONE place — ``core.__version__`` (AUDIT R8-04); this
package re-exports it so ``app.__version__`` keeps working.
"""

from core import __version__

__all__ = ["__version__"]
