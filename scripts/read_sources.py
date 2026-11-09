#!/usr/bin/env python3
"""Read every per-country source into raw_data/derived/measures.json.

One entry per country and field, each with its source, year and evidence. The
national censuses typed in by hand (curated/census.tsv) come last and replace
an older or thinner source for the same field. prepare_tables.py fills the gaps
and writes the resources.

The UN compendium (needs xlrd: `.venv/Scripts/python -m pip install xlrd`) is
read only for what a newer source does not give.
"""
import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from statistics import NormalDist

from propertygen_data import AREAS, CURATED, RAW, SIBLINGS, TENURES, TYPES, eurostat, latest, read_tsv

N = NormalDist()
REFERENCE_YEAR = 2023


def countries():
    """The 199 countries finance-generator and id-generator draw from, with ISO numeric and alpha-3."""
    fin = read_tsv(SIBLINGS / "finance-generator/resources/full/countries.tsv")
    served = {r["country_code"] for r in fin if not r["territory"]}
    cg = {r["cca2"]: r for r in read_tsv(SIBLINGS / "country-generator/resources/full/countries.tsv")}
    return {cc: cg[cc] for cc in sorted(served)}


def put(m, cc, field, value, source, year, evidence="measured", key=None):
    entry = dict(value) if isinstance(value, dict) else {"value": value}
    entry.update({"source": source, "year": str(year), "evidence": evidence})
    if key is None:
        m[cc][field] = entry
    else:
        m[cc].setdefault(field, {})[key] = entry


# ---------------------------------------------------------------- Eurostat

