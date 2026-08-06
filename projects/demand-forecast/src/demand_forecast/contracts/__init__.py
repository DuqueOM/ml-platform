"""Schema contracts for this project.

Lives under ``src/`` rather than at the project root so it is importable as
``demand_forecast.contracts`` — a contract that cannot be imported by the code
it governs is a document, not a contract.
"""

from demand_forecast.contracts.trips import TRIPS_RAW

__all__ = ["TRIPS_RAW"]
