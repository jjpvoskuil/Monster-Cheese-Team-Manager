# Real 2026 projections go here

Drop one CSV/Excel file per projection source in this folder (e.g.
`cbs_qb.csv`, `fantasypros_all.csv`, `espn_rb.csv`). Each file's name (minus
extension) is used as its source tag for blending in `src/projections.py`.

Column headers don't need to match exactly — `src/data_sources/manual_import.py`
maps common aliases (e.g. "Pass Yds", "PaYd", "pass_yards" all map to the
same canonical column). See that file for the full alias list and the
canonical schema if a source's columns aren't being picked up.

As soon as any file exists here, the Draft Board stops using
`data/sample/` (last year's placeholder data) automatically.