def read_eurostat(m, served):
    eu_type = {"HOUSE_D": "detached", "HOUSE_SD": "semi_detached", "FLAT_LT10": "flat_small",
               "FLAT_GE10": "flat_large", "OTH": "other"}
    ids, v = eurostat("ilc_lvho01")
    for deg, area in (("DEG1", "city"), ("DEG2", "town"), ("DEG3", "rural"), ("TOTAL", "all")):
        got = {}
        for code, t in eu_type.items():
            for geo, (year, x) in latest(ids, v, {"rskpovth": "TOTAL", "deg_urb": deg, "building": code}).items():
                got.setdefault(geo, {})[t] = (year, x)
        for geo, d in got.items():
            if geo in served and len(d) == len(eu_type):
                year = max(y for y, _ in d.values())
                shares = {t: d[t][1] / 100 for t in d}
                shares["informal"] = 0.0
                put(m, geo, "types", shares, "Eurostat EU-SILC ilc_lvho01", year, key=area)

    # Tenure by household composition (persons, not households).
    comp = {"TOTAL": "all", "A1": "one_person", "A1_DCH": "single_parent", "A2": "couple",
            "A2_DCH1": "nuclear", "A2_DCH2": "nuclear", "A2_DCH_GE3": "nuclear",
            "A_GE3": "with_parents", "A_GE3_DCH": "multi_generation"}
    ten = {"OWN_NL": "owner_outright", "OWN_L": "owner_mortgage", "RENT_MKT": "tenant_market", "RENT_FR": "tenant_reduced"}
    ids, v = eurostat("ilc_lvho02")
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    years = {}
    for code, htype in comp.items():
        for t_code, t in ten.items():
            for geo, (year, x) in latest(ids, v, {"rskpovth": "TOTAL", "hhcomp": code, "tenure": t_code}).items():
                acc[geo][htype][t] += x
                years[geo] = max(years.get(geo, ""), year)
    for geo, by in acc.items():
        if geo not in served:
            continue
        for htype, d in by.items():
            if len(d) == 4 and sum(d.values()) > 0:
                total = sum(d.values())
                put(m, geo, "tenure", {t: d[t] / total for t in TENURES}, "Eurostat EU-SILC ilc_lvho02", years[geo], key=htype)

    # Rooms per person by building (house, flat).
    ids, v = eurostat("ilc_lvho03")
    for b, g in (("HOUSE", "house"), ("FLAT", "flat"), ("TOTAL", "all")):
        for geo, (year, x) in latest(ids, v, {"building": b, "tenure": "TOTAL"}).items():
            if geo in served:
                put(m, geo, "rooms_per_person", x, "Eurostat EU-SILC ilc_lvho03", year, key=g)

    # Average floor area (2023).
    ids, v = eurostat("ilc_lvho32")
    for geo, (year, x) in latest(ids, v, {"quant_inc": "TOTAL", "tenure": "TOTAL"}).items():
        if geo in served:
            put(m, geo, "floor_mean", x, "Eurostat EU-SILC ilc_lvho32", year)

    # Census 2021: rooms and floor area by building type, occupied and not.
    ids, v = eurostat("cens_21dwbnr_r3")
    bi, ri, ai, gi = (ids.index(k) for k in ("building", "n_room", "area", "geo"))
    rooms = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    areas = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    bgroup = {"RES1": "house", "RES2": "house", "RES_GE3": "flat"}
    for key, x in v.items():
        g = bgroup.get(key[bi])
        if not g or key[gi] not in served:
            continue
        if key[ai] == "TOTAL" and key[ri] not in ("TOTAL", "UNK"):
            rooms[key[gi]][g][key[ri]] += x
        if key[ri] == "TOTAL" and key[ai] not in ("TOTAL", "UNK"):
            areas[key[gi]][g][key[ai]] += x
    for geo, by in rooms.items():
        for g, d in by.items():
            if sum(d.values()) > 1000:
                dist = {("10" if k == "GE9" else k): x for k, x in d.items()}
                if "10" in dist:  # "9 or more" is kept as 9 and up
                    dist["9+"] = dist.pop("10")
                put(m, geo, "rooms_dist", {"shares": dist, "definition": "kitchen"}, "Eurostat census 2021 cens_21dwbnr_r3", 2021, key=g)
    # The bands are open at both ends, so a lognormal is fitted to the band counts by maximum
    # likelihood rather than to assumed band middles (1.0.0 took 180 m2 for "150 or more").
    bands = {"SQM_LT30": (None, 30), "SQM30-39": (30, 40), "SQM40-49": (40, 50), "SQM50-59": (50, 60),
             "SQM60-79": (60, 80), "SQM80-99": (80, 100), "SQM100-119": (100, 120), "SQM120-149": (120, 150),
             "SQM_GE150": (150, None)}
    for geo, by in areas.items():
        for g, d in by.items():
            if sum(d.values()) > 1000:
                mu, sd = fit_lognormal_bands([(bands[k], x) for k, x in d.items()])
                put(m, geo, "floor_dist", {"log_mean": mu, "log_sd": sd}, "Eurostat census 2021 cens_21dwbnr_r3", 2021, key=g)

    # Census 2021: occupied dwellings by period of construction.
    ids, v = eurostat("cens_21dwop_r3")
    yi, hi, gi = ids.index("y_const"), ids.index("housing"), ids.index("geo")
    periods = defaultdict(dict)
    for key, x in v.items():
        if key[hi] == "DW_OC" and key[yi] not in ("TOTAL", "UNK") and key[gi] in served:
            periods[key[gi]][key[yi]] = x
    span = {"Y_LT1919": (1850, 1918), "Y1919-1945": (1919, 1945), "Y1946-1960": (1946, 1960), "Y1961-1980": (1961, 1980),
            "Y1981-2000": (1981, 2000), "Y2001-2010": (2001, 2010), "Y2011-2015": (2011, 2015), "Y_GE2016": (2016, 2021)}
    for geo, d in periods.items():
        total = sum(d.values())
        if total > 0:
            put(m, geo, "periods", {"bands": [[*span[k], x / total] for k, x in sorted(d.items(), key=lambda kv: span[kv[0]])]},
                "Eurostat census 2021 cens_21dwop_r3", 2021)

    # Cost burden: the share of people above 25, 40, 50, 60 and 75% of disposable income, by tenure.
    ids, v = eurostat("ilc_lvho28")
    cuts = {"PC_GT25": 0.25, "PC_GT40": 0.40, "PC_GT50": 0.50, "PC_GT60": 0.60, "PC_GT75": 0.75}
    ten = {"OWN_NL": "owner_outright", "OWN_L": "owner_mortgage", "RENT_MKT": "tenant_market", "RENT_FR": "tenant_reduced"}
    for t_code, t in ten.items():
        points = defaultdict(list)
        years = {}
        for c_code, cut in cuts.items():
            for geo, (year, x) in latest(ids, v, {"tenure": t_code, "percent": c_code}).items():
                points[geo].append((cut, x / 100))
                years[geo] = year
        for geo, pts in points.items():
            fit = fit_lognormal_tail(pts)
            # The tail alone cannot pin the spread when few people pass 25%: then the US spread for the
            # tenure is kept and only the level is fitted.
            if not fit or not 0.45 <= fit[1] <= 1.1:
                fit = fit_lognormal_level(pts, US_SIGMA[t])
            if geo in served and fit:
                put(m, geo, "burden", {"log_mean": fit[0], "log_sd": fit[1], "basis": "disposable"},
                    "Eurostat EU-SILC ilc_lvho28", years[geo], key=t)



