#!/usr/bin/env python3
"""Check the property tables in both tiers and print the coverage report.

Fails (exit 1) on: a missing country or area, shares that do not sum to 1, a negative share, an
unknown evidence word, a period after the reference year or overlapping another, a bedroom count
above the room count, a burden median outside 0-1, an implausible floor area per room, or lite and
full disagreeing on anything but the source texts and rounding.

Then prints, per field, the share of the served population by evidence, and with a country code
(`check_property.py JP`) each of that country's rows with their evidence and source.
"""
import math
import sys
from collections import defaultdict

from propertygen_data import RESOURCES, TYPES, TENURES, AREAS, HOUSEHOLD_TYPES

REFERENCE_YEAR = 2025
EVIDENCE = {"measured", "modelled", "filled"}
GROUPS = ("house", "flat", "other")
TOLERANCE = {"full": 2e-3, "lite": 8e-3}
problems = []


def load(tier, name):
    path = RESOURCES / tier / name
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if not line.startswith("#")]
    head = lines[0].split("\t")
    return [dict(zip(head, line.split("\t"))) for line in lines[1:] if line]


def fail(tier, name, message):
    problems.append(f"{tier}/{name}: {message}")


def sums_to_one(tier, name, key, values):
    if any(v < 0 for v in values):
        fail(tier, name, f"{key}: a negative share")
    if abs(sum(values) - 1) > TOLERANCE[tier]:
        fail(tier, name, f"{key}: shares sum to {sum(values):.4f}")


def check_evidence(tier, name, rows):
    for r in rows:
        for c, v in r.items():
            if c == "evidence" or c.endswith("_evidence"):
                if v not in EVIDENCE:
                    fail(tier, name, f"{r.get('country_code', '?')}: unknown evidence {v!r} in {c}")


def check_tier(tier):
    countries = {r["country_code"]: r for r in load(tier, "countries.tsv")}
    if len(countries) != 199:
        fail(tier, "countries.tsv", f"{len(countries)} countries, expected 199")
    for cc, r in countries.items():
        sums_to_one(tier, "countries.tsv", cc, [float(r[a]) for a in AREAS])
        if not 0.5 <= float(r["net_to_gross"]) <= 1:
            fail(tier, "countries.tsv", f"{cc}: net_to_gross {r['net_to_gross']}")
        if float(r["reference_income"]) < 0:
            fail(tier, "countries.tsv", f"{cc}: reference_income {r['reference_income']}")
    tables = {}
    for name in ("types", "tenures", "households", "dwellings", "periods", "costs", "rooms", "bedrooms",
                 "tenure_odds", "type_odds"):
        tables[name] = load(tier, f"{name}.tsv")
        check_evidence(tier, f"{name}.tsv", tables[name])

    seen = defaultdict(set)
    for r in tables["types"]:
        seen[r["country_code"]].add(r["area"])
        sums_to_one(tier, "types.tsv", f"{r['country_code']} {r['area']}", [float(r[t]) for t in TYPES])
    for cc in countries:
        if seen[cc] != set(AREAS):
            fail(tier, "types.tsv", f"{cc}: areas {sorted(seen[cc])}")

    seen = defaultdict(set)
    for r in tables["tenures"]:
        seen[r["country_code"]].add(r["household_type"])
        sums_to_one(tier, "tenures.tsv", f"{r['country_code']} {r['household_type']}", [float(r[t]) for t in TENURES])
    for cc in countries:
        if "all" not in seen[cc]:
            fail(tier, "tenures.tsv", f"{cc}: no 'all' row")

    shares = defaultdict(list)
    for r in tables["households"]:
        cc, ht = r["country_code"], r["household_type"]
        if ht not in HOUSEHOLD_TYPES:
            fail(tier, "households.tsv", f"{cc}: unknown household type {ht}")
        shares[cc].append(float(r["share"]))
        sizes = [float(r[f"size_{i}"]) for i in range(1, 11)]
        if float(r["share"]) > 0:
            sums_to_one(tier, "households.tsv", f"{cc} {ht} sizes", sizes)
        if ht == "one_person" and sizes[0] < 0.999:
            fail(tier, "households.tsv", f"{cc}: one-person households of other sizes")
    for cc in countries:
        if cc not in shares:
            fail(tier, "households.tsv", f"{cc}: missing")
        else:
            sums_to_one(tier, "households.tsv", cc, shares[cc])

    for r in tables["rooms"]:
        sums_to_one(tier, "rooms.tsv", f"{r['group']} {r['size']}", [float(r[f"r{i}"]) for i in range(1, 11)])
    for r in tables["bedrooms"]:
        rooms = int(r["rooms"])
        dist = [float(r[f"b{i}"]) for i in range(10)]
        sums_to_one(tier, "bedrooms.tsv", f"rooms {rooms}", dist)
        if any(p > 0 for b, p in enumerate(dist) if b > rooms):
            fail(tier, "bedrooms.tsv", f"rooms {rooms}: more bedrooms than rooms")

    seen = defaultdict(set)
    for r in tables["dwellings"]:
        cc, g = r["country_code"], r["group"]
        seen[cc].add(g)
        # The median area of a three-room home: m2_log_mean is the log area at one room, and area grows
        # as rooms^m2_rooms_power.
        three = math.exp(float(r["m2_log_mean"]) + float(r["m2_rooms_power"]) * math.log(3))
        if not 20 <= three <= 250:
            fail(tier, "dwellings.tsv", f"{cc} {g}: {three:.1f} m² for three rooms")
        if not 0.1 <= float(r["m2_log_sd"]) <= 1.0:
            fail(tier, "dwellings.tsv", f"{cc} {g}: m2_log_sd {r['m2_log_sd']}")
        if not -6 <= float(r["rooms_tilt"]) <= 2:
            fail(tier, "dwellings.tsv", f"{cc} {g}: rooms_tilt {r['rooms_tilt']}")
        if not -3 <= float(r["rooms_shift"]) <= 6:
            fail(tier, "dwellings.tsv", f"{cc} {g}: rooms_shift {r['rooms_shift']}")
        if not 0.5 <= float(r["m2_rooms_power"]) <= 1.5:
            fail(tier, "dwellings.tsv", f"{cc} {g}: m2_rooms_power {r['m2_rooms_power']}")
    for cc in countries:
        if seen[cc] != set(GROUPS):
            fail(tier, "dwellings.tsv", f"{cc}: groups {sorted(seen[cc])}")

    bands = defaultdict(list)
    for r in tables["periods"]:
        bands[r["country_code"]].append((int(r["from"]), int(r["to"]), float(r["share"])))
    for cc in countries:
        b = sorted(bands.get(cc, []))
        if not b:
            fail(tier, "periods.tsv", f"{cc}: missing")
            continue
        sums_to_one(tier, "periods.tsv", cc, [s for _, _, s in b])
        for (lo, hi, _), nxt in zip(b, b[1:] + [None]):
            if lo > hi or hi > REFERENCE_YEAR:
                fail(tier, "periods.tsv", f"{cc}: band {lo}-{hi}")
            if nxt and nxt[0] <= hi:
                fail(tier, "periods.tsv", f"{cc}: {lo}-{hi} overlaps {nxt[0]}-{nxt[1]}")

    seen = defaultdict(set)
    for r in tables["costs"]:
        cc = r["country_code"]
        seen[cc].add(r["tenure"])
        median = math.exp(float(r["log_mean"]))
        if not 0 < median < 1:
            fail(tier, "costs.tsv", f"{cc} {r['tenure']}: median burden {median:.3f}")
        if not 0.2 <= float(r["log_sd"]) <= 1.5:
            fail(tier, "costs.tsv", f"{cc} {r['tenure']}: log_sd {r['log_sd']}")
        for c in ("slope_below", "slope_above"):
            if not -1.5 <= float(r[c]) <= 0:
                fail(tier, "costs.tsv", f"{cc} {r['tenure']}: {c} {r[c]}")
    for cc in countries:
        if seen[cc] != set(TENURES):
            fail(tier, "costs.tsv", f"{cc}: tenures {sorted(seen[cc])}")

    for name in ("tenure_odds", "type_odds"):
        for r in tables[name]:
            for c, v in r.items():
                if c in TENURES or c in TYPES:
                    if not float(v) > 0:
                        fail(tier, f"{name}.tsv", f"{r}: an odds of {v}")
    return countries, tables


