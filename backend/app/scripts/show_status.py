"""Print the durable-data status (thin wrapper around the import CLI)."""

from __future__ import annotations

from .import_historical_data import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(["--status"]))
