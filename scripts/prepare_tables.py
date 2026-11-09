#!/usr/bin/env python3
"""Write every resource table from raw_data/derived/{us,measures}.json.

Run read_us.py and read_sources.py first. Each field is taken, per country, from
the best source read (the evidence column says which: `measured`, `modelled`
from a related measure, or `filled` from the population-weighted mean of the
subregion, then the region, then the world), and the room, floor-area and
period models are fitted here so that the C++ side only draws.

Both tiers get the same tables: they are a few rows per country.
"""
import json
import math
from collections import defaultdict

from propertygen_data import (AREAS, HOUSEHOLD_TYPES, RAW, SIBLINGS, TENURES, TYPES, normalise, read_tsv,
                              write_all_tiers)

REFERENCE_YEAR = 2023
MAX_ROOMS = 10
MAX_SIZE = 6        # rooms are conditioned on household sizes 1 to 6 (6 = 6 or more)
MAX_HH = 10         # household sizes drawn 1 to 10
GROUPS = ("house", "flat", "other")
GROUP_OF = {"detached": "house", "semi_detached": "house", "flat_small": "flat", "flat_large": "flat",
            "informal": "other", "other": "other"}
AGE_BANDS = ("16-24", "25-34", "35-44", "45-54", "55-64", "65-120")
# The informal share of urban dwellings is modelled as this fraction of SDG 11.1.1's slum share (whose
# definition also counts overcrowding and missing water or sanitation), capped; rural areas get half.
SLUM_TO_INFORMAL = 0.4
INFORMAL_CAP = 0.35
# Yearly share of the stock replaced, for the modelled period of construction, by income level: about 1%
# fits the EU census periods; shorter-lived dwellings are assumed where incomes are lower.
DEMOLITION = {"High income": 0.012, "Upper middle income": 0.02, "Lower middle income": 0.025, "Low income": 0.03}
# Where no country of the subregion is measured, the share of owners with a mortgage and of tenants
# at a reduced rent or rent-free, by income level (mortgage markets are thin at low incomes).
TENURE_SPLIT_BY_INCOME = {"Low income": {"mortgage": 0.03, "reduced": 0.25},
                          "Lower middle income": {"mortgage": 0.06, "reduced": 0.2},
                          "Upper middle income": {"mortgage": 0.15, "reduced": 0.15}}
# Odds transferred from the US are damped by this power so that one country's structure is not copied.
DAMP = 0.5
# Renting young and owning later holds widely, so the age gradient is damped less.
AGE_DAMP = 0.8
DEFAULT_NET_TO_GROSS = 0.78

US = json.loads((RAW / "derived" / "us.json").read_text(encoding="utf-8"))
SRC = json.loads((RAW / "derived" / "measures.json").read_text(encoding="utf-8"))
M = SRC["measures"]
INFO = SRC["countries"]
CG = {r["cca2"]: r for r in read_tsv(SIBLINGS / "country-generator/resources/full/countries.tsv")}
DIGITS = {r["code"]: r["digits"] for r in read_tsv(SIBLINGS / "country-generator/resources/full/currencies.tsv")}
# The currency of each country is its locale's, as occupation-generator's incomes are in it (countries.tsv
# keeps some old codes: EGP for Palestine, BGN, CUC, ZWL).
LOCALE_CURRENCY = {}
for _r in read_tsv(SIBLINGS / "country-generator/resources/full/locales.tsv"):
    LOCALE_CURRENCY.setdefault(_r["country"], _r["currency_code"])
# occupation-generator's median gross earnings, for the reference income of the cost model.
OCC_INCOME = {r["country_code"]: r for r in read_tsv(SIBLINGS / "occupation-generator/resources/full/income.tsv")}
COUNTRIES = sorted(INFO)
POP = {cc: INFO[cc]["population"] for cc in COUNTRIES}


def region_of(cc):
    return CG[cc]["region"]


def income_of(cc):
    return CG[cc].get("income_level") or "unknown"


def fill(cc, have, keys=("subregion", "region", "world")):
    """The population-weighted mean of `have` (cc -> dict of numbers) over the first group of
    countries that has any; returns (dict, group name)."""
    for key in keys:
        if key == "subregion":
            peers = [c for c in have if INFO[c]["subregion"] == INFO[cc]["subregion"] and c != cc]
        elif key == "region":
            peers = [c for c in have if region_of(c) == region_of(cc) and c != cc]
        elif key == "income":
            peers = [c for c in have if income_of(c) == income_of(cc) and c != cc]
        else:
            peers = [c for c in have if c != cc]
        if peers:
            w = sum(POP[c] for c in peers)
            out = {}
            for k in have[peers[0]]:
                out[k] = sum(POP[c] * have[c][k] for c in peers) / w
            return out, key
    raise SystemExit(f"{cc}: nothing to fill from")


# ------------------------------------------------------------------ settlement

def settlement():
    """city, town, rural shares per country. Europe's EU-SILC countries keep GHS-DUC's degree of
    urbanisation (their type tables are by it); elsewhere the rural share follows the national urban
    definition (World Bank), as census tables do, and GHS-DUC splits the urban part into city and town."""
    eu = {cc for cc in COUNTRIES if "types" in M[cc]}
    out = {}
    for cc in COUNTRIES:
        g = M[cc].get("settlement")
        u = M[cc].get("urban_share")
        if cc in ("HK", "MO", "SG", "MC", "VA"):
            out[cc] = ({"city": 1.0, "town": 0.0, "rural": 0.0}, "modelled", "city-state")
        elif g and (cc in eu or not u):
            out[cc] = ({a: g[a] for a in AREAS}, "modelled", g["source"])
        elif g and u:
            urban = u["value"]
            city_part = g["city"] / max(1e-9, g["city"] + g["town"])
            out[cc] = ({"city": urban * city_part, "town": urban * (1 - city_part), "rural": 1 - urban}, "measured",
                       f"{u['source']} {u['year']}; city and town split from GHS-DUC")
    have = {cc: v[0] for cc, v in out.items()}
    for cc in COUNTRIES:
        if cc not in out:
            d, key = fill(cc, have)
            out[cc] = (d, "filled", f"{key} mean")
    return out


# ------------------------------------------------------------------ households