def compare_tiers(full, lite):
    """lite must equal full but for the source columns and rounding to three decimals."""
    for name, rows in full.items():
        other = lite[name]
        if len(rows) != len(other):
            fail("lite", f"{name}.tsv", f"{len(other)} rows, full has {len(rows)}")
            continue
        for a, b in zip(rows, other):
            for c, v in b.items():
                if a.get(c) is None:
                    fail("lite", f"{name}.tsv", f"column {c} not in full")
                    return
                try:
                    same = abs(float(a[c]) - float(v)) <= 6e-4
                except ValueError:
                    same = a[c] == v
                if not same:
                    fail("lite", f"{name}.tsv", f"{c}: {v} against full {a[c]}")
                    return


def coverage(countries, tables):
    pop = {cc: int(r["population"]) for cc, r in countries.items()}
    total = sum(pop.values())
    fields = {
        "type": [(r["country_code"], r["evidence"]) for r in tables["types"] if r["area"] == "city"],
        "tenure": [(r["country_code"], r["evidence"]) for r in tables["tenures"] if r["household_type"] == "all"],
        "rooms": [(r["country_code"], r["rooms_evidence"]) for r in tables["dwellings"] if r["group"] == "house"],
        "floor area": [(r["country_code"], r["area_evidence"]) for r in tables["dwellings"] if r["group"] == "house"],
        "period": list({r["country_code"]: r["evidence"] for r in tables["periods"]}.items()),
        "cost": [(r["country_code"], r["evidence"]) for r in tables["costs"] if r["tenure"] == "tenant_market"],
        "areas": [(cc, r["area_evidence"]) for cc, r in countries.items()],
    }
    print("share of the served population by evidence:")
    for field, rows in fields.items():
        by = defaultdict(int)
        for cc, ev in rows:
            by[ev] += pop[cc]
        print(f"  {field:<11}" + "  ".join(f"{ev} {by[ev] / total:6.1%}" for ev in ("measured", "modelled", "filled")))


def show(cc, tables):
    for name, rows in tables.items():
        for r in rows:
            if r.get("country_code") == cc:
                print(f"{name:<10}" + " ".join(f"{k}={v}" for k, v in r.items() if k != "country_code"))


def main():
    countries, full = check_tier("full")
    _, lite = check_tier("lite")
    compare_tiers(full, lite)
    if problems:
        print("\n".join(problems[:60]))
        print(f"{len(problems)} problems")
        raise SystemExit(1)
    print("both tiers pass")
    coverage(countries, full)
    for cc in sys.argv[1:]:
        show(cc.upper(), full)


if __name__ == "__main__":
    main()
