"""Arm-neutral role and title matching.

Judged (constraint, claim) pairs decide a verdict; the token rules below are
only a fallback for a constraint the rubric has never seen. Verdicts are keyed
on the pair, so the same claim string gets the same answer whichever arm
returned it.
"""

import json

from src.common import norm_claim
import re
from pathlib import Path

# Judged (role_constraint, title) verdicts. Keyed on the PAIR, so the same title
# gets the same verdict no matter which arm returned it - symmetric by
# construction, and the judge never saw the arm. Supersedes the token rules
# below, which stay only as a fallback for titles judged after the fact.
_ROOT = Path(__file__).resolve().parent.parent
_BASE = _ROOT / "data" / "rubric"
_JPATH = _BASE / "role_judgments.json"
_JUDGED = {}
if _JPATH.exists():
    for _role, _titles in json.loads(_JPATH.read_text()).items():
        _JUDGED[_role] = set(_titles)

# Every pair a judge ruled on, whatever the verdict. For a positive clause,
# "absent from the YES set" is a fail. For an exclusion it is not: a claim
# nobody reviewed incriminates nobody, so it must not disqualify.
_RPATH = _BASE / "reviewed_pairs.json"
_REVIEWED = set()
if _RPATH.exists():
    for _c, _v in json.loads(_RPATH.read_text()).get("role", []):
        _REVIEWED.add((_c, _v))


def exclusion_match(constraint_value, title):
    """True = compatible with the exclusion, False = disqualifies, None = unknown.

    Only a reviewed-and-rejected claim disqualifies. Everything unreviewed is
    unknown and must not block, or an arm is punished for describing a person
    in more ways than the judge happened to see.
    """
    t = norm_claim(title)
    if not t:
        return None
    yes = _JUDGED.get(constraint_value)
    if yes is None:
        return match(constraint_value, title)
    if t in yes:
        return True
    return False if (constraint_value, t) in _REVIEWED else None

# constraint value -> (any_of tokens, none_of tokens)
RULES = {
 "vp of engineering": (["vp of engineering","vice president of engineering","vp engineering","vp, engineering","svp engineering"], []),
 "founding engineer": (["founding engineer","founding ai engineer","founding software engineer","first engineer"], []),
 "head of talent acquisition": (["talent acquisition","head of talent","recruiting lead","head of recruiting","director of talent"], []),
 "product manager": (["product manager","product management","head of product","director of product","group product manager","cpo","chief product officer"], []),
 "chief information security officer": (["chief information security officer","ciso","chief security officer"], []),
 "machine learning engineer": (["machine learning engineer","ml engineer","machine learning","deep learning engineer","perception engineer"], []),
 "data engineer": (["data engineer","analytics engineer","data platform engineer"], []),
 "backend engineer": (["backend engineer","back-end engineer","back end engineer","backend developer","server engineer","platform engineer"], []),
 "ios engineer": (["ios engineer","ios developer","ios software engineer","mobile engineer, ios"], []),
 "site reliability engineer": (["site reliability","sre","infrastructure engineer","platform engineer","devops"], []),
 "developer advocate": (["developer advocate","developer relations","devrel","developer evangelist","developer experience"], []),
 "founder or company-starter now": (["founder","co-founder","cofounder","ceo","building something new","stealth"], []),
 "researcher": (["research","scientist","phd"], []),
 "sales leader": (["sales","revenue officer","cro","account executive","gtm"], []),
 "growth marketer": (["growth","marketing","demand generation","performance marketing"], []),
 "founder": (["founder","co-founder","cofounder","ceo"], []),
 "robotics perception engineer": (["perception","robotics","computer vision"], []),
 "quantitative researcher": (["quant","quantitative"], []),
 "bioinformatics scientist": (["bioinformatic","computational biolog","genomic"], []),
 "embedded systems engineer": (["embedded","firmware"], []),
 "growth lead": (["growth","marketing"], []),
 "head of ai": (["head of ai","ai lead","chief ai","vp of ai","director of ai","head of machine learning"], []),
 "engineering leader (manager or above)": (["engineering manager","head of engineering","vp of engineering","vice president of engineering","director of engineering","engineering leader","cto","chief technology officer","staff engineer","principal engineer","tech lead"], []),
 "ai engineer": (["ai engineer","machine learning engineer","ml engineer","artificial intelligence","applied scientist","llm"], []),
 "investment director": (["investment director","investment","partner","principal","venture","vc","managing director"], []),
 "design engineer bridging design and front-end": (["design engineer","front-end","frontend","ui engineer","product designer"], []),
 "operator (non-founder exec/ops)": (["coo","chief of staff","head of operations","vp operations","gm","general manager"], []),
 "not a recruiter or staffing-agency employee": ([], ["recruiter","recruiting","talent acquisition","staffing","headhunter","talent partner"]),
}

SENIOR = ["senior","sr.","sr ","staff","principal","lead","head","director","vp","chief","manager","architect"]


def match(constraint_value: str, title: str):
    """-> True / False / None (None = cannot check)

    Judged pairs win. A constraint present in role_judgments.json is fully
    enumerated over every title observed in this run, so membership is the
    verdict: in the set = pass, absent = fail. Empty titles always fail.
    """
    if constraint_value in _JUDGED:
        t = norm_claim(title)
        if not t:
            return False
        return t in _JUDGED[constraint_value]
    v = constraint_value.strip().lower()
    if v == "senior":
        if not title: return False
        t = title.lower()
        return any(s in t for s in SENIOR)
    rule = RULES.get(v)
    if rule is None:
        return None
    any_of, none_of = rule
    t = (title or "").lower()
    if none_of:
        ok = not any(n in t for n in none_of)
        if any_of:
            ok = ok and any(a in t for a in any_of)
        return ok
    if not t:
        return False
    return any(a in t for a in any_of)