def households():
    """Household types and sizes from relationship-generator's table (the UN household database)."""
    rel = {r["cca2"]: r for r in read_tsv(SIBLINGS / "relationship-generator/resources/full/households.tsv")}
    defaults = {r["subregion"]: r for r in read_tsv(SIBLINGS / "relationship-generator/resources/full/defaults.tsv")}
    out = {}
    for cc in COUNTRIES:
        r = rel.get(cc)
        evidence = "measured"
        if not r:
            r = defaults.get(INFO[cc]["subregion"]) or defaults["World"]
            evidence = "filled"
        fallback = defaults.get(INFO[cc]["subregion"]) or defaults["World"]
        if any(not r[k] for k in ("size", "one_person", "single_parent", "multi_generation")):
            evidence = "measured" if r["size"] else "filled"
        size = float(r["size"] or fallback["size"])
        op, sp, mg = (float(r[k] or fallback[k]) / 100 for k in ("one_person", "single_parent", "multi_generation"))
        rest = max(0.05, 1 - op - sp - mg)
        w, o = 0.08 * rest, 0.07 * rest
        cn = rest - w - o
        f = min(0.85, max(0.3, 0.35 + 0.15 * (size - 2.5)))
        # mean size = base + k * slope, linear in k (extra children and relatives).
        n, c = cn * f, cn * (1 - f)
        base = op + 2 * c + 3 * n + 2 * sp + 3 * w + 4.5 * mg + 2 * o
        slope = n + sp + w + 1.5 * mg + 0.5 * o
        k = min(4.0, max(0.05, (size - base) / slope))
        shares = {"one_person": op, "couple": c, "nuclear": n, "single_parent": sp, "with_parents": w,
                  "multi_generation": mg, "other": o}
        minimum = {"one_person": 1, "couple": 2, "nuclear": 3, "single_parent": 2, "with_parents": 3,
                   "multi_generation": 4, "other": 2}
        extra = {"one_person": 0, "couple": 0, "nuclear": k, "single_parent": k, "with_parents": k,
                 "multi_generation": 1.5 * k + 0.5, "other": 0.5 * k}
        types = {}
        for t in HOUSEHOLD_TYPES:
            dist = [0.0] * MAX_HH
            for j in range(MAX_HH):
                s = minimum[t] + j
                if s > MAX_HH:
                    break
                p = math.exp(-extra[t]) * extra[t] ** j / math.factorial(j) if extra[t] > 0 else (1.0 if j == 0 else 0.0)
                dist[s - 1] += p
            tail = 1 - sum(dist)
            dist[MAX_HH - 1] += max(0.0, tail)
            types[t] = (shares[t], normalise(dist))
        total = sum(s for s, _ in types.values())
        out[cc] = ({t: (s / total, d) for t, (s, d) in types.items()}, evidence,
                   f"relationship-generator households.tsv ({r.get('source', 'subregion')} {r.get('year', '')})".strip())
    return out


def size_distribution(hh):
    """P(size) for sizes 1..MAX_SIZE (the last is MAX_SIZE or more)."""
    dist = [0.0] * MAX_SIZE
    for share, sizes in hh.values():
        for i, p in enumerate(sizes):
            dist[min(i, MAX_SIZE - 1)] += share * p
    return dist


# ------------------------------------------------------------------ dwelling types

def type_odds_by_size():
    """P(type | size) / P(type) from the US, damped."""
    base = US["types"]
    out = {}
    for s in range(1, MAX_SIZE + 1):
        d = US["type_given_size"][str(s)]
        odds = {t: (d.get(t, 1e-6) / base[t]) ** DAMP if t in base else 1.0 for t in TYPES}
        odds["informal"] = odds["other"]
        out[s] = odds
    return out


def type_factors(shares, sizes, odds_size, rounds=30):
    """Per-type factors f so that drawing P(type | size) proportional to shares x odds(size) x f, over
    the country's household sizes, returns `shares` (proportional fitting). The C++ side runs the same
    loop when it loads the tables (pty::build_type_factors_)."""
    f = {k: 1.0 for k in TYPES}
    for _ in range(rounds):
        mix = {k: 0.0 for k in TYPES}
        for i, ps in enumerate(sizes):
            w = {k: shares[k] * odds_size[i + 1][k] * f[k] for k in TYPES}
            total = sum(w.values())
            if total <= 0:
                continue
            for k in TYPES:
                mix[k] += ps * w[k] / total
        for k in TYPES:
            if mix[k] > 0 and shares[k] > 0:
                f[k] *= shares[k] / mix[k]
    return f


def type_given_size(d_types, settle_shares, sizes, odds_size):
    """P(group | size) over areas, as the C++ side draws types."""
    out = {s: {g: 0.0 for g in GROUPS} for s in range(1, MAX_SIZE + 1)}
    for a in AREAS:
        pa = settle_shares[a]
        if pa <= 0:
            continue
        f = type_factors(d_types[a], sizes, odds_size)
        for s in range(1, MAX_SIZE + 1):
            w = {k: d_types[a][k] * odds_size[s][k] * f[k] for k in TYPES}
            total = sum(w.values())
            for k in TYPES:
                out[s][GROUP_OF[k]] += pa * w[k] / total
    return out


def area_odds():
    """Each area's type shares over the national ones, averaged over the EU-SILC countries (log scale)."""
    logs = defaultdict(lambda: defaultdict(list))
    for cc in COUNTRIES:
        t = M[cc].get("types")
        if not t or "all" not in t:
            continue
        for a in AREAS:
            if a in t:
                for k in TYPES:
                    if k == "informal":
                        continue
                    nat, loc = t["all"][k], t[a][k]
                    if nat > 0.005 and loc > 0:
                        logs[a][k].append(math.log(loc / nat))
    out = {}
    for a in AREAS:
        out[a] = {k: math.exp(sum(v) / len(v)) if (v := logs[a].get(k)) else 1.0 for k in TYPES}
        out[a]["informal"] = 1.0
    return out


def rake_areas(national, area_share, odds):
    """Per-area shares: national x area odds, with a per-type factor so the population mix
    across areas returns the national shares (a few rounds of proportional fitting)."""
    factor = {k: 1.0 for k in TYPES}
    for _ in range(50):
        per_area = {a: normalise([max(1e-9, national[k] * odds[a][k] * factor[k]) for k in TYPES]) for a in AREAS}
        mix = [sum(area_share[a] * per_area[a][i] for a in AREAS) for i in range(len(TYPES))]
        for i, k in enumerate(TYPES):
            if mix[i] > 0 and national[k] > 0:
                factor[k] *= national[k] / mix[i]
    return {a: dict(zip(TYPES, per_area[a])) for a in AREAS}


def informal_shares(cc):
    """(urban, rural, evidence, source) informal share, or None for countries without a slum figure."""
    census = M[cc].get("informal_census")
    if census:
        urb = census.get("urban", census.get("all"))["share"]
        rur = census.get("rural", census.get("all"))["share"]
        meta = next(iter(census.values()))
        return urb, rur, "measured", f"{meta['source']} {meta['year']}"
    comp = M[cc].get("informal_compendium")
    if comp and "urban" in comp and "rural" in comp:
        return comp["urban"]["value"], comp["rural"]["value"], "measured", f"UN compendium table 2, {comp['urban']['year']}"
    slum = M[cc].get("slum_urban")
    if slum:
        u = min(INFORMAL_CAP, SLUM_TO_INFORMAL * slum["value"])
        return u, u / 2, "modelled", f"{slum['source']} {slum['year']} x {SLUM_TO_INFORMAL}"
    return None


def census_types(cc):
    """National or per-area type shares from curated census rows; aggregates 'house' and 'flat' are
    split with the subregion's (or Europe's) inner shares."""
    rows = M[cc].get("types_census")
    if not rows:
        return None
    return rows


