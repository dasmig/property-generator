#!/usr/bin/env python3
"""Turn downloaded national census tables into rows of raw_data/derived/national.tsv.

The rows have the columns of curated/census.tsv (hand-typed figures from
reports that cannot be read by script); read_sources.py reads both. One
function per country; each says which table gives what and how its categories
map onto the library's.
"""
import sys
from collections import defaultdict

from propertygen_data import RAW

COLUMNS = ["country_code", "field", "area", "key", "value", "year", "source", "evidence", "definition"]
rows = []


def add(cc, field, area, values, year, source, definition=""):
    for key, value in values.items():
        rows.append({"country_code": cc, "field": field, "area": area, "key": key, "value": f"{value:.6g}",
                     "year": str(year), "source": source, "evidence": "measured", "definition": definition})


def xls_row(path, first_cell):
    """The numeric cells of the first row whose first cell, without spaces, equals `first_cell`."""
    import xlrd
    sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
    for r in range(sh.nrows):
        if str(sh.cell_value(r, 0)).replace(" ", "").replace("　", "") == first_cell:
            return [sh.cell_value(r, c) for c in range(1, sh.ncols)]
    raise SystemExit(f"{path}: no row {first_cell!r}")


def china():
    """China, 2020 census long form (10% of households), NBS yearbook tables 9-1 to 9-4, family
    households; suffixes a, b, c are city (城市), town (镇) and rural (乡村).

    Type: 9-1 gives storeys and structure, not house against flat. A house is taken as the larger of
    single-storey (平房) and self-built (自建住房, table 9-4) households: rural self-built homes are
    often two or three storeys. The rest are flats in buildings of four or more storeys, nearly all
    with ten or more dwellings, so flat_large. Bamboo, straw or adobe structures (竹草土坯) are informal.
    Rooms: 间数 counts rooms without the kitchen. Floor area: 建筑面积, the gross building area.
    """
    d = RAW / "census" / "cn"
    src = "NBS China, 2020 census yearbook"
    for suffix, area in (("a", "city"), ("b", "town"), ("c", "rural")):
        t1 = xls_row(d / f"B0901{suffix}.xls", "全国")
        t4 = xls_row(d / f"B0904{suffix}.xls", "全国")
        total = t1[0]
        single, informal = t1[1] / total, t1[8] / total
        self_built = t4[7] / t4[0]
        house = max(single, self_built)
        add("CN", "types", area, {"detached": house - informal * (house > informal), "flat_large": 1 - house,
                                   "informal": informal}, 2020, f"{src} tables 9-1{suffix}, 9-4{suffix}")
    t4 = xls_row(d / "B0904.xls", "全国")
    total, public, rent, *owned, other = t4
    add("CN", "tenure", "all", {"tenant_reduced": public, "tenant_market": rent, "owner": sum(owned)}, 2020,
        f"{src} table 9-4 (other sources left out)")
    t2 = xls_row(d / "B0902.xls", "全国")
    households, rooms, area_m2 = t2[0], t2[1], t2[2]
    add("CN", "rooms_mean", "all", {"rooms": rooms / households}, 2020, f"{src} table 9-2", "no_kitchen")
    add("CN", "floor", "all", {"m2_per_dwelling": area_m2 / households}, 2020, f"{src} table 9-2 (gross building area)")
    bands = ["1900-1948", "1949-1959", "1960-1969", "1970-1979", "1980-1989", "1990-1999", "2000-2009", "2010-2014", "2015-2020"]
    add("CN", "periods", "all", {b: t2[3 + 3 * i] for i, b in enumerate(bands)}, 2020, f"{src} table 9-2")


def median_from_bands(bands):
    """The median of grouped counts [(low, high, count)], linear within the band."""
    total = sum(c for _, _, c in bands)
    acc = 0.0
    for lo, hi, c in bands:
        if acc + c >= total / 2:
            return lo + (total / 2 - acc) / c * (hi - lo)
        acc += c
    return bands[-1][1]


