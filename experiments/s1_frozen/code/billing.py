"""Strict append-only call accounting; unknown billing is never guessed as zero."""

import json
import math
from pathlib import Path
from core import IntegrityError


def inspect_journal(path, *, allow_missing=False):
    path = Path(path)
    if not path.exists():
        if not allow_missing:
            raise IntegrityError("Required billing journal missing")
        return {"known_cost_usd": 0.0, "started": 0, "finished": 0, "pending": []}
    calls, cost, finished = {}, 0.0, 0
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
            key = event["id"]
            if not isinstance(key, str) or not key:
                raise ValueError("Invalid call ID")
            if event["state"] == "started":
                if key in calls:
                    raise ValueError("Duplicate call start")
                calls[key] = {"start": event, "end": None}
            elif event["state"] == "finished":
                if key not in calls or calls[key]["end"] is not None:
                    raise ValueError("Missing start or duplicate finish")
                value = event["cost_usd"]
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("Invalid billing value")
                calls[key]["end"] = event
                cost += value
                finished += 1
            else:
                raise ValueError("Unknown journal state")
        except (ValueError, KeyError, TypeError) as error:
            raise IntegrityError("Invalid billing journal: " + str(error)) from error
    return {
        "known_cost_usd": cost,
        "started": len(calls),
        "finished": finished,
        "pending": [value["start"] for value in calls.values() if value["end"] is None],
    }