def dwelling_types(settle, euro_area_odds):
    measured = {}
    meta = {}
    for cc in COUNTRIES:
        t = M[cc].get("types")
        if t and all(a in t for a in AREAS):
            measured[cc] = {a: {k: t[a][k] for k in TYPES} for a in AREAS}
            meta[cc] = ("measured", f"{t['all']['source']} {t['all']['year']}")
        elif cc == "US":
            nat = {k: US["types"].get(k, 0.0) for k in TYPES}
            odds = {a: {k: 1.0 for k in TYPES} for a in AREAS}
            metro, non = US["type_by_metro"]["metro"], US["type_by_metro"]["nonmetro"]
            for k in TYPES:
                if k in nat and nat[k] > 0 and k != "informal":
                    odds["city"][k] = (metro.get(k, 1e-6) / nat[k]) * euro_area_odds["city"][k] / euro_area_odds["town"][k]
                    odds["town"][k] = metro.get(k, 1e-6) / nat[k]
                    odds["rural"][k] = non.get(k, 1e-6) / nat[k]
            measured[cc] = rake_areas(nat, settle[cc][0], odds)
            meta[cc] = ("measured", "US Census Bureau ACS 2023 PUMS (BLD) and AHS 2023 (metro status)")
    # Curated census rows: national (or per area) shares, possibly as house/flat aggregates.
    inner = {}
    for cc, d in measured.items():
        nat = {k: sum(settle[cc][0][a] * d[a][k] for a in AREAS) for k in TYPES}
        h = nat["detached"] + nat["semi_detached"]
        f = nat["flat_small"] + nat["flat_large"]
        inner[cc] = {"detached": nat["detached"] / h if h else 0.8, "flat_small": nat["flat_small"] / f if f else 0.4}
    for cc in COUNTRIES:
        rows = census_types(cc)
        if not rows or cc in measured:
            continue
        split, _ = fill(cc, inner)
        per_area = {}
        for area, row in rows.items():
            s = dict(row["shares"])
            if "house" in s:
                h = s.pop("house")
                s["detached"] = s.get("detached", 0) + h * split["detached"]
                s["semi_detached"] = s.get("semi_detached", 0) + h * (1 - split["detached"])
            if "flat" in s:
                f = s.pop("flat")
                s["flat_small"] = s.get("flat_small", 0) + f * split["flat_small"]
                s["flat_large"] = s.get("flat_large", 0) + f * (1 - split["flat_small"])
            vec = normalise([s.get(k, 0.0) for k in TYPES])
            per_area[area] = dict(zip(TYPES, vec))
        first = next(iter(rows.values()))
        if all(a in per_area for a in AREAS):
            measured[cc] = {a: per_area[a] for a in AREAS}
        elif "urban" in per_area and "rural" in per_area:
            u = per_area["urban"]
            # city and town share the urban row, tilted with Europe's city/town odds.
            odds = {"city": euro_area_odds["city"], "town": euro_area_odds["town"], "rural": {k: 1.0 for k in TYPES}}
            ct = settle[cc][0]["city"] + settle[cc][0]["town"]
            urban_split = rake_areas(u, {"city": settle[cc][0]["city"] / ct if ct else 0.5,
                                         "town": settle[cc][0]["town"] / ct if ct else 0.5, "rural": 0.0}, odds)
            measured[cc] = {"city": urban_split["city"], "town": urban_split["town"], "rural": per_area["rural"]}
        else:
            nat = per_area.get("all") or next(iter(per_area.values()))
            measured[cc] = rake_areas(nat, settle[cc][0], euro_area_odds)
        meta[cc] = (first["evidence"], f"{first['source']} {first['year']}")
    out = {}
    flat_have = {cc: {f"{a}|{k}": d[a][k] for a in AREAS for k in TYPES} for cc, d in measured.items()}
    for cc in COUNTRIES:
        if cc in measured:
            d, (evidence, source) = measured[cc], meta[cc]
        else:
            got, key = fill(cc, flat_have)
            d = {a: {k: got[f"{a}|{k}"] for k in TYPES} for a in AREAS}
            evidence, source = "filled", f"{key} mean of measured countries"
        inf = informal_shares(cc)
        census_informal = any("informal" in r["shares"] for r in (M[cc].get("types_census") or {}).values())
        is_measured_informal = (cc in measured and M[cc].get("types") is not None) or cc == "US" or census_informal
        if inf and not is_measured_informal:
            urban, rural, _, isrc = inf
            for a, share in (("city", urban), ("town", urban), ("rural", rural)):
                rest = 1 - d[a].get("informal", 0.0)
                keep = {k: d[a][k] / rest * (1 - share) if rest > 0 else 0.0 for k in TYPES if k != "informal"}
                keep["informal"] = share
                d[a] = keep
            source += f"; informal: {isrc}"
        for a in AREAS:
            vec = normalise([max(0.0, d[a][k]) for k in TYPES])
            d[a] = dict(zip(TYPES, vec))
        out[cc] = (d, evidence, source)
    return out


# ------------------------------------------------------------------ tenure

def tenure_odds():
    """Odds per age band, household type and dwelling type, relative to the overall shares.

    Age: the US's householders (ACS PUMS), damped by AGE_DAMP; the request's age is the reference
    person's, which is what a householder is. (EU-SILC's ilc_lvps05 counts persons, so a young adult
    in the parents' home counts as an owner, and it is not used.) Household type: the geometric mean
    over the EU-SILC countries, damped by DAMP. Dwelling type: the US, damped by DAMP."""
    us_all = US["tenure"]
    age = {}
    for band in AGE_BANDS:
        us = US["tenure_given_age"][band]
        age[band] = {t: (max(1e-4, us[t]) / us_all[t]) ** AGE_DAMP for t in TENURES}
    hh = {}
    for htype in HOUSEHOLD_TYPES:
        logs = {t: [] for t in TENURES}
        for cc in COUNTRIES:
            rows = M[cc].get("tenure")
            if rows and htype in rows and "all" in rows:
                for t in TENURES:
                    if rows["all"][t] > 0.01 and rows[htype][t] > 0:
                        logs[t].append(math.log(rows[htype][t] / rows["all"][t]))
        hh[htype] = {t: math.exp(DAMP * sum(v) / len(v)) if v else 1.0 for t, v in logs.items()}
    dwelling = {}
    for k in TYPES:
        src = US["tenure_given_type"].get("other" if k == "informal" else k)
        dwelling[k] = {t: (max(1e-4, src[t]) / us_all[t]) ** DAMP for t in TENURES}
    # An informal dwelling is rarely held with a mortgage.
    dwelling["informal"]["owner_mortgage"] *= 0.2
    return age, hh, dwelling


def tenures():
    rows = {}
    meta = {}
    for cc in COUNTRIES:
        t = M[cc].get("tenure")
        if t and "all" in t:
            rows[cc] = {h: {k: t[h][k] for k in TENURES} for h in t}
            meta[cc] = ("measured", f"{t['all']['source']} {t['all']['year']}")
        elif cc == "US":
            rows[cc] = {"all": {k: US["tenure"][k] for k in TENURES}}
            meta[cc] = ("measured", "US Census Bureau ACS 2023 PUMS (TEN)")
    # The split of owners into outright and mortgage, and of tenants into market and reduced, from
    # the measured countries, for sources that do not split them.
    split_have = {}
    for cc, r in rows.items():
        a = r["all"]
        o = a["owner_outright"] + a["owner_mortgage"]
        tn = a["tenant_market"] + a["tenant_reduced"]
        split_have[cc] = {"mortgage": a["owner_mortgage"] / o if o else 0.3, "reduced": a["tenant_reduced"] / tn if tn else 0.3}
    for cc in COUNTRIES:
        if cc in rows:
            continue
        census = M[cc].get("tenure_census")
        comp = M[cc].get("tenure_compendium")
        # Mortgages follow income more than geography: a peer counts only at the same income level
        # (Mexico's subregion peer is the US).
        peers = {c: v for c, v in split_have.items()
                 if INFO[c]["subregion"] == INFO[cc]["subregion"] and income_of(c) == income_of(cc)}
        if peers:
            w = sum(POP[c] for c in peers)
            split = {k: sum(POP[c] * v[k] for c, v in peers.items()) / w for k in ("mortgage", "reduced")}
        elif income_of(cc) not in TENURE_SPLIT_BY_INCOME:
            split, _ = fill(cc, split_have, ("subregion", "world"))
        else:
            split = TENURE_SPLIT_BY_INCOME[income_of(cc)]
        s = None
        if census:
            row = census.get("all") or next(iter(census.values()))
            s = dict(row["shares"])
            meta[cc] = (row["evidence"], f"{row['source']} {row['year']}")
        elif comp:
            s = {k: comp[k] for k in ("owner", "tenant_market", "tenant_reduced")}
            if s["tenant_reduced"] == 0 or s["tenant_market"] == 0:
                # one tenant category missing from the table (Mexico's rent-free, Belarus's market
                # rent): split the tenants as peers do
                s["tenant"] = s.pop("tenant_market") + s.pop("tenant_reduced")
            meta[cc] = ("measured", f"{comp['source']}, census {comp['year']}")
        if s is None:
            continue
        if "owner" in s:
            o = s.pop("owner")
            s["owner_mortgage"] = s.get("owner_mortgage", 0) + o * split["mortgage"]
            s["owner_outright"] = s.get("owner_outright", 0) + o * (1 - split["mortgage"])
        if "tenant" in s:
            tn = s.pop("tenant")
            s["tenant_reduced"] = s.get("tenant_reduced", 0) + tn * split["reduced"]
            s["tenant_market"] = s.get("tenant_market", 0) + tn * (1 - split["reduced"])
        rows[cc] = {"all": dict(zip(TENURES, normalise([s.get(k, 0.0) for k in TENURES])))}
    have = {cc: r["all"] for cc, r in rows.items()}
    out = {}
    for cc in COUNTRIES:
        if cc in rows:
            out[cc] = (rows[cc], *meta[cc])
        else:
            d, key = fill(cc, have, ("subregion", "income", "world"))
            out[cc] = ({"all": d}, "filled", f"{key} mean of measured countries")
    return out