US_SIGMA = {"owner_outright": 0.93, "owner_mortgage": 0.69, "tenant_market": 0.71, "tenant_reduced": 0.92}


def fit_lognormal_bands(counts):
    """mu, sigma of a lognormal fitted by maximum likelihood to counts in bands ((lo, hi), count); None
    for an open end. A grid search refined three times: deterministic, and the likelihood is smooth."""
    def loglik(mu, sd):
        total = 0.0
        for (lo, hi), n in counts:
            if n <= 0:
                continue
            a = N.cdf((math.log(lo) - mu) / sd) if lo else 0.0
            b = N.cdf((math.log(hi) - mu) / sd) if hi else 1.0
            total += n * math.log(max(b - a, 1e-300))
        return total
    mu, sd, step_mu, step_sd = 4.3, 0.4, 0.2, 0.1
    for _ in range(4):
        grid = [(mu + i * step_mu, max(0.02, sd + j * step_sd)) for i in range(-10, 11) for j in range(-10, 11)]
        mu, sd = max(grid, key=lambda p: loglik(*p))
        step_mu, step_sd = step_mu / 10, step_sd / 10
    return mu, sd


def fit_lognormal_level(points, sigma):
    """mu of a lognormal with a given sigma through exceedance points, by least squares on the probit scale."""
    pts = [(math.log(cut), N.inv_cdf(1 - p)) for cut, p in points if 0.001 < p < 0.999]
    if not pts:
        return None
    return sum(x - y * sigma for x, y in pts) / len(pts), sigma


def fit_lognormal_tail(points):
    """mu, sigma of a lognormal through exceedance points (threshold, share above), by least squares
    on the probit scale; None when fewer than two usable points."""
    xs, ys = [], []
    for cut, p in points:
        if 0.002 < p < 0.998:
            xs.append(math.log(cut))
            ys.append(N.inv_cdf(1 - p))
    if len(xs) < 2:
        if len(xs) == 1:  # one point: the US's spread for that tenure is assumed by the caller
            return None
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    if slope <= 0.3:
        return None
    sigma = 1 / slope
    mu = mx - my * sigma
    return mu, sigma


# ---------------------------------------------------------------- DHS

