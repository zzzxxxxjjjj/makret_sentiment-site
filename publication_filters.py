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

_PCR_RETIRED = re.compile(r"^pcr-(?:amount|volume)(?:-|$)")
def position_pcr_only(value):
    """Retire trade PCR from publication; preserve raw saved inputs and model history."""
    if isinstance(value,list):
        return [position_pcr_only(item) for item in value
                if not (isinstance(item,dict) and _PCR_RETIRED.match(str(item.get("id",item.get("key","")))))
                and not (isinstance(item,str) and _PCR_RETIRED.match(item))]
    if isinstance(value,dict):
        result={key:position_pcr_only(item) for key,item in value.items()}
        if isinstance(result.get("entries"),list) and "dailyCount" in result:
            daily=[e for e in result["entries"] if e.get("frequency")=="daily"]
            lagging=[e for e in daily if not e.get("current")]
            result.update(dailyCount=len(daily),currentDailyCount=len(daily)-len(lagging),
                          laggingDaily=lagging,allDailyCurrent=bool(daily) and not lagging)
        return result
    return value
