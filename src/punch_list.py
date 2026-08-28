"""
Lightweight punch list for tracking THIS APP'S OWN development -- ideas,
tweaks, and bugs noticed while using it day to day -- persisted to a
local JSON file the same way src/draft_state.py persists the live draft
(so it survives Streamlit's constant reruns and app restarts). Nothing
to track in a separate doc; input, edit, and close items right from the
Development page.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

VALID_PRIORITIES = ("High", "Medium", "Low")
VALID_STATUSES = ("Open", "Closed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PunchListItem:
    id: str
    title: str
    description: str = ""
    priority: str = "Medium"
    status: str = "Open"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    closed_at: Optional[str] = None


class PunchList:
    def __init__(self, state_file: str = "data/punch_list.json"):
        self.state_file = state_file
        self.items: list[PunchListItem] = []
        self._load_if_exists()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, title: str, description: str = "", priority: str = "Medium") -> PunchListItem:
        title = title.strip()
        if not title:
            raise ValueError("title is required")
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {VALID_PRIORITIES}, got {priority!r}")
        item = PunchListItem(
            id=uuid.uuid4().hex[:8], title=title, description=description.strip(), priority=priority,
        )
        self.items.append(item)
        self.save()
        return item

    def _find(self, item_id: str) -> PunchListItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(f"No punch-list item with id {item_id!r}")

    def update(
        self, item_id: str, title: Optional[str] = None, description: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> PunchListItem:
        """Only the fields passed (not None) change -- callers pass every
        field from an edit form, but this stays permissive for callers
        that just want to bump one field."""
        item = self._find(item_id)
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("title is required")
            item.title = title
        if description is not None:
            item.description = description.strip()
        if priority is not None:
            if priority not in VALID_PRIORITIES:
                raise ValueError(f"priority must be one of {VALID_PRIORITIES}, got {priority!r}")
            item.priority = priority
        item.updated_at = _now()
        self.save()
        return item

    def close(self, item_id: str) -> PunchListItem:
        item = self._find(item_id)
        item.status = "Closed"
        item.closed_at = _now()
        item.updated_at = item.closed_at
        self.save()
        return item

    def reopen(self, item_id: str) -> PunchListItem:
        item = self._find(item_id)
        item.status = "Open"
        item.closed_at = None
        item.updated_at = _now()
        self.save()
        return item

    def delete(self, item_id: str) -> None:
        item = self._find(item_id)  # raises KeyError if unknown, same as the other ops
        self.items.remove(item)
        self.save()

    def open_items(self) -> list[PunchListItem]:
        return [i for i in self.items if i.status == "Open"]

    def closed_items(self) -> list[PunchListItem]:
        return [i for i in self.items if i.status == "Closed"]

    # ------------------------------------------------------------------
    # Persistence -- same atomic write-then-replace pattern as
    # DraftState.save(), so a crash mid-write can't corrupt the file.
    # ------------------------------------------------------------------

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        payload = {"items": [asdict(i) for i in self.items]}
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, self.state_file)

    def _load_if_exists(self) -> None:
        if not os.path.exists(self.state_file) or os.path.getsize(self.state_file) == 0:
            return
        with open(self.state_file, "r") as f:
            try:
                payload = json.load(f)
            except json.JSONDecodeError:
                # Corrupt/partial file (e.g. an interrupted write) -- don't
                # crash the page, just start from an empty list.
                return
        self.items = [PunchListItem(**i) for i in payload.get("items", [])]
