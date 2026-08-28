"""
CLI to (re)build data/projections/fantasypoints_2026.csv from a browser
capture of FantasyPoints.com's season projections export.

FantasyPoints.com is login-gated (paid subscription) -- there is no
--live mode here, unlike fetch_fftoday.py/fetch_fantasypros.py. Only
--from-capture-dir is supported: point it at a directory containing the
6 per-position CSVs (qb.csv/rb.csv/wr.csv/te.csv/k.csv/dst.csv) saved by
clicking FantasyPoints' own "Download CSV" button once per position on
its Season Projections page (NFL -> Projections & Rankings -> Season) --
see src/data_sources/fantasypoints.py's module docstring for the full
capture procedure and this source's known limitations (no fumbles-lost;
no DST points/yards-allowed).

Usage:
    python scripts/fetch_fantasypoints.py --from-capture-dir data/projections/raw/fantasypoints_capture
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_sources.fantasypoints import load_capture_dir
from src.data_sources.manual_import import CANONICAL_COLUMNS


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-capture-dir", metavar="DIR", required=True,
                     help="directory with qb.csv/rb.csv/wr.csv/te.csv/k.csv/dst.csv from FantasyPoints' CSV export")
    ap.add_argument("--output", default="data/projections/fantasypoints_2026.csv", help="output CSV path")
    args = ap.parse_args()

    df = load_capture_dir(args.from_capture_dir)

    # Write with the full canonical column set (in canonical order) so this
    # file loads identically to cbs_2026.csv/fftoday_2026.csv via
    # manual_import.load_table() -- missing columns (e.g. fumbles_lost,
    # this source's known gap -- see the module docstring) are written out
    # as blank, same as those files already do for columns THEY lack.
    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[CANONICAL_COLUMNS]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