def china_burden():
    """Tenant burden from table 9-5 (monthly rent bands of renting family households) against the
    2020 urban median disposable income per person, 40,378 yuan (NBS, 2020 income and consumption
    release, 18 January 2021), times the 2020 census's mean family household size, 2.62."""
    t5 = xls_row(RAW / "census" / "cn" / "B0905.xls", "全国")
    edges = [0, 200, 500, 1000, 2000, 3000, 4000, 6000, 8000, 10000, 15000]
    rent = median_from_bands([(edges[i], edges[i + 1], c) for i, c in enumerate(t5[1:11])])
    income = 40378 * 2.62 / 12
    add("CN", "burden", "all", {"tenant_market": rent / income}, 2020,
        "NBS China, 2020 census table 9-5 (median rent) over the 2020 urban median disposable income", "disposable")


def xlsx_rows(path):
    import openpyxl
    ws = openpyxl.load_workbook(str(path), data_only=True).worksheets[0]
    return [[c for c in row if c is not None] for row in ws.iter_rows(values_only=True)]


def find(rows, *labels):
    """The numbers of the first row holding every label, in order of appearance."""
    for row in rows:
        text = [str(c).strip() for c in row]
        if all(lab in text for lab in labels):
            return [float(c) for c in row if isinstance(c, (int, float))]
    raise SystemExit(f"no row with {labels}")


def japan():
    """Japan, 2023 Housing and Land Survey, through the Japan Statistical Yearbook 2026 (tables 21-1
    to 21-15; occupied dwellings, thousands).

    Type: detached (一戸建) is detached, tenement houses (長屋建) semi-detached; apartments (共同住宅)
    in two-storey buildings are taken as flats in buildings under ten dwellings, the rest as ten or
    more. Tenure: owned; private rentals at market rent; public, UR and employer-issued housing at a
    reduced rent. Rooms: 居住室 (dwelling rooms) leave the kitchen out unless it is also a dining room.
    """
    d = RAW / "census" / "jp"
    src = "Statistics Bureau of Japan, 2023 Housing and Land Survey (Japan Statistical Yearbook 2026"
    t7 = xlsx_rows(d / "y752107000.xlsx")
    total = find(t7, "総数", "Total")[0]
    detached = find(t7, "一戸建", "Detached houses")[0]
    tenement = find(t7, "長屋建", "Tenement-houses")[0]
    apartments = find(t7, "共同住宅", "Apartments")[0]
    small = 0.0
    seen = False
    for row in t7:
        text = [str(c).strip() for c in row]
        if "共同住宅" in text:
            seen = True
            continue
        if seen and text and text[0] in ("1階建", "2"):
            small += float([c for c in row if isinstance(c, (int, float))][0])
        if seen and text and text[0] == "3":
            break
    other = total - detached - tenement - apartments
    add("JP", "types", "all", {"detached": detached, "semi_detached": tenement, "flat_small": small,
                               "flat_large": apartments - small, "other": other, "informal": 0}, 2023, f"{src} table 21-7)")
    t5 = xlsx_rows(d / "y752105000.xlsx")
    _, total, owned, rented, local, ur, private, issued, _ = find(t5, "令和5年", "2023")
    add("JP", "tenure", "all", {"owner": owned, "tenant_market": private, "tenant_reduced": local + ur + issued}, 2023,
        f"{src} table 21-5)")
    t1 = xlsx_rows(d / "y752101000.xlsx")
    rows2023 = [r for r in t1 if "令和5年" in [str(c).strip() for c in r]]
    rooms, _, floor = [float(c) for c in rows2023[1] if isinstance(c, (int, float))][1:4]
    add("JP", "rooms_mean", "all", {"rooms": rooms}, 2023, f"{src} table 21-1)", "no_kitchen")
    add("JP", "floor", "all", {"m2_per_dwelling": floor}, 2023, f"{src} table 21-1)")
    t4 = xlsx_rows(d / "y752104000.xlsx")
    vals = find(t4, "令和5年", "2023")
    bands = ["1900-1950", "1951-1980", "1981-1990", "1991-2000", "2001-2010", "2011-2018", "2019-2023"]
    add("JP", "periods", "all", dict(zip(bands, vals[4:11])), 2023, f"{src} table 21-4)")
    t15 = xlsx_rows(d / "y752115000.xlsx")
    edges = [0, 100, 150, 200, 300, 400, 500, 700, 1000, 1500, 2000, 3000]
    # The two private rows appear twice (bands up to 4 million yen, then from 4 million): join them.
    private_rows = [[float(c) for c in row if isinstance(c, (int, float))] for row in t15
                    if row and str(row[0]).strip().startswith("民営")]
    first = [a + b for a, b in zip(private_rows[0], private_rows[1])][1:]   # drop the total
    second = [a + b for a, b in zip(private_rows[2], private_rows[3])]
    bands_counts = first + second
    income = median_from_bands([(edges[i] * 1e4, edges[i + 1] * 1e4, c) for i, c in enumerate(bands_counts)])
    t12 = xlsx_rows(d / "y752112000.xlsx")
    rent = find(t12, "令和5年", "2023")[-2]
    add("JP", "burden", "all", {"tenant_market": rent * 12 / income}, 2023,
        f"{src} tables 21-12 and 21-15: mean monthly rent over the median annual income of private tenants)", "gross")


