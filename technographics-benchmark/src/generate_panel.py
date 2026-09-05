"""Regenerate the benchmark panel (data/panel/panel.json).

    python -m src.generate_panel

Provider-neutral sources only - never a benchmarked provider's own index, which
would rig coverage by construction:

  smb_software   YC directory, team size 10-50
  midsize_tech   YC directory, team size 51-500
  established    Wikidata companies with an official website and >=500
                 employees (committed snapshot: data/panel/wikidata_established.json)

Deterministic: seeded RNG, committed sources, source URL recorded per row.
Screening: domain normalisation and dedupe, benchmarked providers excluded,
BuiltWith's published Ignore List flagged (rows stay in the panel, marked
bw_ignored so the coverage denominator is stated up front). Makes no provider
API calls. The committed panel additionally carries a few hand-applied
stratum reclassifications and the removal of one defunct company, which this
script does not reproduce."""

import json
import random
import re
import sys
import urllib.request

from src.common import DATA, PANEL, ROOT, maybe_help

SEED = 42
QUOTAS = {"smb_software": 400, "midsize_tech": 260, "established": 340}
SNAPSHOT = DATA / "panel" / "wikidata_established.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# never include the benchmarked providers themselves
EXCLUDE_DOMAINS = {
    "crustdata.com", "crustdata.co", "sumble.com", "theirstack.com",
    "predictleads.com", "builtwith.com",
}

NONCOMMERCIAL = re.compile(
    r"(university|college|school|district|academy|institut|library|"
    r"\bcity of\b|county|gemeente|municipio|commune|ministry|"
    r"department of|government|fondazione|foundation|church|diocese|"
    r"charter|memorial college|public schools|colegio|ikastola|"
    r"\bisd\b|universitaria)", re.IGNORECASE)

# global TLDs plus the major query markets; Wikidata notability skews heavily
# international otherwise. A market rule, not any provider's index.
MARKET_TLD = re.compile(
    r"\.(com|co|io|ai|net|org|de|uk|fr|jp|ca|au|nl|se|dk|ch|es|it|fi|no|be|at|ie|sg|in)$")


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def norm_domain(url):
    if not url:
        return None
    d = re.sub(r"^https?://", "", url.strip().lower())
    d = d.split("/")[0].split("?")[0]
    d = re.sub(r"^www\.", "", d)
    return d if "." in d and " " not in d else None


def yc_pools():
    data = json.loads(get("https://yc-oss.github.io/api/companies/all.json"))
    smb, mid = [], []
    for c in data:
        ts, site = c.get("team_size"), norm_domain(c.get("website"))
        if not ts or not site:
            continue
        if c.get("status") and c["status"].lower() not in ("active", "public"):
            continue
        row = {"domain": site, "name": c.get("name"),
               "source": "yc-directory", "team_size_at_selection": ts,
               "source_url": f"https://www.ycombinator.com/companies/{c.get('slug', '')}"}
        if 10 <= ts <= 50:
            smb.append(row)
        elif 51 <= ts <= 500:
            mid.append(row)
    return smb, mid


def wikidata_pool():
    pool = json.loads(SNAPSHOT.read_text())
    return [r for r in pool
            if MARKET_TLD.search(r["domain"])
            and not re.search(r"\.(gov|edu|ac)(\.|$)", r["domain"])
            and not NONCOMMERCIAL.search(r["name"])
            and not re.search(r"(opera|ballet|theatre|theater|museum|orchestra)",
                              r["name"], re.IGNORECASE)]


def builtwith_ignore():
    try:
        from src.providers.builtwith import ignore_list
        return ignore_list()
    except Exception:
        return set()


def main():
    rng = random.Random(SEED)
    smb, mid = yc_pools()
    est = wikidata_pool()
    print(f"pools: yc-smb={len(smb)} yc-mid={len(mid)} wikidata={len(est)}")

    ignore = builtwith_ignore()
    panel, seen = [], set()

    def admit(row, stratum):
        d = row.get("domain")
        if d in EXCLUDE_DOMAINS or d in seen:
            return False
        seen.add(d)
        row["bw_ignored"] = d in ignore
        row["stratum"] = stratum
        panel.append(row)
        return True

    for stratum, pool in (("smb_software", smb), ("midsize_tech", mid), ("established", est)):
        rng.shuffle(pool)
        n = 0
        for row in pool:
            if n >= QUOTAS[stratum]:
                break
            if admit(dict(row), stratum):
                n += 1
        print(f"{stratum}: {n}")

    PANEL.write_text(json.dumps({
        "generated": "seeded, reproducible - see src/generate_panel.py",
        "seed": SEED,
        "note": ("bw_ignored flags BuiltWith's published Ignore List membership "
                 "(coverage denominator stated up front)."),
        "companies": panel,
    }, indent=1))
    print(f"\npanel written: {len(panel)} companies -> {PANEL.relative_to(ROOT)}")
    print(f"builtwith-ignore-flagged: {sum(1 for r in panel if r.get('bw_ignored'))}")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