def calibrate_tenure(cc, row, types_nat, odds_age, odds_type, age_dist, hh_odds):
    """A base row that, after the odds the C++ side applies (dwelling type, age band and, for the
    'all' row, household type), gives back `row` as the tenure shares (proportional fitting over the
    type x age x household mix, taken as independent). hh_odds: [(share, odds)], or [(1, ones)]."""
    base = dict(row)
    for _ in range(40):
        mix = {t: 0.0 for t in TENURES}
        for k, pk in types_nat.items():
            if pk <= 0:
                continue
            for band, pa in age_dist.items():
                for ph, oh in hh_odds:
                    w = [base[t] * odds_type[k][t] * odds_age[band][t] * oh[t] for t in TENURES]
                    s = sum(w)
                    if s <= 0:
                        continue
                    for t, x in zip(TENURES, w):
                        mix[t] += pk * pa * ph * x / s
        for t in TENURES:
            if mix[t] > 0 and row[t] > 0:
                base[t] *= row[t] / mix[t]
            elif row[t] == 0:
                base[t] = 0.0
    total = sum(base.values())
    return {t: base[t] / total for t in TENURES}


def calibrate_jointly(rows, target, hshares, types_nat, odds_age, odds_type, odds_hh, age_dist, rounds=40):
    """Where household types have rows of their own (EU-SILC), one factor per tenure on every row, so
    that the mix the C++ side draws (own row, else the 'all' row with the household odds, over the
    country's household types) returns the source's overall shares."""
    rows = {h: dict(r) for h, r in rows.items()}
    for _ in range(rounds):
        mix = {t: 0.0 for t in TENURES}
        for h in HOUSEHOLD_TYPES:
            ph = hshares[h][0]
            base = rows[h] if h in rows else {t: rows["all"][t] * odds_hh[h][t] for t in TENURES}
            for k, pk in types_nat.items():
                if pk <= 0:
                    continue
                for band, pa in age_dist.items():
                    w = [base[t] * odds_type[k][t] * odds_age[band][t] for t in TENURES]
                    total = sum(w)
                    if total <= 0:
                        continue
                    for t, x in zip(TENURES, w):
                        mix[t] += ph * pk * pa * x / total
        g = {t: target[t] / mix[t] if mix[t] > 0 and target[t] > 0 else (0.0 if target[t] == 0 else 1.0) for t in TENURES}
        for r in rows.values():
            for t in TENURES:
                r[t] *= g[t]
    return {h: {t: r[t] / sum(r.values()) for t in TENURES} for h, r in rows.items()}


def us_age_distribution():
    us = US["tenure_given_age"]
    # Householder age shares are not stored; a flat 18-80 draw (the library's default) weights the bands
    # by their width within 18..80.
    width = {"16-24": 7, "25-34": 10, "35-44": 10, "45-54": 10, "55-64": 10, "65-120": 16}
    total = sum(width.values())
    return {b: w / total for b, w in width.items() if b in us}


# ------------------------------------------------------------------ rooms

def room_base():
    """P(rooms | group, size) from the AHS, smoothed with the neighbouring sizes and the group's margin."""
    raw = US["rooms_given_size"]
    out = {}
    for g in GROUPS:
        margin = [0.0] * MAX_ROOMS
        for s in range(1, MAX_SIZE + 1):
            d = raw.get(f"{g}|{s}", {})
            for r in range(1, MAX_ROOMS + 1):
                margin[r - 1] += d.get(str(r), 0.0) / MAX_SIZE
        for s in range(1, MAX_SIZE + 1):
            vec = [0.0] * MAX_ROOMS
            for s2, w in ((s - 1, 0.2), (s, 0.6), (s + 1, 0.2)):
                d = raw.get(f"{g}|{s2}")
                if not d:
                    d = raw[f"{g}|{s}"]
                for r in range(1, MAX_ROOMS + 1):
                    vec[r - 1] += w * d.get(str(r), 0.0)
            vec = [0.9 * v + 0.1 * m for v, m in zip(normalise(vec), normalise(margin))]
            vec = normalise([max(v, 1e-5) for v in vec])
            # Smoothing steadies the shape of thin cells but must not move the mean: tilt it back.
            d = raw[f"{g}|{s}"]
            target = sum(int(r) * p for r, p in d.items()) / sum(d.values())
            out[(g, s)] = tilt_to_mean(vec, target)
    return out


def tilt_to_mean(dist, target):
    """dist tilted by exp(theta * r), r = 1, 2, ..., with theta chosen so the mean is target."""
    def tilted(th):
        w = [p * math.exp(th * (i + 1)) for i, p in enumerate(dist)]
        return normalise(w)

    lo, hi = -3.0, 3.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum((i + 1) * p for i, p in enumerate(tilted(mid))) < target:
            lo = mid
        else:
            hi = mid
    return tilted((lo + hi) / 2)


def bedroom_base():
    """P(bedrooms | rooms) from the AHS; a one-room home is a studio, and bedrooms stay below rooms."""
    raw = US["bedrooms_given_rooms"]
    out = {}
    for r in range(1, MAX_ROOMS + 1):
        d = raw.get(str(r), {})
        vec = [0.0] * MAX_ROOMS
        for b in range(0, r):
            vec[b] = d.get(str(b), 0.0)
        if r == 1:
            vec = [1.0] + [0.0] * (MAX_ROOMS - 1)
        out[r] = normalise([max(v, 0.0) for v in vec]) if sum(vec) > 0 else [1.0] + [0.0] * (MAX_ROOMS - 1)
    return out


def shifted(base, shift):
    """The base moved down by `shift` rooms (negative: up), between whole rooms by linear
    interpolation; what would fall below one room is one room, above the last the last."""
    n = len(base)
    lo = math.floor(shift)
    frac = shift - lo
    out = [0.0] * n
    for r, p in enumerate(base):
        out[min(max(r - lo, 0), n - 1)] += p * (1 - frac)
        out[min(max(r - lo - 1, 0), n - 1)] += p * frac
    return out


