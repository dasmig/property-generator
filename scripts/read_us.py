#!/usr/bin/env python3
"""Read the US microdata into raw_data/derived/us.json.

Two public-domain files from the Census Bureau:
- AHS 2023 national PUF (household.csv): rooms, bedrooms, unit size, building,
  tenure, year built, household size and metro status, one record per unit.
- ACS 2023 1-year PUMS housing records (psam_hus*.csv): building, tenure,
  householder's age, household size, year built, and the rent or owner costs as
  a share of household income (GRPIP, OCPIP), and the household income (HINCP).

What it writes is used twice: as the US's own measured rows, and as the joint
structure (rooms given household size and building, bedrooms given rooms, floor
area per room, the household-size and age gradients) that other countries take
as odds around their own margins.
"""
import csv
import io
import json
import math
import zipfile
from collections import defaultdict

from propertygen_data import RAW

MAX_ROOMS = 10
MAX_SIZE = 6
SQFT_TO_M2 = 0.09290304
# AHS UNITSIZE bands, square feet (the last is open; 4,500 is its assumed middle).
UNITSIZE = {1: (0, 500), 2: (500, 750), 3: (750, 1000), 4: (1000, 1500), 5: (1500, 2000),
            6: (2000, 2500), 7: (2500, 3000), 8: (3000, 4000), 9: (4000, 5000)}


def ahs_type(bld):
    """AHS BLD: 01 mobile home, 02 one-family detached, 03 one-family attached,
    04 2 apartments, 05 3-4, 06 5-9, 07 10-19, 08 20-49, 09 50+, 10 boat/RV/van."""
    return {1: "other", 2: "detached", 3: "semi_detached", 4: "flat_small", 5: "flat_small", 6: "flat_small",
            7: "flat_large", 8: "flat_large", 9: "flat_large", 10: "other"}.get(bld)


def pums_type(bld):
    """PUMS BLD: 01 mobile home, 02 one-family detached, 03 attached, 04 2 apartments,
    05 3-4, 06 5-9, 07 10-19, 08 20-49, 09 50+, 10 boat/RV/van."""
    return ahs_type(bld)


def group_of(t):
    return {"detached": "house", "semi_detached": "house", "flat_small": "flat", "flat_large": "flat"}.get(t, "other")


def ahs_tenure(t, mortgage):
    # TENURE: 1 owned or being bought, 2 rented, 3 occupied without payment of rent.
    if t == 1:
        return "owner_mortgage" if mortgage else "owner_outright"
    if t == 2:
        return "tenant_market"
    if t == 3:
        return "tenant_reduced"
    return None


def num(s):
    s = s.strip().strip("'")
    try:
        return float(s)
    except ValueError:
        return None


def read_ahs():
    z = zipfile.ZipFile(RAW / "us" / "ahs2023.zip")
    rooms_by = defaultdict(lambda: defaultdict(float))     # (group, size) -> rooms -> weight
    bed_by_rooms = defaultdict(lambda: defaultdict(float))  # rooms -> bedrooms -> weight
    area = defaultdict(list)                                # group -> (weight, m2 per room)
    sized = defaultdict(list)                               # group -> (weight, rooms, log lo, log hi) of the band
    metro = defaultdict(lambda: defaultdict(float))         # metro? -> type -> weight
    with z.open("household.csv") as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
        for r in reader:
            w = num(r["WEIGHT"])
            people = num(r["NUMPEOPLE"])
            if not w or not people or people < 1:  # vacant or not interviewed
                continue
            t = ahs_type(int(num(r["BLD"]) or 0))
            rooms, beds = num(r["TOTROOMS"]), num(r["BEDROOMS"])
            if t is None or rooms is None or beds is None or rooms < 1 or beds < 0:
                continue
            g = group_of(t)
            rr = min(int(rooms), MAX_ROOMS)
            size = min(int(people), MAX_SIZE)
            rooms_by[(g, size)][rr] += w
            bed_by_rooms[rr][min(int(beds), rr)] += w
            unitsize = num(r["UNITSIZE"])
            if unitsize and int(unitsize) in UNITSIZE:
                lo, hi = UNITSIZE[int(unitsize)]
                # The band's geometric middle (the first band's middle is taken at 350 sq ft).
                mid = math.sqrt(max(lo, 200) * hi)
                area[g].append((w, mid * SQFT_TO_M2 / rooms))
                sized[g].append((w, rr, math.log(max(lo, 200) * SQFT_TO_M2), math.log(hi * SQFT_TO_M2)))
            cbsa = r["OMB13CBSA"].strip("'")
            metro["metro" if cbsa and cbsa != "99999" else "nonmetro"][t] += w
    return rooms_by, bed_by_rooms, area, metro, sized


