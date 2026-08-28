"""Arm-neutral employer matching.

`company` is one of the four fields every arm returns, so an employer clause is
checkable on the same footing as role and location. Employer names are exact
enough that normalised comparison decides the verdict - no judged table.
"""
import re


def _norm(s):
    # Some providers append provenance to the company field in parentheses.
    # Strip any parenthetical before normalising, so an annotation habit
    # cannot decide a match.
    s = re.sub(r"\s*\([^)]*\)", " ", str(s or ""))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|sa|ag|bv|plc|pte|pvt)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match(constraint_value, company):
    if not company:
        return False
    a, b = _norm(constraint_value), _norm(company)
    if not a or not b:
        return None
    return a == b or a in b.split() or b.startswith(a + " ") or b == a
