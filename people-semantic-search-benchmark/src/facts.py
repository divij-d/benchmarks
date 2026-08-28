"""Extract every claim a provider made about a person.

A clause is graded against all of them, not one hand-picked field: providers
populate different fields, so reading a single one discards evidence unevenly.
Each claim carries the path it came from, so a verdict can be traced.

The same rules apply to every arm:

  * Current roles only. An employment entry with an end date in the past is
    past. If every entry has ended, the first listed is still offered.
  * Headlines count. Two arms expose one as a field; the third puts it under
    the name heading of the page text.
  * Labelled summary lines count, where an arm was asked to produce them.
  * Free page text is never mined for scoring. It carries past roles and
    boilerplate in equal measure, and substring-matching it would hand passes
    to whichever arm returns the most prose."""
import json
import re
from datetime import date

# "Now", for deciding whether an employment entry has ended. Taken from the
# clock rather than frozen, so a run years from now does not treat roles
# that have since ended as current. Set BENCH_TODAY=YYYY-MM-DD to pin it.
import os
TODAY = os.environ.get("BENCH_TODAY") or date.today().isoformat()


def _s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _ended(entry):
    """True only when the entry carries an end date already in the past."""
    d = entry.get("dates") or {}
    to = d.get("to") or entry.get("end_date")
    return bool(to) and str(to)[:10] < TODAY


def _add(out, path, value):
    v = _s(value)
    # Providers write these in place of null; they are absences, not claims.
    if not v or v.lower().startswith(("not publicly", "not listed", "unknown",
                                      "n/a", "not available", "not stated")):
        return
    if (path, v) not in out:
        out.append((path, v))


def _labelled(summary, label):
    """Pull 'Label: value' out of the summary Exa was asked to produce."""
    for line in (summary or "").splitlines():
        m = re.match(rf"\s*{label}\s*[:\-]\s*(.+)", line, re.I)
        if m:
            return re.sub(r"\s*\((?:[^)]*)\)\s*$", "", m.group(1)).strip(" .;")
    return None


def _exa_headline(text):
    """The line under the '# Name' heading - Exa's equivalent of a headline."""
    lines = [l.strip() for l in (text or "").splitlines()]
    for i, l in enumerate(lines):
        if l.startswith("#"):
            for nxt in lines[i + 1:i + 4]:
                if nxt and not nxt.startswith("#"):
                    return nxt
            return None
    return None


def crustdata(profile):
    roles, locs = [], []
    bp = profile.get("basic_profile") or {}
    _add(roles, "basic_profile.current_title", bp.get("current_title"))
    _add(roles, "basic_profile.headline", bp.get("headline"))
    nt = bp.get("normalized_title") or {}
    if nt.get("confident"):
        _add(roles, "basic_profile.normalized_title", nt.get("matched_title"))
    loc = bp.get("location") or {}
    for f in ("full_location", "raw", "city", "state", "country", "continent"):
        _add(locs, f"basic_profile.location.{f}", loc.get(f))
    cur = ((profile.get("experience") or {}).get("employment_details") or {}).get("current") or []
    for e in cur:
        _add(roles, "experience.current[].title", e.get("title"))
        _add(roles, "experience.current[].seniority_level", e.get("seniority_level"))
        _add(locs, "experience.current[].location", e.get("location"))
    return roles, locs


def exa(result):
    roles, locs = [], []
    ents = result.get("entities") or []
    pr = (ents[0].get("properties") if ents else {}) or {}
    _add(locs, "entity.location", pr.get("location"))
    wh = pr.get("workHistory") or []
    live = [w for w in wh if not _ended(w)] or wh[:1]
    for w in live:
        _add(roles, "workHistory.current[].title", w.get("title"))
        _add(locs, "workHistory.current[].location", w.get("location"))
    summ = result.get("summary")
    _add(roles, "summary.current_title", _labelled(summ, "Current job title"))
    _add(locs, "summary.location", _labelled(summ, "Location"))
    _add(roles, "page.headline", _exa_headline(result.get("text")))
    return roles, locs


def parallel(person):
    roles, locs = [], []
    _add(roles, "current_title", person.get("current_title"))
    _add(roles, "headline", person.get("headline"))
    _add(roles, "seniority", person.get("seniority"))
    _add(locs, "location", person.get("location"))
    return roles, locs


def _people(arm, envelope):
    """Raw per-person records, in the same order the card list is built."""
    r = envelope.get("response")
    if arm.startswith("crustdata"):
        if isinstance(r, dict):
            return r.get("profiles") or r.get("people") or []
        return r if isinstance(r, list) else []
    if arm.startswith("exa"):
        return (r or {}).get("results") or [] if isinstance(r, dict) else []
    o = (r or {}).get("output") or r
    c = o.get("content") if isinstance(o, dict) else o
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except Exception:
            return []
    if isinstance(c, dict):
        # same location parse() reads - never a first-list-wins heuristic,
        # which could pick a different list than the scorer's card parser
        ppl = c.get("people")
        return ppl if isinstance(ppl, list) else []
    return c if isinstance(c, list) else []


EXTRACT = {"crustdata": crustdata, "exa": exa, "parallel": parallel}


def claims(arm, envelope):
    """-> [{"roles": [...], "locations": [...], "tenure": [(path, years)]}] per result."""
    fam = "crustdata" if arm.startswith("crustdata") else \
          "exa" if arm.startswith("exa") else "parallel"
    fn = EXTRACT[fam]
    out = []
    for p in _people(arm, envelope):
        if not isinstance(p, dict):
            out.append({"roles": [], "locations": [], "tenure": []})
            continue
        roles, locs = fn(p)
        from src import tenure as _t
        out.append({"roles": roles, "locations": locs,
                    "tenure": _t.claims(arm, p)})
    return out