def sidra(path):
    """{(category name, ...): value} from a SIDRA API v3 answer, Brazil level, one variable."""
    import json
    d = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for res in d[0]["resultados"]:
        key = tuple(next(iter(c["categoria"].values())) for c in res["classificacoes"])
        value = res["series"][0]["serie"]["2022"]
        out[key] = float(value) if value not in ("-", "...", "X", "") else 0.0
    return out


def brazil():
    """Brazil, Censo Demográfico 2022 (IBGE SIDRA tables 9880 and 9932), permanent private households.

    Type: casa is a house (detached and semi-detached split as the region's measured countries split
    them); casa de vila ou em condomínio semi-detached; apartamento a flat; cortiço and indigenous
    dwellings other; degraded or unfinished structures and improvised dwellings informal.
    Rooms: cômodos count the kitchen and the bathrooms; bathrooms are taken off (table 9932 crosses
    both), with 6-9 rooms read as 7 and 10 or more as 11.
    """
    d = RAW / "census" / "br"
    src = "IBGE, Censo Demográfico 2022, SIDRA table"
    t = sidra(d / "type_size.json")
    by_type = {k[0]: v for k, v in t.items() if all(x == "Total" for x in k[1:])}
    add("BR", "types", "all", {
        "house": by_type["Casa"], "semi_detached": by_type["Casa de vila ou em condomínio"], "flat": by_type["Apartamento"],
        "other": by_type["Habitação em casa de cômodos ou cortiço"] + by_type["Habitação indígena sem paredes ou maloca"],
        "informal": by_type["Estrutura residencial permanente degradada ou inacabada"] + by_type["Improvisado"]},
        2022, f"{src} 9880")
    t = sidra(d / "tenure_type.json")
    ten = {k[3]: v for k, v in t.items() if k[4] == "Total"}
    add("BR", "tenure", "all", {"owner_outright": ten["Próprio de algum morador - já pago, herdado ou ganho"],
                                "owner_mortgage": ten["Próprio de algum morador - ainda pagando"],
                                "tenant_market": ten["Alugado"], "tenant_reduced": ten["Cedido ou emprestado"]},
        2022, f"{src} 9932 (other arrangements left out)")
    t = sidra(d / "rooms_bath_type.json")
    rooms_of = {"1 cômodo": 1, "2 cômodos": 2, "3 cômodos": 3, "4 cômodos": 4, "5 cômodos": 5, "6 a 9 cômodos": 7,
                "10 cômodos ou mais": 11}
    baths_of = {"Nenhum banheiro": 0, "1 banheiro": 1, "2 banheiros": 2, "3 banheiros ou mais": 3.3}
    for type_name, group in (("Casa", "house"), ("Apartamento", "flat"), ("Total", "all")):
        n = total = 0.0
        for (c, b, bed, _, typ), v in t.items():
            if typ == type_name and c in rooms_of and b in baths_of and bed == "Total":
                total += v * max(1, rooms_of[c] - baths_of[b])
                n += v
        add("BR", "rooms_mean", group, {"rooms": total / n}, 2022, f"{src} 9932 (cômodos less bathrooms)", "kitchen")


