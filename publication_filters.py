"""Exclude retired indicators from dashboard responses and public snapshots."""
from __future__ import annotations

import re

_NORTHBOUND = re.compile(r"land[-_]?connect|northbound|陆股通|北向", re.I)


def without_northbound(value):
    """Remove the indicator and its freshness entries, preserving other data."""
    if isinstance(value, dict):
        return {
            key: without_northbound(item)
            for key, item in value.items()
            if not _NORTHBOUND.search(str(key))
            and not (isinstance(item, str) and _NORTHBOUND.search(item))
        }
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str) and _NORTHBOUND.search(item):
                continue
            if isinstance(item, dict) and any(
                _NORTHBOUND.search(str(item.get(key, "")))
                for key in ("id", "key", "name", "label", "title")
            ):
                continue
            result.append(without_northbound(item))
        return result
    return value