def tilt(base, theta):
    """The base shifted, then tilted by exp(theta r); theta is a number (no shift) or (theta, shift).

    1.0.0 tilted only. A tilt moves the US's shape to a smaller mean by piling homes onto one room
    (49% of Latvia's flats, against 18% of its dwellings in its census); a shift moves the shape
    whole. Over the 43 countries with a distribution, the squared error of the shares is 1.82 with a
    tilt, 0.99 with a shift and 0.34 with both."""
    th, shift = theta if isinstance(theta, tuple) else (theta, 0.0)
    if shift:
        base = shifted(base, shift)
    w = [p * math.exp(th * (r + 1)) for r, p in enumerate(base)]
    s = sum(w)
    return [x / s for x in w]


def model_rooms(theta, base, sizes, group_given_size, groups=GROUPS):
    """P(rooms) over households: sizes x groups x tilted base. theta: per group."""
    out = [0.0] * MAX_ROOMS
    for s in range(1, MAX_SIZE + 1):
        ps = sizes[s - 1]
        for g in groups:
            pg = group_given_size[s][g]
            if ps * pg <= 0:
                continue
            for r, p in enumerate(tilt(base[(g, s)], theta[g])):
                out[r] += ps * pg * p
    total = sum(out)
    return [x / total for x in out]


def to_categories(dist, keys):
    """Collapse a rooms distribution (index 0 = 1 room) into the category keys of a source: "1", "2",
    "5+" or "9+"."""
    out = {}
    for k in keys:
        if k.endswith("+"):
            lo = int(k[:-1])
            out[k] = sum(dist[lo - 1:])
        else:
            out[k] = dist[int(k) - 1] if int(k) <= MAX_ROOMS else 0.0
    return out


def dist_mean(shares):
    """The mean of a rooms distribution keyed "1", "2", ..., "k+"; an open class counts as k + 1."""
    total = mean = 0.0
    for k, v in shares.items():
        total += v
        mean += v * (int(k.rstrip("+")) + (1 if k.endswith("+") else 0))
    return mean / total


def fit_theta(objective, lo=-6.0, hi=2.0):
    best = None
    steps = 240
    for i in range(steps + 1):
        th = lo + (hi - lo) * i / steps
        e = objective(th)
        if best is None or e < best[1]:
            best = (th, e)
    th0 = best[0]
    a, b = th0 - (hi - lo) / steps, th0 + (hi - lo) / steps
    for _ in range(40):
        m1, m2 = a + (b - a) / 3, b - (b - a) / 3
        if objective(m1) < objective(m2):
            b = m2
        else:
            a = m1
    return (a + b) / 2


def sq_error(model, target):
    total = sum(target.values())
    return sum((model[k] - v / total) ** 2 for k, v in target.items())


def fit_shift_tilt(objective):
    """(theta, shift) minimising objective(theta, shift): the shift on a grid, refined once, with
    theta fitted at each."""
    def at(s):
        th = fit_theta(lambda x: objective(x, s))
        return th, s, objective(th, s)
    best = min((at(-3.0 + 0.25 * i) for i in range(37)), key=lambda v: v[2])
    best = min((at(best[1] + 0.025 * i) for i in range(-10, 11)), key=lambda v: v[2])
    return best[0], best[1]


def rooms_mean(dist):
    return sum((i + 1) * p for i, p in enumerate(dist))


def fit_rooms(cc, base, bed, sizes, group_given_size):
    """(theta, shift) per group and the evidence. Targets, best first: census room counts by
    building (Europe) and room counts for all dwellings (curated census, UN compendium), fitted with
    a shift and a tilt; then mean rooms, sleeping rooms (DHS) and rooms per person, with a shift."""
    rd = M[cc].get("rooms_dist", {})
    if cc == "US":
        return ({g: (0.0, 0.0) for g in GROUPS}, "measured",
                "US Census Bureau AHS 2023 (TOTROOMS by building and household size)")
    if "house" in rd and "flat" in rd:
        theta = {}
        for g in ("house", "flat"):
            target = rd[g]["shares"]
            keys = list(target)
            theta[g] = fit_shift_tilt(lambda th, s, g=g: sq_error(
                to_categories(model_rooms({**{x: 0.0 for x in GROUPS}, g: (th, s)}, base, sizes, group_given_size,
                                          (g,)), keys), target))
        theta["other"] = tuple((theta["house"][i] + theta["flat"][i]) / 2 for i in range(2))
        return theta, "measured", f"{rd['house']['source']} {rd['house']['year']}"
    if "all" in rd:
        # The shares and the mean, which sets the floor area too (validate_property.py checks both).
        row = rd["all"]
        shift = 1 if row.get("definition", "kitchen") == "no_kitchen" else 0
        target = {str(int(k.rstrip("+")) + shift) + ("+" if k.endswith("+") else ""): v for k, v in row["shares"].items()}
        mean = dist_mean(row["shares"]) + shift

        def objective(th, s):
            dist = model_rooms({g: (th, s) for g in GROUPS}, base, sizes, group_given_size)
            return sq_error(to_categories(dist, list(target)), target) + (rooms_mean(dist) / mean - 1) ** 2
        th, s = fit_shift_tilt(objective)
        return {g: (th, s) for g in GROUPS}, row["evidence"], f"{row['source']} {row['year']}"
    rmg = M[cc].get("rooms_mean", {})
    if "house" in rmg and "flat" in rmg:
        theta = {}
        for g in ("house", "flat"):
            row = rmg[g]
            target = row["value"] + (1 if row["definition"] == "no_kitchen" else 0)

            def objective(s, g=g, target=target):
                dist = model_rooms({**{x: 0.0 for x in GROUPS}, g: (0.0, s)}, base, sizes, group_given_size, (g,))
                return (rooms_mean(dist) - target) ** 2
            theta[g] = (0.0, fit_theta(objective, -3.0, 6.0))
        theta["other"] = tuple((theta["house"][i] + theta["flat"][i]) / 2 for i in range(2))
        return theta, rmg["house"]["evidence"], f"{rmg['house']['source']} {rmg['house']['year']} (mean rooms)"

    def common(objective):
        s = fit_theta(lambda x: objective(model_rooms({g: (0.0, x) for g in GROUPS}, base, sizes, group_given_size)),
                      -3.0, 6.0)
        return {g: (0.0, s) for g in GROUPS}
    rm = rmg.get("all")
    if rm:
        target = rm["value"] + (1 if rm["definition"] == "no_kitchen" else 0)
        return (common(lambda dist: (rooms_mean(dist) - target) ** 2), rm["evidence"],
                f"{rm['source']} {rm['year']} (mean rooms)")
    sl = M[cc].get("sleeping_rooms", {}).get("all")
    if sl:
        target = sl["shares"]

        def sleeping(dist):
            sleep = [0.0] * MAX_ROOMS
            for r, p in enumerate(dist):
                for b, q in enumerate(bed[r + 1]):
                    sleep[max(1, b) - 1] += p * q
            return sq_error(to_categories(sleep, ["1", "2", "3+"]), target)
        return common(sleeping), "modelled", f"{sl['source']} {sl['year']} (rooms for sleeping)"
    rpp = M[cc].get("rooms_per_person", {})
    if "all" in rpp:
        mean_size = sum((i + 1) * p for i, p in enumerate(sizes))
        target = rpp["all"]["value"] * mean_size
        return (common(lambda dist: (rooms_mean(dist) - target) ** 2), "modelled",
                f"{rpp['all']['source']} {rpp['all']['year']} (rooms per person)")
    return None, None, None


# ------------------------------------------------------------------ floor area

# The least spread of log floor area left for a given number of rooms, where a country's census
# spread is nearly all explained by its rooms.
MIN_M2_SD = 0.15


