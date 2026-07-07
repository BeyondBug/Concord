# Tests

tests/unit/         Fast, no external deps. Run on every PR.
tests/integration/  Requires running connectors. Run every Friday.

Run unit:  pytest tests/unit -v
Run all:   pytest tests/ -v
