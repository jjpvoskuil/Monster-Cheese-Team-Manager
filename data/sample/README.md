# Sample data — NOT real projections

`sample_projections.csv` is a small, hand-built, synthetic set of ~15
players spanning every position, used only to smoke-test the pipeline
(scoring → blending → ranking → Draft Board UI) end to end. Stat lines are
plausible but made up, not sourced from any projection provider.

The Draft Board page (`pages/1_Draft_Board.py`) only falls back to this
folder when `data/projections/` is empty, and shows a visible warning
banner when it does. Real 2026 projections belong in `data/projections/`
(see the README there).