def rooms_by_group(theta, base, sizes, group_given_size, power):
    """Per group: its share of households, and the mean of rooms^power, the mean of log rooms and
    the variance of log rooms."""
    out = {}
    for g in GROUPS:
        weight, dist = 0.0, [0.0] * MAX_ROOMS
        for s in range(1, MAX_SIZE + 1):
            pg = sizes[s - 1] * group_given_size[s][g]
            if pg <= 0:
                continue
            weight += pg
            for r, p in enumerate(tilt(base[(g, s)], theta[g])):
                dist[r] += pg * p
        if weight <= 0:  # a group the country has none of: its rooms over the household sizes alone
            for s in range(1, MAX_SIZE + 1):
                for r, p in enumerate(tilt(base[(g, s)], theta[g])):
                    dist[r] += sizes[s - 1] * p
        total = sum(dist)
        dist = [x / total for x in dist]
        scale = sum(p * (r + 1) ** power[g] for r, p in enumerate(dist))
        mlog = sum(p * math.log(r + 1) for r, p in enumerate(dist))
        vlog = sum(p * (math.log(r + 1) - mlog) ** 2 for r, p in enumerate(dist))
        out[g] = (weight, scale, mlog, vlog)
    return out


def floor_area(cc, theta, base, sizes, group_given_size, sigma_fill=None):
    """Per group, the log floor area of one room, its log sd, the power of rooms, and the evidence.

    Floor area is rooms^power x a lognormal (1.0.0: rooms x a lognormal area per room, power 1).
    The power and the spread left at a given number of rooms are the US's, from the AHS: 0.8 for
    flats, whose rooms get smaller as they multiply, and 1.2 for houses. A census gives the mean and
    spread of the whole floor area; the level is set to its mean log, and the spread left is the
    census's less what the model's own rooms spread explains (power squared x the variance of log
    rooms), the census's capped at the US's. A country with only a mean area takes `sigma_fill`, the spread of measured countries
    near it (None asks the caller to come back with it), and the US's distance between the groups'
    mean log areas, halved."""
    us = US["m2_on_rooms"]
    power = {g: us[g]["power"] for g in GROUPS}
    fd = M[cc].get("floor_dist", {})
    rooms = rooms_by_group(theta, base, sizes, group_given_size, power)
    if cc == "US":
        return ({g: us[g]["log_one_room"] for g in GROUPS}, {g: us[g]["log_sd"] for g in GROUPS}, power,
                "measured", "US Census Bureau AHS 2023 (UNITSIZE / TOTROOMS)")
    if "house" in fd and "flat" in fd:
        mu = {g: fd[g]["log_mean"] - power[g] * rooms[g][2] for g in ("house", "flat")}
        # A census spread is capped at the US microdata's for the group: where most homes are in the
        # open top band ("150 m2 or more": 52% of Norway's houses) the fitted spread is extrapolation.
        census_sd = {g: min(fd[g]["log_sd"], us[g]["log_sd_area"]) for g in ("house", "flat")}
        sd = {g: math.sqrt(max(census_sd[g] ** 2 - power[g] ** 2 * rooms[g][3], MIN_M2_SD ** 2))
              for g in ("house", "flat")}
        # The census has houses and flats only; the other dwellings take the flats' parameters.
        mu["other"], sd["other"] = mu["flat"], sd["flat"]
        return mu, sd, {**power, "other": power["flat"]}, "measured", f"{fd['house']['source']} {fd['house']['year']}"
    fm = M[cc].get("floor_mean")
    census = M[cc].get("floor_census", {}).get("all")
    per_dwelling = None
    if census:
        if "m2_per_dwelling" in census:
            per_dwelling = census["m2_per_dwelling"]
        elif "m2_per_person" in census:
            per_dwelling = census["m2_per_person"] * sum((i + 1) * p for i, p in enumerate(sizes))
        src = (census["evidence"], f"{census['source']} {census['year']}")
    elif fm:
        per_dwelling = fm["value"]
        src = ("measured", f"{fm['source']} {fm['year']}")
    if per_dwelling:
        if sigma_fill is None:
            return "later", None, None, None, None
        # Each group's mean log area is a level plus half the US's distance from the flats'; the level
        # is solved so that the mean area per dwelling over the groups is the source's.
        offset = {g: 0.5 * (us[g]["log_mean_area"] - us["flat"]["log_mean_area"]) - power[g] * rooms[g][2]
                  for g in GROUPS}
        scale = sum(rooms[g][0] * rooms[g][1] * math.exp(offset[g] + sigma_fill[g] ** 2 / 2) for g in GROUPS)
        level = math.log(per_dwelling / scale)
        return {g: level + offset[g] for g in GROUPS}, dict(sigma_fill), power, *src
    return None, None, None, None, None


# ------------------------------------------------------------------ periods

PUMS_BANDS = None


def us_periods():
    years = {int(k): v for k, v in US["year_built"].items()}
    codes = sorted(years)
    bands = []
    for i, c in enumerate(codes):
        lo = 1900 if c == 1939 else c
        hi = codes[i + 1] - 1 if i + 1 < len(codes) else REFERENCE_YEAR
        bands.append([lo, hi, years[c]])
    return bands


def modelled_periods(growth, delta):
    """Stock by decade: new dwellings follow population growth plus replacement, then survive at 1 - delta a year."""
    pop = {1950: 1.0}
    for y in range(1950, REFERENCE_YEAR):
        pop[y + 1] = pop[y] * (1 + growth.get(y, growth.get(max(growth), 1.0)) / 100)
    built = {}
    for y in range(1950, REFERENCE_YEAR + 1):
        new = max(0.0, pop[y] - pop.get(y - 1, pop[y])) + delta * pop[y]
        built[y] = new * (1 - delta) ** (REFERENCE_YEAR - y)
    old = pop[1950] * (1 - delta) ** (REFERENCE_YEAR - 1950)
    bands = [[1900, 1949, old]]
    for lo in range(1950, REFERENCE_YEAR + 1, 10):
        hi = min(lo + 9, REFERENCE_YEAR)
        bands.append([lo, hi, sum(built[y] for y in range(lo, hi + 1))])
    total = sum(b[2] for b in bands)
    return [[lo, hi, x / total] for lo, hi, x in bands]


def periods():
    out = {}
    for cc in COUNTRIES:
        p = M[cc].get("periods")
        if p:
            out[cc] = (p["bands"], p.get("evidence", "measured"), f"{p['source']} {p['year']}")
        elif cc == "US":
            bands = us_periods()
            total = sum(b[2] for b in bands)
            out[cc] = ([[lo, hi, x / total] for lo, hi, x in bands], "measured", "US Census Bureau ACS 2023 PUMS (YRBLT)")
    for cc in COUNTRIES:
        if cc in out:
            continue
        g = M[cc].get("growth")
        if not g:
            g = M[{"XK": "RS", "VA": "IT"}.get(cc, "IT")]["growth"]
        growth = {int(k): v for k, v in g["value"].items()}
        delta = DEMOLITION.get(income_of(cc), 0.02)
        out[cc] = (modelled_periods(growth, delta), "modelled",
                   f"UN WPP 2024 population growth since 1950, {delta:.1%} of the stock replaced a year")
    return out


# ------------------------------------------------------------------ costs

def currency_of(cc):
    return LOCALE_CURRENCY.get(cc) or INFO[cc]["currency"]


def income_model():
    """How the burden falls with income, from the US (ACS PUMS): per tenure the log burden at the knot
    (the mean log income of all households) less the tenure's mean log burden, the slopes below and
    above the knot, and the ratio of the spread left around the line to the whole spread; and the knot.
    A reduced-rent tenant, whom the ACS does not ask, is taken as a market tenant."""
    b = US["burden"]
    model = {t: {"shift": b[t]["at_knot"] - b[t]["log_mean"], "below": b[t]["slope_below"],
                 "above": b[t]["slope_above"], "resid": b[t]["residual_sd"] / b[t]["log_sd"]} for t in b}
    model["tenant_reduced"] = model["tenant_market"]
    return model, b["tenant_market"]["knot"]