def read_dhs(m, served):
    iso = {r["DHS_CountryCode"]: r["ISO2_CountryCode"]
           for r in json.loads((RAW / "dhs" / "countries.json").read_text(encoding="utf-8"))["Data"]}
    rows = json.loads((RAW / "dhs" / "national.json").read_text(encoding="utf-8"))["Data"]
    rows += json.loads((RAW / "dhs" / "breakdown.json").read_text(encoding="utf-8"))["Data"]
    best = {}
    for r in rows:
        cc = iso.get(r["DHS_CountryCode"])
        if cc not in served or not r["IsPreferred"]:
            continue
        if best.get(cc, (0, ""))[0] < r["SurveyYear"]:
            best[cc] = (r["SurveyYear"], r["SurveyId"])
    data = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        cc = iso.get(r["DHS_CountryCode"])
        if cc not in best or r["SurveyId"] != best[cc][1]:
            continue
        cat, label = r["CharacteristicCategory"], r["CharacteristicLabel"]
        if cat == "Total":
            key = "all"
        elif cat == "Residence":
            key = label.lower()
        elif cat == "Household usual members":
            key = "size:" + label
        else:
            continue
        data[cc][key][r["IndicatorId"]] = r["Value"]
    for cc, by in data.items():
        year, survey = best[cc]
        for key, d in by.items():
            if all(k in d for k in ("HC_RMSL_H_1RM", "HC_RMSL_H_2RM", "HC_RMSL_H_3RM")):
                put(m, cc, "sleeping_rooms", {"shares": {"1": d["HC_RMSL_H_1RM"], "2": d["HC_RMSL_H_2RM"], "3+": d["HC_RMSL_H_3RM"]},
                                              "persons_per_room": d.get("HC_PPRM_H_MNP")},
                    f"DHS Program {survey}", year, key=key)


# ---------------------------------------------------------------- UN compendium

def compendium_blocks(table):
    """(country name, year, area, [(label, total, share)]) blocks from a compendium table."""
    import xlrd
    sh = xlrd.open_workbook(str(RAW / "un" / f"compendium_table{table}.xls")).sheet_by_index(0)
    pct_col = 9 if table in ("03", "15") else None
    out, country, year, block = [], None, None, None
    for r in range(7, sh.nrows):
        label = str(sh.cell_value(r, 0)).strip().replace("\xa0", " ")
        total = sh.cell_value(r, 1)
        if not label:
            continue
        if re.fullmatch(r"(19|20)\d\d(\.0)?", label):
            year = label[:4]
            continue
        if total in ("", None) and not re.fullmatch(r"[A-Z -]+", label):
            country = re.sub(r"\d+$", "", label.split(" - ")[0]).strip()
            continue
        if total in ("", None):
            continue
        area = {"Total": "all", "Urban - Urbaine": "urban", "Rural - Rurale": "rural"}.get(re.sub(r"\d+$", "", label))
        if area:
            block = (country, year, area, [])
            out.append(block)
            continue
        if block is None or block[0] != country:
            continue
        if re.search(r"\s(19|20)\d\d$", label):  # a city, not a category
            block = None
            continue
        share = sh.cell_value(r, pct_col) if pct_col else None
        block[3].append((label, total, share))
    return out


def name_index(served):
    idx = {}
    for cc, r in served.items():
        idx[r["name_common"].lower()] = cc
        idx[r["name_official"].lower()] = cc
    idx.update({"china, hong kong sar": None, "republic of korea": "KR", "russian federation": "RU",
                "iran (islamic republic of)": "IR", "venezuela (bolivarian republic of)": "VE",
                "bolivia (plurinational state of)": "BO", "united republic of tanzania": "TZ",
                "republic of moldova": "MD", "viet nam": "VN", "côte d'ivoire": "CI", "cote d'ivoire": "CI",
                "the former yugoslav republic of macedonia": "MK", "syrian arab republic": "SY",
                "lao people's democratic republic": "LA", "occupied palestinian territory": "PS",
                "state of palestine": "PS", "united kingdom of great britain and northern ireland": "GB",
                "united states of america": "US", "micronesia (federated states of)": "FM",
                "saint vincent and the grenadines": "VC", "saint kitts and nevis": "KN", "saint lucia": "LC",
                "cabo verde": "CV", "cape verde": "CV", "sao tome and principe": "ST", "kyrgyzstan": "KG",
                "democratic republic of the congo": "CD", "congo": "CG", "czech republic": "CZ", "brunei darussalam": "BN",
                "turks and caicos islands": None, "china, macao sar": None, "bahamas": "BS", "gambia": "GM", "swaziland": "SZ", "turkey": "TR"})
    return idx


