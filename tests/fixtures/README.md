# Test fixtures

Both fixtures below were written by the packaging/CLI builder as **minimal,
clearly-marked local fixtures** because the sibling rinex/client builders had
not landed theirs yet. They are synthetic and spec-plausible — not real NGS
products. Sibling builders: feel free to replace or extend them; the CLI tests
only depend on the paths and on the marker name `TESTRV`.

- `rinex/minimal_2.11.obs` — minimal RINEX 2.11 observation header, 4-hour GPS
  static session (2026-10-01 00:00 → 04:00 UTC), marker `TESTRV`,
  antenna `TRM59900.00` at 1.842 m, 18 satellites, all lines 80 columns.
  `validate_for_opus` returns `[]` for it. Used by `tests/test_cli.py` for a
  real `validate` smoke test.
- `reports/synthetic_success.txt` — synthetic OPUS solution report in the
  standard/extended layout. **Not a real solution; numbers are invented.**
  Provided for parser development and CLI `parse` smoke tests.