def reference_income(cc, x_all):
    """The income the cost model is centred on, in the country's currency: the US's mean log household
    income, scaled by the country's median earnings over the US's (occupation-generator). None where
    occupation-generator has no income for the country, or has it in another currency."""
    def earnings(r):
        return math.sqrt(float(r["median_male"]) * float(r["median_female"]))
    r = OCC_INCOME.get(cc)
    if not r or r["currency"] != currency_of(cc):
        return None
    return math.exp(x_all) * earnings(r) / earnings(OCC_INCOME["US"])


def burdens(net):
    """(log_mean, log_sd) of the burden on gross income per country and tenure."""
    have = {}
    meta = {}
    for cc in COUNTRIES:
        b = M[cc].get("burden")
        if b and all(t in b for t in TENURES):
            shift = math.log(net[cc][0])  # disposable -> gross: the cost over a larger income
            have[cc] = {f"{t}|m": b[t]["log_mean"] + shift for t in TENURES}
            have[cc].update({f"{t}|s": b[t]["log_sd"] for t in TENURES})
            meta[cc] = ("measured", f"{b['tenant_market']['source']} {b['tenant_market']['year']} (disposable income, "
                                    f"turned gross with {net[cc][0]:.2f})")
        elif cc == "US":
            u = US["burden"]
            have[cc] = {}
            for t in ("owner_outright", "owner_mortgage", "tenant_market"):
                have[cc][f"{t}|m"] = u[t]["log_mean"]
                have[cc][f"{t}|s"] = u[t]["log_sd"]
            meta[cc] = ("measured", "US Census Bureau ACS 2023 PUMS (GRPIP, OCPIP; gross income)")
    # The US has no reduced-rent figure: Europe's ratio to market rent.
    eu = [cc for cc in have if cc != "US"]
    ratio = sum(have[c]["tenant_reduced|m"] - have[c]["tenant_market|m"] for c in eu) / len(eu)
    sd = sum(have[c]["tenant_reduced|s"] for c in eu) / len(eu)
    have["US"]["tenant_reduced|m"] = have["US"]["tenant_market|m"] + ratio
    have["US"]["tenant_reduced|s"] = sd
    out = {}
    for cc in COUNTRIES:
        if cc in have:
            out[cc] = (have[cc], *meta[cc])
            continue
        d, key = fill(cc, have)
        census = M[cc].get("burden_census", {}).get("all")
        if census and "tenant_market" in census:
            # A measured market-tenant level; the other tenures keep the US's ratios to it (the US counts the
            # whole mortgage payment, EU-SILC only its interest).
            level = math.log(census["tenant_market"] * (net[cc][0] if census["basis"] == "disposable" else 1.0))
            us = have["US"]
            d = {f"{t}|m": level + us[f"{t}|m"] - us["tenant_market|m"] for t in TENURES}
            d.update({f"{t}|s": us[f"{t}|s"] for t in TENURES})
            out[cc] = (d, "modelled", f"{census['source']} {census['year']}; other tenures at the US's ratios to it")
        else:
            out[cc] = (d, "filled", f"{key} mean of measured countries")
    return out


# ------------------------------------------------------------------ write