def read_compendium(m, served):
    try:
        import xlrd  # noqa: F401
    except ImportError:
        print("xlrd missing: the UN compendium is skipped")
        return
    idx = name_index(served)
    unmatched = set()

    def cc_of(name):
        key = name.lower()
        if key in idx:
            return idx[key]
        unmatched.add(name)
        return None

    # Table 15: tenure. Owner, renter, free of rent, other; "other" over 20% makes the row unusable.
    for country, year, area, cats in compendium_blocks("15"):
        cc = cc_of(country)
        if not cc or area != "all":
            continue
        got = defaultdict(float)
        for label, total, share in cats:
            if not isinstance(share, float):
                continue
            low = label.lower()
            if "free" in low:
                key = "tenant_reduced"
            elif " ow" in low or low.startswith("owner"):
                key = "owner"
            elif " re" in low or "rent" in low:
                key = "tenant_market"
            elif "other" in low:
                key = "other"
            else:
                key = None
            if key:
                got[key] += share
        known = got["owner"] + got["tenant_market"] + got["tenant_reduced"]
        if known > 50 and got["other"] < 20:
            put(m, cc, "tenure_compendium", {k: got[k] / known for k in ("owner", "tenant_market", "tenant_reduced")},
                "UN Compendium of Housing Statistics 2011, table 15", year, evidence="measured")

    # Table 3: rooms of occupied housing units.
    for country, year, area, cats in compendium_blocks("03"):
        cc = cc_of(country)
        if not cc or area not in ("all",):
            continue
        dist, open_end = {}, None
        rank = 0
        unknown = 0.0
        for label, total, share in cats:
            if label.startswith("Unknown"):
                unknown += share if isinstance(share, float) else 0.0
                continue
            if not isinstance(share, float):
                continue
            rank += 1
            if "+" in label:
                open_end = rank
                dist[f"{rank}+"] = share
                break
            dist[str(rank)] = share
        # A block whose categories and unknowns do not add up to the total is misprinted (Nicaragua 2005:
        # 84% one-room dwellings, 90% accounted for); it is not used.
        if rank >= 4 and sum(dist.values()) + unknown >= 98:
            put(m, cc, "rooms_dist", {"shares": dist, "definition": "kitchen"},
                "UN Compendium of Housing Statistics 2011, table 3", year, key="all")

    # Table 2: share of housing units that are not conventional dwellings (semi-permanent, mobile, informal).
    for country, year, area, cats in compendium_blocks("02"):
        pass  # the compendium table 2 rows carry numbers per column, read below
    import xlrd
    sh = xlrd.open_workbook(str(RAW / "un" / "compendium_table02.xls")).sheet_by_index(0)
    country = year = None
    for r in range(7, sh.nrows):
        label = str(sh.cell_value(r, 0)).strip().replace("\xa0", " ")
        if re.fullmatch(r"(19|20)\d\d(\.0)?", label):
            year = label[:4]
            continue
        if sh.cell_value(r, 1) in ("", None):
            if label and not re.fullmatch(r"[A-Z -]+", label):
                country = re.sub(r"\d+$", "", label.split(" - ")[0]).strip()
            continue
        area = {"Total": "all", "Urban - Urbaine": "urban", "Rural - Rurale": "rural"}.get(re.sub(r"\d+$", "", label))
        if not area:
            continue
        total, semi, informal = (sh.cell_value(r, c) for c in (1, 9, 13))  # total, semi-permanent, informal
        if not isinstance(total, float) or total <= 0 or not (isinstance(semi, float) or isinstance(informal, float)):
            continue
        semi = semi if isinstance(semi, float) else 0.0
        informal = informal if isinstance(informal, float) else 0.0
        cc = cc_of(country)
        if cc:
            put(m, cc, "informal_compendium", (semi + informal) / total,
                "UN Compendium of Housing Statistics 2011, table 2", year, key=area)
    if unmatched:
        print("compendium names not matched:", "; ".join(sorted(unmatched)[:60]))


