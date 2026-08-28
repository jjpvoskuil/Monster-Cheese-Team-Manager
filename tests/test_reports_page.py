"""
AppTest smoke tests for the Reports page (punch-list item #7): pick any
combination of reports/grids and download them as one Excel workbook.
The report-building logic itself is unit-tested in
tests/test_report_catalog.py -- these tests just confirm the page wires
that up, the download button gets real bytes, and deselecting a report
actually changes what's on offer.

Same AppTest-via-app.py pattern as tests/test_draft_board_page.py (see
that file's module docstring for why), and the same save/restore
fixture for the live data/draft_state.json.
"""

from __future__ import annotations

import os

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")


@pytest.fixture(autouse=True)
def _clean_draft_state():
    backup = None
    if os.path.exists(DRAFT_STATE_FILE):
        with open(DRAFT_STATE_FILE) as f:
            backup = f.read()
        os.remove(DRAFT_STATE_FILE)
    yield
    if os.path.exists(DRAFT_STATE_FILE):
        os.remove(DRAFT_STATE_FILE)
    if backup is not None:
        with open(DRAFT_STATE_FILE, "w") as f:
            f.write(backup)


def _open_page():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/7_Reports.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def test_reports_page_renders_with_everything_selected_by_default():
    at = _open_page()
    multiselect = at.multiselect[0]
    assert multiselect.value  # not empty -- everything on by default
    assert len(multiselect.value) == len(multiselect.options)


def test_reports_page_download_button_is_wired_to_a_real_file():
    at = _open_page()
    download_buttons = at.get("download_button")
    assert len(download_buttons) == 1
    button = download_buttons[0]
    assert not button.proto.disabled
    # Streamlit stores the actual bytes out-of-band (media file manager)
    # and points the button at a URL, rather than inlining data on the
    # proto -- a real .xlsx url is what confirms build_workbook_bytes()
    # actually produced and attached a file, not an empty/broken button.
    assert button.proto.url.endswith(".xlsx")


def test_reports_page_deselecting_a_report_shrinks_the_sheet_count():
    at = _open_page()
    multiselect = at.multiselect[0]
    full_caption = next(c.value for c in at.caption if c.value.startswith("Will produce"))

    fewer = [v for v in multiselect.value if "League Rosters" not in v]
    multiselect.set_value(fewer).run(timeout=60)
    assert not at.exception

    shrunk_caption = next(c.value for c in at.caption if c.value.startswith("Will produce"))
    assert shrunk_caption != full_caption


def test_reports_page_with_nothing_selected_shows_a_prompt_not_an_error():
    at = _open_page()
    multiselect = at.multiselect[0]
    multiselect.set_value([]).run(timeout=60)
    assert not at.exception
    assert any("Select at least one report" in i.value for i in at.info)
    assert not at.get("download_button")
