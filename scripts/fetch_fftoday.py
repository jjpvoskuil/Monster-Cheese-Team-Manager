"""
CLI to (re)build data/projections/fftoday_2026.csv.

Two modes:
  --live         Fetch fresh data directly from fftoday.com (requires normal
                  internet access -- will fail in this sandboxed session,
                  should work on Streamlit Cloud or any normal machine).
  --from-capture Parse a saved page-text capture instead (the file format
                  produced by Claude in Chrome's get_page_text, one
                  "==== POS (PosID=NN) ====" section per position -- see
                  data/projections/raw/fftoday_2026_raw.txt for the format
                  this session used to seed the initial data).

Usage:
    python scripts/fetch_fftoday.py --live
    python scripts/fetch_fftoday.py --from-capture data/projections/raw/fftoday_2026_raw.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.data_sources.fftoday import POSITION_CONFIG, fetch_all, parse_position_text

_SECTION_RE = re.compile(r"==== (\w+) \(PosID=\d+\) ====")


def parse_capture_file(path: str) -> pd.DataFrame:
    text = Path(path).read_text()
    parts = _SECTION_RE.split(text)
    sections = {parts[i].lower(): parts[i + 1] for i in range(1, len(parts), 2)}

    frames = []
    for pos in POSITION_CONFIG:
        if pos not in sections:
            raise ValueError(f"capture file is missing a '{pos}' section (looked for {list(sections)})")
        df = parse_position_text(pos, sections[pos])
        if df.empty:
            raise ValueError(f"parsed 0 rows for {pos} from the capture file -- check the section format")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="fetch live from fftoday.com")
    ap.add_argument("--from-capture", metavar="PATH", help="parse a saved page-text capture instead of fetching live")
    ap.add_argument("--output", default="data/projections/fftoday_2026.csv", help="output CSV path")
    args = ap.parse_args()

    if args.live == bool(args.from_capture):
        ap.error("pass exactly one of --live or --from-capture")

    df = fetch_all() if args.live else parse_capture_file(args.from_capture)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