# ---------------------------------------------------------------- SDG, GHSL, World Bank, OECD, WPP

def read_global(m, served):
    by_num = {str(int(r["ccn3"])): cc for cc, r in served.items() if r["ccn3"].isdigit()}
    by_a3 = {r["cca3"]: cc for cc, r in served.items()}

    slum = json.loads((RAW / "un" / "sdg_slum.json").read_text(encoding="utf-8"))["data"]
    best = {}
    for r in slum:
        cc = by_num.get(r["geoAreaCode"])
        if cc and r["value"] not in (None, "", "NaN") and r["dimensions"].get("Location") == "URBAN":
            year = int(r["timePeriodStart"])
            if year >= best.get(cc, (0, 0))[0]:
                best[cc] = (year, float(r["value"]) / 100)
    for cc, (year, x) in best.items():
        put(m, cc, "slum_urban", x, "UN SDG 11.1.1 EN_LND_SLUM (UN-Habitat)", year)

    z = zipfile.ZipFile(RAW / "ghsl" / "duc.zip")
    shares = {}
    for epoch in (2020, 2025):
        text = z.read(f"GHS_DUC_GLOBE_R2023A_V2_0_GADM41_{epoch}_level0.csv").decode("utf-8", "replace")
        for r in csv.DictReader(io.StringIO(text)):
            cc = by_a3.get(r["GID_0"])
            if cc:
                shares.setdefault(cc, {})[epoch] = (float(r["UCentre_share"]), float(r["UCluster_share"]), float(r["Rural_share"]))
    for cc, d in shares.items():
        if 2020 in d and 2025 in d:
            f = (REFERENCE_YEAR - 2020) / 5
            city, town, rural = (a + (b - a) * f for a, b in zip(d[2020], d[2025]))
            total = city + town + rural
            put(m, cc, "settlement", {"city": city / total, "town": town / total, "rural": rural / total},
                "EC JRC GHS-DUC R2023A (degree of urbanisation), 2020-2025 interpolated", REFERENCE_YEAR, evidence="modelled")

    wb = json.loads((RAW / "wb" / "urban.json").read_text(encoding="utf-8"))[1]
    for r in wb:
        cc = by_a3.get(r["countryiso3code"])
        if cc and r["value"] is not None:
            put(m, cc, "urban_share", r["value"] / 100, "World Bank SP.URB.TOTL.IN.ZS (UN WUP)", r["date"])

    rows = list(csv.DictReader(io.StringIO((RAW / "oecd" / "idd.csv").read_text(encoding="utf-8"))))

    def pick(measure):
        out = {}
        for r in rows:
            if (r["MEASURE"] == measure and r["STATISTICAL_OPERATION"] == "MEAN" and r["AGE"] == "_T"
                    and r["DEFINITION"] == "D_CUR" and r["UNIT_MEASURE"] == "XDC_HH_EQ" and r["OBS_VALUE"]):
                out[(r["REF_AREA"], r["TIME_PERIOD"])] = float(r["OBS_VALUE"])
        return out
    disp, tax = pick("INC_DISP"), pick("TAC")
    best = {}
    for (a3, y), t in tax.items():
        cc = by_a3.get(a3)
        if cc and (a3, y) in disp and y >= best.get(cc, ("0",))[0]:
            best[cc] = (y, disp[(a3, y)] / (disp[(a3, y)] + abs(t)))
    for cc, (y, ratio) in best.items():
        put(m, cc, "net_to_gross", ratio, "OECD Income Distribution Database (INC_DISP, TAC)", y)

    growth = {}
    for r in csv.DictReader(io.StringIO((RAW / "wpp" / "growthrate.txt").read_text(encoding="utf-8")), delimiter="\t"):
        cc = by_num.get(r["country_code"])
        if cc:
            growth[cc] = {int(k): float(v) for k, v in r.items() if k.isdigit() and v not in ("", "NA")}
    for cc, g in growth.items():
        m[cc]["growth"] = {"value": g, "source": "UN WPP 2024 (growth rate)", "year": "2023", "evidence": "measured"}