def pakistan():
    """Pakistan, 2023 census table 25 (housing characteristics by residential status and number of
    rooms), summed over tehsils from the CRAN package PakPC2023 (its data/TABLE_25.RData), since the
    PBS PDF no longer resolves. Needs the `rdata` package.

    Tenure: rent-free, government and other employer housing at a reduced rent; "other" left out.
    Rooms: the census counts rooms without the kitchen; "four or more" is the open class.
    """
    import rdata
    with __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore")
        df = rdata.read_rda(str(RAW / "census" / "pk" / "TABLE_25.RData"))["TABLE_25"]
    src = "Pakistan Bureau of Statistics, 2023 census table 25 (via the CRAN package PakPC2023)"
    t = df[df["REGION"] == "OVERALL"].sum(numeric_only=True)
    add("PK", "tenure", "all", {"owner": t["RES_ST_OWNED"], "tenant_market": t["RES_ST_RENTED"],
                                "tenant_reduced": t["RES_ST_RENT_FREE"] + t["RES_ST_GOVT"] + t["RES_ST_NON_GOVT"]},
        2023, src)
    add("PK", "rooms", "all", {"1": t["NO_ROOMS_ONE"], "2": t["NO_ROOMS_TWO"], "3": t["NO_ROOMS_THREE"],
                               "4+": t["NO_ROOMS_GRTREQ_FOUR"]}, 2023, src, "no_kitchen")
    # Informal: table 26 counts structures; jhuggis (huts) are taken as one household each, against
    # table 25's households. The census has no house/flat split, so types are filled.
    with __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore")
        s26 = rdata.read_rda(str(RAW / "census" / "pk" / "TABLE_26.RData"))["TABLE_26"]
    for region, area in (("URBAN", "urban"), ("RURAL", "rural")):
        huts = s26[s26["REGION"] == region]["OTHER_JUGHI"].sum()
        households = df[df["REGION"] == region]["HOUSEHOLDS"].sum()
        add("PK", "informal", area, {"share": huts / households}, 2023,
            "Pakistan Bureau of Statistics, 2023 census tables 25 and 26 (via PakPC2023), jhuggi structures per household")


def psa_csv(name):
    """A PSA OpenSTAT CSV as {first column label: {column: number}}."""
    import csv
    with open(RAW / "census" / "ph" / name, encoding="utf-8-sig", newline="") as f:
        r = list(csv.reader(f))
    head = r[0]
    return {row[0]: {h: float(x) for h, x in zip(head[2:], row[2:]) if x not in ("", "-", "..")} for row in r[1:]}


def philippines():
    """Philippines, 2020 Census of Population and Housing (PSA OpenSTAT, national rows).

    Type (table 4, occupied housing units): single house detached; duplex semi-detached;
    apartment/accessoria/rowhouse, one- or two-storey structures split into units with their own
    entrances, semi-detached (terraced); condominium/condotel a large flat; other multi-unit
    residential a small flat; commercial, institutional and other buildings other.
    Tenure (table 7, households): every own-house arrangement (on an owned, rented or rent-free lot)
    owner; renting the house or a room market tenant; rent-free house and lot reduced; not reported
    left out. Floor area (table 6): mean of the bands at their midpoints, 250 m² for 200 and over.
    """
    src = "PSA, 2020 Census of Population and Housing, OpenSTAT table"
    t = psa_csv("0041A6DTOB0.csv")
    units = {k: v["Occupied Housing Units"] for k, v in t.items()}
    add("PH", "types", "all", {
        "detached": units["Single house"],
        "semi_detached": units["Duplex"] + units["Apartment/accessoria/rowhouse"],
        "flat_large": units["Condominium/condotel"], "flat_small": units["Other multi-unit residential"],
        "other": units["Commercial/industrial/agricultural"] + units["Institutional living quarter"]
        + units["Other types of building"]}, 2020, f"{src} 0041A6DTOB0")
    t = psa_csv("0071A6DTSH0.csv")
    hh = {k: v["All Types of Building"] for k, v in t.items()}
    owner = sum(v for k, v in hh.items() if k.startswith("Own"))
    add("PH", "tenure", "all", {"owner": owner, "tenant_market": hh["Rent house/room including lot"],
                                "tenant_reduced": hh["Rent-free house and lot with consent of owner"]
                                + hh["Rent-free house and lot without consent of owner"]},
        2020, f"{src} 0071A6DTSH0 (not reported left out)")
    t = psa_csv("0061A6DFAO0.csv")["Total"]
    mids = {"Less than 5": 2.5, "5 - 9": 7.5, "10 - 19": 15, "20 - 29": 25, "30 - 49": 40, "50 - 69": 60,
            "70 - 89": 80, "90 - 119": 105, "120 - 149": 135, "150 - 199": 175, "200 sq.m. and over": 250}
    n = total = 0.0
    for col, v in t.items():
        mid = next((m for k, m in mids.items() if col.startswith(k)), None)
        if mid is not None:
            n += v
            total += v * mid
    add("PH", "floor", "all", {"m2_per_dwelling": total / n}, 2020, f"{src} 0061A6DFAO0 (band midpoints)")