def main():
    settle = settlement()
    hh = households()
    euro_odds = area_odds()
    types = dwelling_types(settle, euro_odds)
    odds_size = type_odds_by_size()
    odds_age, odds_hh, odds_type = tenure_odds()
    ten = tenures()
    base = room_base()
    bed = bedroom_base()
    per = periods()

    net = {}
    have_net = {cc: {"r": M[cc]["net_to_gross"]["value"]} for cc in COUNTRIES if "net_to_gross" in M[cc]}
    for cc in COUNTRIES:
        if cc in have_net:
            net[cc] = (have_net[cc]["r"], "measured")
        else:
            peers = [c for c in have_net if INFO[c]["subregion"] == INFO[cc]["subregion"]]
            net[cc] = ((sum(have_net[c]["r"] for c in peers) / len(peers)) if peers else DEFAULT_NET_TO_GROSS, "filled")
    cost = burdens(net)
    cost_model, x_all = income_model()

    rows_countries, rows_hh, rows_types, rows_ten, rows_dw, rows_per, rows_cost = [], [], [], [], [], [], []
    room_fit, area_fit = {}, {}
    for cc in COUNTRIES:
        sizes = size_distribution(hh[cc][0])
        d_types = types[cc][0]
        group_given_size = type_given_size(d_types, settle[cc][0], sizes, odds_size)
        group_given_size_cache[cc] = (sizes, group_given_size)
        theta, ev, src = fit_rooms(cc, base, bed, sizes, group_given_size)
        if theta:
            room_fit[cc] = (theta, ev, src)
    have_theta = {cc: {g: v[0][g][0] for g in GROUPS} for cc, v in room_fit.items()}
    have_shift = {cc: {g: v[0][g][1] for g in GROUPS} for cc, v in room_fit.items()}
    for cc in COUNTRIES:
        if cc not in room_fit:
            d, key = fill(cc, have_theta, ("subregion", "income", "world"))
            s, _ = fill(cc, have_shift, ("subregion", "income", "world"))
            room_fit[cc] = ({g: (d[g], s[g]) for g in GROUPS}, "filled", f"{key} mean of measured countries")
    later = []
    for cc in COUNTRIES:
        sizes, ggs = group_given_size_cache[cc]
        mu, sd, pw, ev, src = floor_area(cc, room_fit[cc][0], base, sizes, ggs)
        if mu == "later":
            later.append(cc)
        elif mu:
            area_fit[cc] = (mu, sd, pw, ev, src)
    # Spreads come from the US and the census countries; a country with only a mean takes theirs.
    have_sd = {cc: v[1] for cc, v in area_fit.items()}
    for cc in later:
        sizes, ggs = group_given_size_cache[cc]
        sigma, _ = fill(cc, have_sd, ("subregion", "income", "world"))
        area_fit[cc] = floor_area(cc, room_fit[cc][0], base, sizes, ggs, sigma)
    have_mu = {cc: v[0] for cc, v in area_fit.items()}
    have_sd = {cc: v[1] for cc, v in area_fit.items()}
    for cc in COUNTRIES:
        if cc not in area_fit:
            d, key = fill(cc, have_mu, ("subregion", "income", "world"))
            s, _ = fill(cc, have_sd, ("subregion", "income", "world"))
            pw = {g: US["m2_on_rooms"][g]["power"] for g in GROUPS}
            area_fit[cc] = (d, s, pw, "filled", f"{key} mean of measured countries")

    age_dist = us_age_distribution()
    for cc in COUNTRIES:
        info = INFO[cc]
        s, sev, ssrc = settle[cc]
        ref = reference_income(cc, x_all)
        rows_countries.append({"country_code": cc, "population": info["population"], "currency": currency_of(cc),
                               "currency_digits": DIGITS[currency_of(cc)], "subregion": info["subregion"],
                               "city": s["city"], "town": s["town"], "rural": s["rural"],
                               "net_to_gross": net[cc][0], "reference_income": round(ref) if ref else 0,
                               "area_evidence": sev})
        hshares, hev, hsrc = hh[cc]
        for t in HOUSEHOLD_TYPES:
            share, sizes = hshares[t]
            row = {"country_code": cc, "household_type": t, "share": share, "evidence": hev}
            row.update({f"size_{i + 1}": p for i, p in enumerate(sizes)})
            rows_hh.append(row)
        d, tev, tsrc = types[cc]
        for a in AREAS:
            row = {"country_code": cc, "area": a, **d[a], "evidence": tev, "source": tsrc}
            rows_types.append(row)
        trows, tnev, tnsrc = ten[cc]
        nat = {k: sum(s[a] * d[a][k] for a in AREAS) for k in TYPES}
        calibrated = {}
        for htype, row in trows.items():
            if htype != "all" and htype not in HOUSEHOLD_TYPES:
                continue
            if htype == "all":
                hh_odds = [(hshares[h][0], odds_hh[h]) for h in HOUSEHOLD_TYPES]
            else:
                hh_odds = [(1.0, {t: 1.0 for t in TENURES})]
            calibrated[htype] = calibrate_tenure(cc, row, nat, odds_age, odds_type, age_dist, hh_odds)
        if len(calibrated) > 1:
            calibrated = calibrate_jointly(calibrated, trows["all"], hshares, nat, odds_age, odds_type, odds_hh, age_dist)
        for htype in sorted(calibrated, key=lambda h: (h != "all", h)):
            rows_ten.append({"country_code": cc, "household_type": htype, **calibrated[htype], "evidence": tnev,
                             "source": tnsrc})
        theta, rev, rsrc = room_fit[cc]
        mu, sd, pw, aev, asrc = area_fit[cc]
        for g in GROUPS:
            rows_dw.append({"country_code": cc, "group": g, "rooms_tilt": theta[g][0], "rooms_shift": theta[g][1],
                            "m2_log_mean": mu[g],
                            "m2_log_sd": sd[g], "m2_rooms_power": pw[g], "rooms_evidence": rev, "area_evidence": aev,
                            "rooms_source": rsrc, "area_source": asrc})
        bands, pev, psrc = per[cc]
        for lo, hi, share in bands:
            if share > 0:
                rows_per.append({"country_code": cc, "from": lo, "to": hi, "share": share, "evidence": pev, "source": psrc})
        c, cev, csrc = cost[cc]
        for t in TENURES:
            # The measured lognormal is over all households; with a reference income it is moved to that
            # income by the US's difference for the tenure and keeps the spread the income does not explain.
            m = cost_model[t]
            if ref:
                row = {"log_mean": c[f"{t}|m"] + m["shift"], "log_sd": c[f"{t}|s"] * m["resid"],
                       "slope_below": m["below"], "slope_above": m["above"]}
            else:
                row = {"log_mean": c[f"{t}|m"], "log_sd": c[f"{t}|s"], "slope_below": 0.0, "slope_above": 0.0}
            rows_cost.append({"country_code": cc, "tenure": t, **row, "evidence": cev, "source": csrc})

    write_all_tiers("countries.tsv", "country-generator (population; the locale's currency); World Bank SP.URB.TOTL.IN.ZS and "
                    "EC JRC GHS-DUC (city, town, rural); OECD IDD (net_to_gross); reference_income: US ACS PUMS and "
                    "occupation-generator earnings (0: none)",
                    ["country_code", "population", "currency", "currency_digits", "subregion", "city", "town", "rural",
                     "net_to_gross", "reference_income", "area_evidence"], rows_countries)
    write_all_tiers("households.tsv", "relationship-generator households.tsv (UN Database on Household Size and Composition); "
                    "type shares and sizes modelled from size, one-person, single-parent and multi-generation shares",
                    ["country_code", "household_type", "share", *[f"size_{i}" for i in range(1, MAX_HH + 1)], "evidence"], rows_hh)
    write_all_tiers("types.tsv", "dwelling type shares by area; see doc/data.md",
                    ["country_code", "area", *TYPES, "evidence", "source"], rows_types)
    write_all_tiers("tenures.tsv", "tenure base shares by household type, calibrated so that the odds of tenure_odds.tsv "
                    "return the source's shares; see doc/data.md",
                    ["country_code", "household_type", *TENURES, "evidence", "source"], rows_ten)
    odds_rows = []
    for band in AGE_BANDS:
        odds_rows.append({"dimension": "age", "value": band, **odds_age[band]})
    for htype in HOUSEHOLD_TYPES:
        odds_rows.append({"dimension": "household", "value": htype, **odds_hh[htype]})
    for k in TYPES:
        odds_rows.append({"dimension": "type", "value": k, **odds_type[k]})
    write_all_tiers("tenure_odds.tsv", "odds of each tenure by age band (US ACS PUMS householders), "
                    "household type (EU-SILC ilc_lvho02) and dwelling type (US ACS PUMS), damped",
                    ["dimension", "value", *TENURES], odds_rows)
    type_rows = [{"size": s, **odds_size[s]} for s in range(1, MAX_SIZE + 1)]
    write_all_tiers("type_odds.tsv", "odds of each dwelling type by household size (US ACS 2023 PUMS, BLD by NP), damped",
                    ["size", *TYPES], type_rows)
    room_rows = []
    for g in GROUPS:
        for s in range(1, MAX_SIZE + 1):
            room_rows.append({"group": g, "size": s, **{f"r{r}": base[(g, s)][r - 1] for r in range(1, MAX_ROOMS + 1)}})
    write_all_tiers("rooms.tsv", "rooms (kitchen counted, bathrooms not) by building group and household size, US AHS 2023, "
                    "smoothed; countries tilt it (dwellings.tsv)",
                    ["group", "size", *[f"r{r}" for r in range(1, MAX_ROOMS + 1)]], room_rows, digits=8)
    bed_rows = [{"rooms": r, **{f"b{b}": bed[r][b] for b in range(MAX_ROOMS)}} for r in range(1, MAX_ROOMS + 1)]
    write_all_tiers("bedrooms.tsv", "bedrooms given rooms, US AHS 2023; one room is a studio",
                    ["rooms", *[f"b{b}" for b in range(MAX_ROOMS)]], bed_rows, digits=6)
    write_all_tiers("dwellings.tsv", "per country and building group: the rooms shift and tilt, and floor area as rooms^m2_rooms_power x a "
                    "lognormal (m2_log_mean, m2_log_sd); see doc/data.md",
                    ["country_code", "group", "rooms_tilt", "rooms_shift", "m2_log_mean", "m2_log_sd", "m2_rooms_power", "rooms_evidence", "area_evidence",
                     "rooms_source", "area_source"], rows_dw)
    write_all_tiers("periods.tsv", "occupied dwellings by period of construction; see doc/data.md",
                    ["country_code", "from", "to", "share", "evidence", "source"], rows_per)
    write_all_tiers("costs.tsv", "housing cost as a share of gross household income, lognormal by tenure at the country's "
                    "reference_income, its log moved by slope_below or slope_above x ln(income / reference_income); "
                    "see doc/data.md",
                    ["country_code", "tenure", "log_mean", "log_sd", "slope_below", "slope_above", "evidence", "source"],
                    rows_cost)
    report(types, ten, room_fit, area_fit, per, cost, hh)


group_given_size_cache = {}


def report(types, ten, room_fit, area_fit, per, cost, hh):
    total = sum(POP.values())
    print("population share by evidence:")
    for name, table, pick in (("type", types, lambda v: v[1]), ("tenure", ten, lambda v: v[1]),
                              ("rooms", room_fit, lambda v: v[1]), ("area", area_fit, lambda v: v[3]),
                              ("period", per, lambda v: v[1]), ("cost", cost, lambda v: v[1]), ("household", hh, lambda v: v[1])):
        by = defaultdict(float)
        for cc in COUNTRIES:
            by[pick(table[cc])] += POP[cc] / total
        print(f"  {name:9}", "  ".join(f"{k} {v:.1%}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