def area_on_rooms(rows):
    """Floor area against rooms: the weighted least-squares line of the bands' log middles on log
    rooms. Returns the power (the slope: 0.8 for flats, whose rooms get smaller as they multiply;
    1.2 for houses), the log area of one room (the intercept) and the spread left around the line,
    which counts the variance inside a band too (uniform in log, width squared over 12)."""
    total = sum(w for w, _, _, _ in rows)
    pts = [(w, math.log(r), (lo + hi) / 2) for w, r, lo, hi in rows]
    mx = sum(w * x for w, x, _ in pts) / total
    my = sum(w * y for w, _, y in pts) / total
    sxx = sum(w * (x - mx) ** 2 for w, x, _ in pts) / total
    power = sum(w * (x - mx) * (y - my) for w, x, y in pts) / total / sxx
    resid = sum(w * (y - my - power * (x - mx)) ** 2 for w, x, y in pts) / total
    within_band = sum(w * (hi - lo) ** 2 / 12 for w, _, lo, hi in rows) / total
    spread = sum(w * (y - my) ** 2 for w, _, y in pts) / total
    return {"power": power, "log_one_room": my - power * mx, "log_sd": math.sqrt(resid + within_band),
            "log_mean_area": my, "log_sd_area": math.sqrt(spread + within_band)}


def pums_tenure(ten):
    # TEN: 1 owned with mortgage or loan, 2 owned free and clear, 3 rented, 4 occupied without rent.
    return {1: "owner_mortgage", 2: "owner_outright", 3: "tenant_market", 4: "tenant_reduced"}.get(ten)


# PUMS YRBLT: the first year of the band it codes (1939 = 1939 or earlier; single years from 2000).
def pums_year(y):
    return int(y) if y else None


def read_pums():
    z = zipfile.ZipFile(RAW / "us" / "csv_hus.zip")
    type_size = defaultdict(lambda: defaultdict(float))   # size -> type -> weight
    type_tenure = defaultdict(lambda: defaultdict(float))  # type -> tenure -> weight
    age_tenure = defaultdict(lambda: defaultdict(float))   # age band -> tenure -> weight
    tenure = defaultdict(float)
    types = defaultdict(float)
    years = defaultdict(float)
    burden = defaultdict(list)                              # tenure -> (weight, share, income)
    for name in sorted(n for n in z.namelist() if n.endswith(".csv")):
        with z.open(name) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            head = next(reader)
            ix = {c: head.index(c) for c in ("WGTP", "NP", "TYPEHUGQ", "BLD", "TEN", "HHLDRAGEP", "YRBLT", "GRPIP", "OCPIP",
                                     "HINCP", "ADJINC")}
            for row in reader:
                if row[ix["TYPEHUGQ"]] != "1":
                    continue
                np_ = row[ix["NP"]]
                if not np_ or int(np_) < 1:
                    continue
                w = float(row[ix["WGTP"]])
                t = pums_type(int(row[ix["BLD"]] or 0))
                ten = pums_tenure(int(row[ix["TEN"]] or 0))
                if t is None or ten is None:
                    continue
                size = min(int(np_), MAX_SIZE)
                type_size[size][t] += w
                type_tenure[t][ten] += w
                tenure[ten] += w
                types[t] += w
                age = row[ix["HHLDRAGEP"]]
                if age:
                    age_tenure[age_band(int(age))][ten] += w
                y = row[ix["YRBLT"]]
                if y:
                    years[int(y)] += w
                share = row[ix["GRPIP"]] if ten.startswith("tenant") else row[ix["OCPIP"]]
                income = row[ix["HINCP"]]
                if share and income and ten != "tenant_reduced":
                    income = float(income) * float(row[ix["ADJINC"]]) / 1e6  # in 2023 dollars
                    if income > 0:  # the share is not defined for no income (coded 101)
                        burden[ten].append((w, float(share) / 100, income))
    return type_size, type_tenure, age_tenure, tenure, types, years, burden


AGE_BANDS = ((16, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 120))


def age_band(age):
    for lo, hi in AGE_BANDS:
        if lo <= age <= hi:
            return f"{lo}-{hi}"
    return f"{AGE_BANDS[0][0]}-{AGE_BANDS[0][1]}"


def shares(d):
    total = sum(d.values())
    return {k: v / total for k, v in d.items()}


def weighted_quantiles(pairs, qs):
    pairs = sorted(pairs, key=lambda p: p[1])
    total = sum(w for w, _ in pairs)
    out, acc, i = [], 0.0, 0
    for q in qs:
        while i < len(pairs) and acc + pairs[i][0] < q * total:
            acc += pairs[i][0]
            i += 1
        out.append(pairs[min(i, len(pairs) - 1)][1])
    return out


def solve3(a, b):
    """x with a x = b, for a 3 x 3 system (Gaussian elimination with partial pivoting)."""
    m = [row[:] + [v] for row, v in zip(a, b)]
    for i in range(3):
        k = max(range(i, 3), key=lambda r: abs(m[r][i]))
        m[i], m[k] = m[k], m[i]
        for r in range(i + 1, 3):
            f = m[r][i] / m[i][i]
            m[r] = [x - f * y for x, y in zip(m[r], m[i])]
    x = [0.0] * 3
    for i in (2, 1, 0):
        x[i] = (m[i][3] - sum(m[i][j] * x[j] for j in range(i + 1, 3))) / m[i][i]
    return x


