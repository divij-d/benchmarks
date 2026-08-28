"""Arm-neutral location matching.

Every arm returns a free-text location string and the same matcher runs over
all of them. Nothing here consults a vendor's structured fields, so no arm gets
a verification path the others lack.
"""

import json

from src.common import norm_claim
from pathlib import Path

# Judged (location constraint, place) verdicts - same design as roles.py.
# Keyed on the PAIR, graded once, blind to which arm produced it. Supersedes
# the substring table below, which stays only as a fallback.
_ROOT = Path(__file__).resolve().parent.parent
_BASE = _ROOT / "data" / "rubric"
_JPATH = _BASE / "location_judgments.json"
_JUDGED = {}
if _JPATH.exists():
    for _c, _places in json.loads(_JPATH.read_text()).items():
        _JUDGED[_c] = set(_places)

EU = ["united kingdom","england","scotland","wales","ireland","france","germany",
      "spain","portugal","italy","netherlands","belgium","luxembourg","switzerland",
      "austria","denmark","sweden","norway","finland","iceland","poland","czech",
      "czechia","slovakia","hungary","romania","bulgaria","greece","croatia",
      "slovenia","serbia","estonia","latvia","lithuania","ukraine","turkey","malta",
      "cyprus","europe"]
LATAM = ["brazil","brasil","mexico","argentina","chile","colombia","peru","uruguay",
         "paraguay","bolivia","ecuador","venezuela","costa rica","panama","guatemala",
         "honduras","nicaragua","el salvador","dominican republic","latin america",
         "latam"]
BAY = ["san francisco","bay area","oakland","palo alto","mountain view","san jose",
       "berkeley","menlo park","sunnyvale","redwood city","santa clara","cupertino",
       "san mateo","daly city","emeryville","foster city","burlingame","fremont"]

# constraint value -> accepted substrings (all lowercase)
RULES = {
 "new york": ["new york","nyc","brooklyn","manhattan","queens","bronx"],
 "new york city": ["new york","nyc","brooklyn","manhattan","queens","bronx"],
 "san francisco": BAY,
 "san francisco bay area": BAY,
 "united states": ["united states","usa"," us",", us"],
 "boston": ["boston","cambridge, massachusetts","somerville","massachusetts"],
 "germany": ["germany","deutschland","berlin","munich","münchen","hamburg","cologne","frankfurt","stuttgart"],
 "singapore": ["singapore"],
 "united kingdom": ["united kingdom","england","scotland","wales","london","cambridge, england","oxford"],
 "india": ["india"],
 "china": ["china","beijing","shanghai","shenzhen","hangzhou","guangzhou","hong kong"],
 "europe": EU,
 "latin america": LATAM,
 "bangalore / bengaluru": ["bangalore","bengaluru"],
}


def match(constraint_value: str, location: str):
    """-> True / False / None (None = cannot check)

    Judged pairs win. A constraint present in location_judgments.json is fully
    enumerated over every place string observed in this run, so membership is
    the verdict. Empty locations always fail.
    """
    checkable = (constraint_value in _JUDGED
                 or constraint_value.strip().lower() in RULES)
    if not checkable:
        return None          # unknown constraint stays unknown, empty or not
    if location is None or str(location).strip() == "":
        return False
    if constraint_value in _JUDGED:
        return norm_claim(location) in _JUDGED[constraint_value]
    rules = RULES.get(constraint_value.strip().lower())
    loc = str(location).lower()
    return any(r in loc for r in rules)
