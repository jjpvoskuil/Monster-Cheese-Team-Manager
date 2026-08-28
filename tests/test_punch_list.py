import json
import os
import tempfile

import pytest

from src.punch_list import PunchList


def _fresh_list():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)  # start from no file
    return PunchList(state_file=tmp.name)


def test_add_creates_an_open_item_with_defaults():
    pl = _fresh_list()
    item = pl.add("Fix bye week display")
    assert item.status == "Open"
    assert item.priority == "Medium"
    assert item.description == ""
    assert item.id  # non-empty auto-generated id
    assert item.number == 1
    assert [i.id for i in pl.open_items()] == [item.id]
    assert pl.closed_items() == []


def test_add_assigns_sequential_numbers_starting_at_1():
    pl = _fresh_list()
    a = pl.add("First")
    b = pl.add("Second")
    c = pl.add("Third")
    assert [a.number, b.number, c.number] == [1, 2, 3]


def test_deleting_an_item_does_not_reuse_its_number():
    pl = _fresh_list()
    a = pl.add("First")
    pl.add("Second")
    pl.delete(a.id)
    c = pl.add("Third")
    assert c.number == 3  # not 2 -- #1 is gone for good, not recycled


def test_get_by_number_finds_the_right_item_and_raises_for_unknown():
    pl = _fresh_list()
    pl.add("First")
    second = pl.add("Second")
    assert pl.get_by_number(2).id == second.id
    with pytest.raises(KeyError):
        pl.get_by_number(999)


def test_add_strips_whitespace_and_rejects_a_blank_title():
    pl = _fresh_list()
    item = pl.add("  Add sortable columns  ", description="  some notes  ")
    assert item.title == "Add sortable columns"
    assert item.description == "some notes"
    with pytest.raises(ValueError):
        pl.add("   ")


def test_add_rejects_an_invalid_priority():
    pl = _fresh_list()
    with pytest.raises(ValueError):
        pl.add("Something", priority="Urgent")


def test_update_changes_only_the_provided_fields():
    pl = _fresh_list()
    item = pl.add("Original title", description="orig desc", priority="Low")
    updated = pl.update(item.id, priority="High")
    assert updated.title == "Original title"
    assert updated.description == "orig desc"
    assert updated.priority == "High"
    assert updated.updated_at >= item.created_at


def test_update_rejects_blank_title_or_invalid_priority():
    pl = _fresh_list()
    item = pl.add("Keep me")
    with pytest.raises(ValueError):
        pl.update(item.id, title="   ")
    with pytest.raises(ValueError):
        pl.update(item.id, priority="Nope")
    # neither rejected update should have mutated the item
    assert pl._find(item.id).title == "Keep me"
    assert pl._find(item.id).priority == "Medium"


def test_close_and_reopen_round_trip():
    pl = _fresh_list()
    item = pl.add("Something to fix")
    closed = pl.close(item.id)
    assert closed.status == "Closed"
    assert closed.closed_at is not None
    assert pl.open_items() == []
    assert [i.id for i in pl.closed_items()] == [item.id]

    reopened = pl.reopen(item.id)
    assert reopened.status == "Open"
    assert reopened.closed_at is None
    assert [i.id for i in pl.open_items()] == [item.id]
    assert pl.closed_items() == []


def test_delete_removes_the_item():
    pl = _fresh_list()
    item = pl.add("Delete me")
    other = pl.add("Keep me")
    pl.delete(item.id)
    assert [i.id for i in pl.items] == [other.id]


def test_operations_on_an_unknown_id_raise_keyerror():
    pl = _fresh_list()
    with pytest.raises(KeyError):
        pl.update("nope", title="x")
    with pytest.raises(KeyError):
        pl.close("nope")
    with pytest.raises(KeyError):
        pl.reopen("nope")
    with pytest.raises(KeyError):
        pl.delete("nope")


def test_persistence_round_trip():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    pl1 = PunchList(state_file=tmp.name)
    pl1.add("Persisted item", priority="High")
    pl1.add("Second item")
    pl1.close(pl1.items[1].id)

    pl2 = PunchList(state_file=tmp.name)
    assert len(pl2.items) == 2
    assert pl2.items[0].title == "Persisted item"
    assert pl2.items[0].priority == "High"
    assert pl2.items[0].number == 1
    assert pl2.items[1].number == 2
    assert pl2.items[1].status == "Closed"
    os.unlink(tmp.name)


def test_numbering_survives_a_reload_and_keeps_counting_up():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    pl1 = PunchList(state_file=tmp.name)
    pl1.add("First")
    pl1.add("Second")

    pl2 = PunchList(state_file=tmp.name)  # simulates re-opening the page
    third = pl2.add("Third")
    assert third.number == 3
    os.unlink(tmp.name)


def test_loading_a_pre_numbering_file_migrates_items_to_sequential_numbers():
    """Items saved before #-numbering existed have no "number" key at all
    (simulates a real file written by an older version of this app)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    legacy_payload = {
        "items": [
            {
                "id": "aaaaaaaa", "title": "Older item", "description": "", "priority": "Medium",
                "status": "Open", "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00", "closed_at": None,
            },
            {
                "id": "bbbbbbbb", "title": "Newer item", "description": "", "priority": "Low",
                "status": "Open", "created_at": "2026-08-02T00:00:00+00:00",
                "updated_at": "2026-08-02T00:00:00+00:00", "closed_at": None,
            },
        ],
    }
    with open(tmp.name, "w") as f:
        json.dump(legacy_payload, f)

    pl = PunchList(state_file=tmp.name)
    by_id = {i.id: i.number for i in pl.items}
    assert by_id["aaaaaaaa"] == 1  # oldest created_at -> #1
    assert by_id["bbbbbbbb"] == 2

    # A newly-added item continues from there, not restarting at 1.
    new_item = pl.add("Brand new")
    assert new_item.number == 3

    # The migration was persisted, so re-loading doesn't renumber again.
    pl2 = PunchList(state_file=tmp.name)
    by_id2 = {i.id: i.number for i in pl2.items}
    assert by_id2["aaaaaaaa"] == 1
    assert by_id2["bbbbbbbb"] == 2
    os.unlink(tmp.name)


def test_missing_state_file_starts_empty_without_raising():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    pl = PunchList(state_file=tmp.name)
    assert pl.items == []
    assert pl.open_items() == []
    assert pl.closed_items() == []