def burden_model(records, knot):
    """The burden's lognormal and how it falls with income. records: (weight, share, income).

    The ACS caps the share at 101%, and many households of low income are at the cap, so means of
    logs are biased there; medians and quartiles are not. So: the lognormal's median is the share's
    median and its spread the interquartile range over 1.349; how it falls with income is a line in
    log-log through the ten income deciles' medians, kinked at `knot` (the burden falls at another rate
    below it, where rent has a floor); and the spread left at a given income is the mean of the
    deciles' own interquartile spreads. The medians by income quintile are kept for
    validate_property.py."""
    def robust(part):
        q25, q50, q75 = weighted_quantiles([(w, max(x, 0.01)) for w, x, _ in part], [0.25, 0.5, 0.75])
        return math.log(q50), (math.log(q75) - math.log(q25)) / 1.349

    def groups(n):
        edges = weighted_quantiles([(w, inc) for w, _, inc in records], [i / n for i in range(1, n)])
        for lo, hi in zip([0.0] + edges, edges + [math.inf]):
            yield [(w, x, inc) for w, x, inc in records if lo < inc <= hi]

    log_mean, log_sd = robust(records)
    points, spreads = [], []
    for part in groups(10):
        x = math.log(weighted_quantiles([(w, inc) for w, _, inc in part], [0.5])[0])
        y, sd = robust(part)
        points.append((x, y))
        spreads.append(sd)
    rows = [(y, (1.0, min(0.0, x - knot), max(0.0, x - knot))) for x, y in points]
    ata = [[sum(f[i] * f[j] for _, f in rows) for j in range(3)] for i in range(3)]
    aty = [sum(y * f[i] for y, f in rows) for i in range(3)]
    at_knot, below, above = solve3(ata, aty)
    quintiles = [{"income": weighted_quantiles([(w, inc) for w, _, inc in part], [0.5])[0],
                  "burden": weighted_quantiles([(w, x) for w, x, _ in part], [0.5])[0]} for part in groups(5)]
    return {"q": weighted_quantiles([(w, x) for w, x, _ in records], [0.1, 0.25, 0.5, 0.75, 0.9]),
            "log_mean": log_mean, "log_sd": log_sd, "knot": knot, "at_knot": at_knot, "slope_below": below,
            "slope_above": above, "residual_sd": sum(spreads) / len(spreads), "by_income_quintile": quintiles}


def main():
    rooms_by, bed_by_rooms, area, metro, sized = read_ahs()
    print("AHS read")
    type_size, type_tenure, age_tenure, tenure, types, years, burden = read_pums()
    print("PUMS read")
    # The knot of the burden's line: the mean log income of the households asked about their costs.
    every = [r for v in burden.values() for r in v]
    knot = sum(w * math.log(inc) for w, _, inc in every) / sum(w for w, _, _ in every)
    out = {
        "rooms_given_size": {f"{g}|{s}": shares(d) for (g, s), d in sorted(rooms_by.items())},
        "bedrooms_given_rooms": {str(r): shares(d) for r, d in sorted(bed_by_rooms.items())},
        "m2_per_room": {g: {"median": weighted_quantiles(v, [0.5])[0],
                            "q10": weighted_quantiles(v, [0.1])[0], "q90": weighted_quantiles(v, [0.9])[0],
                            "log_mean": sum(w * math.log(x) for w, x in v) / sum(w for w, _ in v),
                            "log_sd": math.sqrt(sum(w * math.log(x) ** 2 for w, x in v) / sum(w for w, _ in v)
                                                - (sum(w * math.log(x) for w, x in v) / sum(w for w, _ in v)) ** 2)}
                        for g, v in area.items()},
        "m2_on_rooms": {g: area_on_rooms(v) for g, v in sized.items()},
        "type_by_metro": {k: shares(v) for k, v in metro.items()},
        "type_given_size": {str(s): shares(d) for s, d in sorted(type_size.items())},
        "tenure_given_type": {t: shares(d) for t, d in type_tenure.items()},
        "tenure_given_age": {a: shares(d) for a, d in sorted(age_tenure.items())},
        "tenure": shares(tenure),
        "types": shares(types),
        "year_built": {str(k): v / sum(years.values()) for k, v in sorted(years.items())},
        "burden": {t: burden_model(v, knot) for t, v in burden.items()},
    }
    path = RAW / "derived" / "us.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {path}")
    print("types", {k: round(v, 3) for k, v in out["types"].items()})
    print("tenure", {k: round(v, 3) for k, v in out["tenure"].items()})
    print("m2/room", {g: round(v["median"], 1) for g, v in out["m2_per_room"].items()})
    print("m2 on rooms", {g: {k: round(x, 3) for k, x in v.items()} for g, v in out["m2_on_rooms"].items()})
    print("burden", {t: [round(x, 3) for x in v["q"]] for t, v in out["burden"].items()})


if __name__ == "__main__":
    main()