def mexico():
    """Mexico, Censo de Población y Vivienda 2020, basic questionnaire tabulations (INEGI,
    cpv2020_b_eum_16_vivienda.xlsx), occupied private dwellings. Tenure is only in the extended
    questionnaire and is not read here.

    Type (sheet 01, by locality size; under 2,500 inhabitants is rural): casa única en el terreno
    detached; casa que comparte terreno con otra(s), a house on a lot shared with other houses, a
    house split as the region splits them; casa dúplex semi-detached; departamento en edificio a flat;
    vecindad or cuarto de azotea, mobile homes other; premises not built for living in and refuges
    informal (as Brazil's improvised dwellings).
    Rooms (sheet 05): cuartos count the kitchen but not bathrooms or corridors; 9 or more is open.
    """
    import openpyxl
    wb = openpyxl.load_workbook(str(RAW / "census" / "mx" / "cpv2020_b_eum_16_vivienda.xlsx"), read_only=True)
    src = "INEGI, Censo de Población y Vivienda 2020, tabulados del cuestionario básico, vivienda"
    groups = {"Casa única en el terreno": "detached", "Casa que comparte terreno": "house", "Casa dúplex": "semi_detached",
              "Departamento en edificio": "flat", "Vivienda en vecindad": "other", "Vivienda en cuarto de azotea": "other",
              "Vivienda móvil": "other", "Local no construido": "informal", "Refugio": "informal"}
    by_area = {"urban": defaultdict(float), "rural": defaultdict(float)}
    for row in wb["01"].iter_rows(min_row=10, values_only=True):
        place, kind, cls, n = row[0], row[1], row[2], row[3]
        if kind != "Vivienda particular" or not isinstance(n, (int, float)) or place == "Estados Unidos Mexicanos":
            continue
        key = next((v for k, v in groups.items() if str(cls).startswith(k)), None)
        if key is None:
            continue
        size = int(str(place).split("-")[0].split(" y ")[0].replace(" ", ""))
        by_area["rural" if size < 2500 else "urban"][key] += n
    for area, shares in by_area.items():
        add("MX", "types", area, dict(shares), 2020, f"{src} 01 (rural: localities under 2,500)")
    keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9+"]
    for row in wb["05"].iter_rows(min_row=9, values_only=True):
        if row[0] == "Estados Unidos Mexicanos" and row[1] == "Total":
            add("MX", "rooms", "all", dict(zip(keys, row[3:12])), 2020, f"{src} 05 (not specified left out)", "kitchen")
            break


def main():
    for fn in (china, china_burden, japan, brazil, pakistan, philippines, mexico):
        fn()
    path = RAW / "derived" / "national.tsv"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(r[c] for c in COLUMNS) + "\n")
    print(f"wrote {path}: {len(rows)} rows")


if __name__ == "__main__":
    sys.exit(main())
