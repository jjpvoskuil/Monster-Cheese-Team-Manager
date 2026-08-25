#!/usr/bin/env python3
"""
Turn a saved CBS draft-results page (plain text) into structured JSON, and
optionally update config/league_settings.yaml's draft.team_order in place.

CBS's draft-results page requires a logged-in session and blocks plain
HTTP fetches (robots.txt), so this script does NOT fetch the page itself.
The workflow each year is:

  1. Know the URL for the new season:
       python scripts/fetch_draft_order.py --print-url --year 2027
     (edit src/data_sources/draft_order.draft_results_url() first if CBS
     ever renames the draft event or changes the URL pattern)

  2. Visit that URL in a logged-in browser (Claude in Chrome, or your own
     browser) and grab the page's plain text — with Claude in Chrome
     that's the "get page text" action; by hand it's select-all + copy
     from the draft results table. Save it to a .txt file.

  3. Run this script against that file:
       python scripts/fetch_draft_order.py \\
           --input /path/to/raw_page.txt \\
           --year 2027 \\
           --source-url "https://maniacfl.football.cbssports.com/draft/results/2027:Pre-season:MFL%20Draft%202027/" \\
           --update-config

     This writes data/draft/2027_draft_order.json and (with
     --update-config) replaces the draft.team_order list in
     config/league_settings.yaml with the freshly parsed round-1 order.

Only handles a draft that HASN'T started yet (CBS shows "NOT STARTED",
every pick's PLAYER column empty) — see src/data_sources/draft_order.py
for why.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_sources.draft_order import parse_draft_order_text, draft_results_url

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")


def update_config_team_order(config_path: str, team_order: list[str]) -> None:
    """Replace the `draft.team_order:` list in the YAML file in place,
    via targeted text substitution rather than a full parse/dump round
    -trip — a real YAML round-trip would silently drop every comment in
    the file, and this file's comments are load-bearing documentation."""
    with open(config_path, "r") as f:
        content = f.read()

    items = "\n".join(f'    - "{team}"' for team in team_order)
    block = (
        "  team_order:  # round-1 snake order, refreshed by scripts/fetch_draft_order.py\n"
        f"{items}\n"
    )

    pattern = re.compile(
        r"  team_order:.*?(?=\n  \S|\nroster:|\Z)", re.DOTALL
    )
    if pattern.search(content):
        new_content = pattern.sub(block.rstrip("\n"), content, count=1)
    else:
        # No existing team_order block — insert right after the `draft:`
        # section's `rounds:` line (a stable, always-present anchor).
        anchor = re.compile(r"(  rounds: \d+.*\n)")
        if not anchor.search(content):
            raise ValueError(
                "Could not find an anchor to insert draft.team_order into "
                f"{config_path} — insert it manually."
            )
        new_content = anchor.sub(r"\1" + block, content, count=1)

    with open(config_path, "w") as f:
        f.write(new_content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="Path to saved raw page text")
    parser.add_argument("--year", type=int, help="Draft season year")
    parser.add_argument("--source-url", help="URL the page text was captured from")
    parser.add_argument("--captured-at", default=str(date.today()), help="Capture date, default today")
    parser.add_argument("--output", help="Output JSON path (default data/draft/<year>_draft_order.json)")
    parser.add_argument("--update-config", action="store_true", help="Also patch config/league_settings.yaml draft.team_order")
    parser.add_argument("--print-url", action="store_true", help="Just print the expected CBS URL for --year and exit")
    args = parser.parse_args()

    if args.print_url:
        if not args.year:
            parser.error("--print-url requires --year")
        print(draft_results_url(args.year))
        return

    if not args.input or not args.year:
        parser.error("--input and --year are required (unless using --print-url)")

    with open(args.input, "r") as f:
        raw_text = f.read()

    result = parse_draft_order_text(raw_text)
    result.year = args.year
    result.source_url = args.source_url or draft_results_url(args.year)
    result.captured_at = args.captured_at

    output_path = args.output or os.path.join(ROOT, "data", "draft", f"{args.year}_draft_order.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
        f.write("\n")

    print(f"Wrote {output_path}")
    print(f"  {result.rounds} rounds x {result.teams_per_round} teams, standard snake: {result.is_standard_snake}")
    if result.notes:
        for note in result.notes:
            print(f"  NOTE: {note}")
    print(f"  Round 1 order: {result.team_order}")

    if args.update_config:
        update_config_team_order(CONFIG_PATH, result.team_order)
        print(f"Updated {CONFIG_PATH} draft.team_order")


if __name__ == "__main__":
    main()
