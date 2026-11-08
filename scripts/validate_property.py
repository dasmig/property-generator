#!/usr/bin/env python3
"""Compare the generator's margins with the sources (doc/data.md, "How well it matches").

Builds scripts/sample_property.cpp, draws --count homes per country from a tier and compares:
- dwelling types with types.tsv over the country's areas (checks the sampling and the size odds' fit);
- tenure with the source's shares before calibration (checks the calibration);
- mean rooms with the source's mean or distribution (+1 room where the source leaves the kitchen out);
- mean floor area with the source's mean per dwelling;
- mean year built with periods.tsv; median burden per tenure, at the country's reference income, with
  costs.tsv (as a multiple of the allowed sampling error, so 1.0 is the limit);
- and the US's joint structure and burden by income against the microdata (check_joint).

Usage, from the library root (the national readers need the venv):
    .venv/Scripts/python scripts/validate_property.py [--tier full] [--count 20000] [--cxx clang++]
Exits 1 when a check fails for more than its allowed share of countries.
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_tables as P  # noqa: E402
from propertygen_data import read_tsv, TYPES, TENURES, AREAS  # noqa: E402


def build_and_sample(tier, count, cxx):
    exe = ROOT / "build" / ("sample_property.exe" if sys.platform == "win32" else "sample_property")
    exe.parent.mkdir(exist_ok=True)
    subprocess.run([cxx, "-std=c++23", "-O2", "-I", str(ROOT), "-o", str(exe), str(ROOT / "scripts" / "sample_property.cpp")],
                   check=True)
    out = ROOT / "build" / f"sample_property_{tier}.tsv"
    subprocess.run([str(exe), str(ROOT / "resources" / tier), str(count), str(out)], check=True)
    return {r["country"]: {k: (float(v) if k != "country" else v) for k, v in r.items()} for r in read_tsv(out)}


def rooms_target(cc):
    """The source's mean rooms with the kitchen, or None. Only for countries whose rooms were fitted to
    one national figure: Europe's are fitted per building to the census distributions, which the
    sample reproduces by construction, and a rooms-per-person figure uses another definition."""
    m = P.M[cc]
    if "house" in m.get("rooms_dist", {}):
        return None, None
    rm = m.get("rooms_mean", {}).get("all")
    if rm:
        return rm["value"] + (1 if rm["definition"] == "no_kitchen" else 0), "rooms_mean"
    rd = m.get("rooms_dist", {}).get("all")
    if rd:
        return P.dist_mean(rd["shares"]) + (1 if rd.get("definition") == "no_kitchen" else 0), "rooms_dist"
    return None, None


def floor_target(cc):
    """The source's mean floor area per dwelling where the fit used it (not Europe's census bands)."""
    m = P.M[cc]
    if "house" in m.get("floor_dist", {}):
        return None
    census = m.get("floor_census", {}).get("all")
    if census and "m2_per_dwelling" in census:
        return census["m2_per_dwelling"]
    fm = m.get("floor_mean")
    if fm:
        return fm["value"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="full")
    ap.add_argument("--count", type=int, default=20000)
    ap.add_argument("--cxx", default="clang++")
    args = ap.parse_args()
    sample = build_and_sample(args.tier, args.count, args.cxx)
    res = ROOT / "resources" / args.tier
    countries = {r["country_code"]: r for r in read_tsv(res / "countries.tsv")}
    types = {(r["country_code"], r["area"]): r for r in read_tsv(res / "types.tsv")}
    costs = {(r["country_code"], r["tenure"]): float(r["log_mean"]) for r in read_tsv(res / "costs.tsv")}
    sds = {(r["country_code"], r["tenure"]): float(r["log_sd"]) for r in read_tsv(res / "costs.tsv")}
    periods = {}
    for r in read_tsv(res / "periods.tsv"):
        periods.setdefault(r["country_code"], []).append((int(r["from"]), int(r["to"]), float(r["share"])))
    margins = P.tenures()

    checks = {"type": [], "tenure": [], "rooms": [], "floor": [], "year": [], "burden": []}
    for cc, s in sample.items():
        c = countries[cc]
        nat = {k: sum(float(c[a]) * float(types[(cc, a)][k]) for a in AREAS) for k in TYPES}
        checks["type"].append((cc, max(abs(s[f"t_{k}"] - nat[k]) for k in TYPES)))
        src = margins[cc][0]["all"]
        checks["tenure"].append((cc, max(abs(s[f"h_{t}"] - src[t]) for t in TENURES)))
        target, how = rooms_target(cc)
        if target:
            checks["rooms"].append((cc, abs(s["rooms_mean"] / target - 1), f"{s['rooms_mean']:.2f} vs {target:.2f} ({how})"))
        ft = floor_target(cc)
        if ft:
            checks["floor"].append((cc, abs(s["floor_mean"] / ft - 1), f"{s['floor_mean']:.0f} vs {ft:.0f} m²"))
        bands = periods[cc]
        total = sum(sh for lo, hi, sh in bands if lo <= P.REFERENCE_YEAR)
        year = sum(sh * (lo + min(hi, P.REFERENCE_YEAR)) / 2 for lo, hi, sh in bands if lo <= P.REFERENCE_YEAR) / total
        checks["year"].append((cc, abs(s["year_mean"] - year), f"{s['year_mean']:.1f} vs {year:.1f}"))
        # A median's relative sampling error is about 1.25 sigma / sqrt(n); the check allows 3 of them.
        worst = 0.0
        for t in TENURES:
            n = s[f"h_{t}"] * args.count
            if n >= 100:
                allowed_error = 0.01 + 3 * 1.2533 * sds[(cc, t)] / math.sqrt(n)
                worst = max(worst, abs(s[f"b_{t}"] / math.exp(costs[(cc, t)]) - 1) / allowed_error)
        checks["burden"].append((cc, worst))

    # Tolerances: sampling error at 20,000 draws, plus the model's stated approximations.
    tolerance = {"type": 0.015, "tenure": 0.03, "rooms": 0.10, "floor": 0.15, "year": 1.5, "burden": 1.0}
    allowed = {"type": 0.0, "tenure": 0.05, "rooms": 0.2, "floor": 0.25, "year": 0.0, "burden": 0.0}
    failed = False
    for name, rows in checks.items():
        bad = [r for r in rows if r[1] > tolerance[name]]
        share = len(bad) / len(rows) if rows else 0.0
        flag = "FAIL" if share > allowed[name] else "ok"
        failed |= flag == "FAIL"
        print(f"{name:<7} {len(rows):>3} countries, {len(rows) - len(bad):>3} within {tolerance[name]} ({flag})")
        for r in sorted(bad, key=lambda r: -r[1])[:8]:
            print(f"    {r[0]} {r[1]:.3f} " + (r[2] if len(r) > 2 else ""))
    failed |= check_joint(args)
    raise SystemExit(1 if failed else 0)


def check_joint(args):
    """The US's joint structure against the microdata it came from (ACS PUMS, AHS).

    Other countries take the US's odds damped by DAMP, so the US is drawn with those damped odds too:
    the check is that the generated gradient points the same way as the microdata's and keeps about
    DAMP of it, measured as the slope of the generated log-odds on the microdata's (each cell's
    log P(value | given) / P(value)), weighted by the cell's share. Rooms by size compare means.
    """
    exe = ROOT / "build" / ("sample_property.exe" if sys.platform == "win32" else "sample_property")
    out = ROOT / "build" / f"sample_joint_{args.tier}.tsv"
    subprocess.run([str(exe), str(ROOT / "resources" / args.tier), str(args.count * 10), str(out), "--joint", "US"],
                   check=True)
    gen = {}
    for r in read_tsv(out):
        gen.setdefault(r["table"], {}).setdefault(r["given"], {})[r["value"]] = float(r["share"])
    with open(ROOT / "raw_data" / "derived" / "us.json", encoding="utf-8") as f:
        us = json.load(f)

    failed = False
    print("US joint structure against the microdata (slope of the generated log-odds on the microdata's)")
    for table in ("tenure_given_type", "tenure_given_age", "type_given_size"):
        src, got = us[table], gen[table]
        margin_src, margin_got = {}, {}
        for given, dist in src.items():
            for v, p in dist.items():
                margin_src[v] = margin_src.get(v, 0) + p / len(src)
        for given, dist in got.items():
            for v, p in dist.items():
                margin_got[v] = margin_got.get(v, 0) + p / len(got)
        xs, ys, ws = [], [], []
        for given, dist in src.items():
            for v, p in dist.items():
                q = got.get(given, {}).get(v, 0)
                if p > 0.005 and q > 0.005:
                    xs.append(math.log(p / margin_src[v]))
                    ys.append(math.log(q / margin_got[v]))
                    ws.append(p)
        mx = sum(w * x for w, x in zip(ws, xs)) / sum(ws)
        my = sum(w * y for w, y in zip(ws, ys)) / sum(ws)
        slope = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys)) / sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
        damp = P.AGE_DAMP if table == "tenure_given_age" else P.DAMP
        ok = 0.6 * damp <= slope <= 1.2
        failed |= not ok
        print(f"  {table:<18} slope {slope:.2f} over {len(xs)} cells, damped by {damp} ({'ok' if ok else 'FAIL'})")
    worst = 0.0
    for key, dist in us["rooms_given_size"].items():
        mean_src = sum(int(k) * p for k, p in dist.items()) / sum(dist.values())
        g = gen["rooms_given_size"].get(key)
        if g:
            mean_got = sum(int(k) * p for k, p in g.items())
            worst = max(worst, abs(mean_got / mean_src - 1))
    ok = worst <= 0.05
    failed |= not ok
    print(f"  {'rooms_given_size':<18} worst mean off by {worst:.1%} ({'ok' if ok else 'FAIL'})")

    # The median burden at a given income, against the PUMS medians by income quintile (interpolated on
    # log income, within the quintiles' range). The model is a line in log-log; the tolerance is its fit.
    worst, cells = 0.0, 0
    for key, dist in gen["burden_given_income"].items():
        tenure, income = key.split("|")
        q = us["burden"][tenure]["by_income_quintile"]
        x = math.log(float(income))
        pts = [(math.log(p["income"]), math.log(p["burden"])) for p in q]
        if not pts[0][0] <= x <= pts[-1][0]:
            continue
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                target = math.exp(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
        worst = max(worst, abs(dist["median"] / target - 1))
        cells += 1
    ok = worst <= 0.15
    failed |= not ok
    print(f"  {'burden_given_income':<18} worst median off by {worst:.1%} over {cells} cells ({'ok' if ok else 'FAIL'})")
    return failed


if __name__ == "__main__":
    main()
