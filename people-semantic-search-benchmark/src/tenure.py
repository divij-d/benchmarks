"""Match years-of-experience clauses.

Numeric, so no judged pairs. Crustdata states a figure outright; Parallel
writes one in prose; for Exa it is derived from the earliest work-history
date, which can only understate, so no arm is credited for experience it did
not evidence."""
import json
import re
from datetime import date

import os
# Same contract as facts.py: BENCH_TODAY pins "now", else the clock. Derived
# years-of-experience shift across year boundaries, so reproducing a past
# run's tenure verdicts exactly requires pinning its date.
TODAY = (date.fromisoformat(os.environ["BENCH_TODAY"])
         if os.environ.get("BENCH_TODAY") else date.today())


def _int(s):
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else None


def parse_constraint(value):
    """'10+ years experience' -> (10, None); '6-12 years' -> (6, 12)."""
    v = str(value or "").lower()
    rng = re.search(r"(\d+)\s*[-–]\s*(\d+)", v)
    if rng:
        return int(rng.group(1)), int(rng.group(2))
    n = re.search(r"(\d+)", v)
    return (int(n.group()), None) if n else (None, None)


def claims(arm, person):
    """-> [(path, years)] every tenure figure this record supports."""
    out = []
    if arm.startswith("crustdata"):
        y = person.get("years_of_experience_raw")
        if isinstance(y, int):
            out.append(("years_of_experience_raw", y))
        elif _int(person.get("years_of_experience")) is not None:
            out.append(("years_of_experience", _int(person["years_of_experience"])))
        starts = []
        emp = ((person.get("experience") or {}).get("employment_details") or {})
        for grp in ("current", "past"):
            for e in emp.get(grp) or []:
                if e.get("start_date"):
                    starts.append(str(e["start_date"])[:4])
        if starts:
            out.append(("experience.earliest_start", TODAY.year - int(min(starts))))
    elif arm.startswith("exa"):
        ents = person.get("entities") or []
        pr = (ents[0].get("properties") if ents else {}) or {}
        starts = [str((w.get("dates") or {}).get("from"))[:4]
                  for w in (pr.get("workHistory") or [])
                  if (w.get("dates") or {}).get("from")]
        starts = [s for s in starts if s.isdigit()]
        if starts:
            out.append(("workHistory.earliest_start", TODAY.year - int(min(starts))))
    else:
        y = _int(person.get("years_experience"))
        if y is not None:
            out.append(("years_experience", y))
    return out


def match(constraint_value, years):
    """True / False / None. None only when the record supports no figure."""
    if years is None:
        return None
    lo, hi = parse_constraint(constraint_value)
    if lo is None:
        return None
    if hi is not None:
        return lo <= years <= hi
    return years >= lo