# ---------------------------------------------------------------- curated national tables

def read_curated(m, served):
    sources = [p for p in (RAW / "derived" / "national.tsv", CURATED / "census.tsv") if p.exists()]
    groups = defaultdict(list)
    for r in (row for p in sources for row in read_tsv(p)):
        if r["country_code"] not in served:
            raise SystemExit(f"census.tsv: unknown country {r['country_code']}")
        groups[(r["country_code"], r["field"], r["area"] or "all")].append(r)
    for (cc, field, area), rows in groups.items():
        meta = rows[0]
        values = {r["key"]: float(r["value"]) for r in rows}
        info = {"source": meta["source"], "year": meta["year"], "evidence": meta["evidence"] or "measured"}
        if field == "types":
            m[cc].setdefault("types_census", {})[area] = {"shares": values, **info}
        elif field == "tenure":
            m[cc].setdefault("tenure_census", {})[area] = {"shares": values, **info}
        elif field == "rooms":
            m[cc].setdefault("rooms_dist", {})[area] = {"shares": values, "definition": meta["definition"] or "kitchen", **info}
        elif field == "rooms_mean":
            m[cc].setdefault("rooms_mean", {})[area] = {"value": values["rooms"], "definition": meta["definition"] or "kitchen", **info}
        elif field == "sleeping_rooms":
            m[cc].setdefault("sleeping_rooms", {})[area] = {"shares": values, **info}
        elif field == "floor":
            m[cc].setdefault("floor_census", {})[area] = {**values, **info}
        elif field == "periods":
            bands = []
            for k, x in values.items():
                lo, hi = k.split("-")
                bands.append([int(lo), int(hi), x])
            total = sum(b[2] for b in bands)
            m[cc]["periods"] = {"bands": [[lo, hi, x / total] for lo, hi, x in sorted(bands)], **info}
        elif field == "burden":
            m[cc].setdefault("burden_census", {})[area] = {**values, "basis": meta["definition"] or "gross", **info}
        elif field == "informal":
            m[cc].setdefault("informal_census", {})[area] = {**values, **info}
        else:
            raise SystemExit(f"census.tsv: unknown field {field}")


def main():
    served = countries()
    m = defaultdict(dict)
    read_eurostat(m, served)
    print("Eurostat read")
    read_dhs(m, served)
    print("DHS read")
    read_compendium(m, served)
    print("compendium read")
    read_global(m, served)
    print("SDG, GHSL, World Bank, OECD, WPP read")
    read_curated(m, served)
    out = {"countries": {cc: {"population": int(r["population"]), "currency": r["currency_code"].split(",")[0].strip(),
                              "subregion": r["subregion"], "name": r["name_common"]} for cc, r in served.items()},
           "measures": {cc: m[cc] for cc in sorted(served)}}
    path = RAW / "derived" / "measures.json"
    path.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    count = defaultdict(int)
    for cc in served:
        for f in m[cc]:
            count[f] += 1
    print(f"wrote {path}")
    print(" ".join(f"{k}:{v}" for k, v in sorted(count.items())))


if __name__ == "__main__":
    main()
