#!/usr/bin/env python3
"""Download the raw sources into raw_data/ (git-ignored). Existing files are kept,
so delete a file to refresh it. Exits non-zero if anything could not be fetched.

Sources (design section 4):
- Eurostat: EU-SILC housing tables and the 2021 census tables (JSON-stat).
- US Census Bureau: ACS 2023 1-year PUMS housing records; AHS 2023 national PUF.
- DHS Program indicator API: rooms for sleeping, persons per sleeping room.
- UN Statistics Division: Compendium of Housing Statistics 2011 tables 2, 3, 15.
- UN SDG API: urban population living in slums (EN_LND_SLUM).
- World Bank: urban population share (SP.URB.TOTL.IN.ZS).
- EC JRC GHSL: GHS-DUC, population by degree of urbanisation per country.
- OECD Income Distribution Database: disposable income and direct taxes.
- UN WPP 2024 (PPgp/wpp2024): population growth rate by year since 1950.
- National census tables: China (NBS), Japan (Statistics Bureau), Brazil (IBGE SIDRA), Mexico
  (INEGI), Pakistan (PBS via PakPC2023), Philippines (PSA OpenSTAT), and India's NSS report 584,
  which is read by hand into curated/census.tsv.
"""
import json
import sys
import time
import urllib.request

from propertygen_data import RAW

HEADERS = {"User-Agent": "Mozilla/5.0 (dasmig-data-build/1.0)"}
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{}?format=JSON&lang=EN{}"
EUROSTAT_TABLES = {
    "ilc_lvho01": "&sinceTimePeriod=2021",   # dwelling type by degree of urbanisation
    "ilc_lvho02": "&sinceTimePeriod=2021",   # tenure by household type
    "ilc_lvho03": "&sinceTimePeriod=2021",   # rooms per person by tenure and type
    "ilc_lvho28": "&sinceTimePeriod=2021",   # cost burden distribution by tenure
    "ilc_lvho32": "",                        # average floor area by tenure, 2023
    "cens_21dwop_r3": "&geoLevel=country",   # dwellings by period of construction
    "cens_21dwbnr_r3": "&geoLevel=country",  # dwellings by building type, rooms and floor area
}
COMPENDIUM = "https://unstats.un.org/unsd/demographic-social/sconcerns/housing/2011_compendium/table{}.xls"
DHS_INDICATORS = "HC_RMSL_H_1RM,HC_RMSL_H_2RM,HC_RMSL_H_3RM,HC_PPRM_H_MNP,HC_PPRM_H_12P,HC_PPRM_H_34P,HC_PPRM_H_56P,HC_PPRM_H_7PP"
DHS_FIELDS = "CountryName,DHS_CountryCode,SurveyId,SurveyYear,IndicatorId,Value,CharacteristicCategory,CharacteristicLabel,IsPreferred,ByVariableLabel"
FILES = {
    "us/csv_hus.zip": "https://www2.census.gov/programs-surveys/acs/data/pums/2023/1-Year/csv_hus.zip",
    "us/ahs2023.zip": "https://www2.census.gov/programs-surveys/ahs/2023/AHS%202023%20National%20PUF%20v1.0%20CSV.zip",
    "us/acs_b25007.json": "https://api.census.gov/data/2023/acs/acs1?get=group(B25007)&for=us:1",
    "dhs/countries.json": "https://api.dhsprogram.com/rest/dhs/countries?returnFields=DHS_CountryCode,ISO2_CountryCode,CountryName&f=json",
    "dhs/national.json": f"https://api.dhsprogram.com/rest/dhs/data?indicatorIds={DHS_INDICATORS}&returnFields={DHS_FIELDS}&perpage=20000&f=json",
    "un/sdg_slum.json": "https://unstats.un.org/sdgapi/v1/sdg/Series/Data?seriesCode=EN_LND_SLUM&pageSize=20000",
    "wb/urban.json": "https://api.worldbank.org/v2/country/all/indicator/SP.URB.TOTL.IN.ZS?format=json&per_page=20000&mrnev=1",
    "ghsl/duc.zip": "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_DUC_GLOBE_R2023A/V2-0/GHS_DUC_MT_GLOBE_R2023A_V2_0.zip",
    "oecd/idd.csv": "https://sdmx.oecd.org/public/rest/data/OECD.WISE.INE,DSD_WISE_IDD@DF_IDD,/all?startPeriod=2018&format=csvfile",
    "wpp/growthrate.txt": "https://raw.githubusercontent.com/PPgp/wpp2024/main/data-raw/growthrate.txt",
}
# China, 2020 census yearbook (long form): tables 9-1 to 9-4, national and city (a), town (b), rural (c).
for t in ("B0901", "B0902", "B0903", "B0904", "B0905"):
    for suffix in ("", "a", "b", "c"):
        FILES[f"census/cn/{t}{suffix}.xls"] = f"https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/{t}{suffix}.xls"
# Mexico, 2020 census, basic questionnaire tabulations, housing.
FILES["census/mx/cpv2020_b_eum_16_vivienda.xlsx"] = "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/tabulados/cpv2020_b_eum_16_vivienda.xlsx"
# Pakistan, 2023 census tables 25 and 26, as carried by the CRAN package PakPC2023 (R data).
for t in ("25", "26"):
    FILES[f"census/pk/TABLE_{t}.RData"] = f"https://raw.githubusercontent.com/cran/PakPC2023/master/data/TABLE_{t}.RData"
# Japan, 2023 Housing and Land Survey, through the Japan Statistical Yearbook 2026 (chapter 21).
for t in ("01", "03", "04", "05", "06", "07", "12", "14", "15"):
    FILES[f"census/jp/y7521{t}000.xlsx"] = f"https://www.stat.go.jp/data/nenkan/75nenkan/zuhyou/y7521{t}000.xlsx"
# Brazil, 2022 census (IBGE SIDRA API v3), Brazil level: table 9880 (type by residents) and table
# 9932 (tenure, and rooms with bathrooms, by type) of permanent private households.
SIDRA = "https://servicodados.ibge.gov.br/api/v3/agregados/{}/periodos/2022/variaveis/{}?localidades=N1[all]&classificacao={}"
FILES["census/br/type_size.json"] = SIDRA.format(9880, 800, "125[all]|68[all]|11561[100679]|12237[104570]|11562[72593]")
FILES["census/br/tenure_type.json"] = SIDRA.format(9932, 381, "65[95810]|1973[73081]|74[95811]|63[all]|125[all]")
FILES["census/br/rooms_bath_type.json"] = SIDRA.format(9932, 381, "65[all]|1973[all]|74[all]|63[95826]|125[121264,2932,3247,6815]")
# India, NSS Report No. 584 (76th round, 2018): read by hand into curated/census.tsv; kept for reference.
FILES["census/in/r584.pdf"] = "https://www.mospi.gov.in/sites/default/files/publication_reports/Report_584_final_0.pdf"
# Philippines, 2020 census (PSA OpenSTAT PX-Web): national rows of tables 4 (building type),
# 6 (floor area by occupants) and 7 (tenure by building type). PX-Web takes a POSTed query.
PSA = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/1A/PO_2020/{}.px"
PSA_TABLES = {
    "0041A6DTOB0": {"Type of Building": 10, "Parameter": 3},
    "0061A6DFAO0": {"Number of Occupants": 11, "Floor Area of the Housing Unit": 14},
    "0071A6DTSH0": {"Tenure Status of the Housing Unit/Lot": 10, "Type of Building": 10},
}
POSTS = {}
for table, variables in PSA_TABLES.items():
    query = [{"code": "Geographic Location", "selection": {"filter": "item", "values": ["0"]}}]
    query += [{"code": code, "selection": {"filter": "item", "values": [str(i) for i in range(n)]}}
              for code, n in variables.items()]
    POSTS[f"census/ph/{table}.csv"] = (PSA.format(table), json.dumps({"query": query, "response": {"format": "csv"}}))
for t in ("02", "03", "15"):
    FILES[f"un/compendium_table{t}.xls"] = COMPENDIUM.format(t)
for name, extra in EUROSTAT_TABLES.items():
    FILES[f"eurostat/{name}.json"] = EUROSTAT.format(name, extra)

# The DHS breakdowns (residence, household size, ...) come in pages of 5,000.
DHS_BREAKDOWN = f"https://api.dhsprogram.com/rest/dhs/data?indicatorIds={DHS_INDICATORS}&breakdown=all&returnFields={DHS_FIELDS}&perpage=5000&page={{}}&f=json"

failures = []


def get(url, retries=4, wait=10, body=None):
    headers = dict(HEADERS, **({"Content-Type": "application/json"} if body else {}))
    request = urllib.request.Request(url, headers=headers, data=body.encode() if body else None)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return response.read()
        except OSError as e:
            print(f"  retry {attempt}: {url[:100]}: {e}")
            time.sleep(wait * (attempt + 1))
    return None


def fetch_dhs_pages():
    path = RAW / "dhs" / "breakdown.json"
    if path.exists():
        return
    rows, page, pages = [], 1, 1
    while page <= pages:
        data = get(DHS_BREAKDOWN.format(page))
        if data is None:
            failures.append(f"dhs/breakdown page {page}")
            return
        d = json.loads(data)
        rows += d["Data"]
        pages = d["TotalPages"]
        page += 1
    path.write_text(json.dumps({"Data": rows}), encoding="utf-8")
    print(f"dhs/breakdown.json: {len(rows):,} rows in {pages} pages")


def main():
    only = set(sys.argv[1:])
    jobs = {name: (url, None) for name, url in FILES.items()} | POSTS
    for name, (url, body) in jobs.items():
        if only and not any(o in name for o in only):
            continue
        path = RAW / name
        if path.exists():
            continue
        data = get(url, body=body)
        if data is None:
            failures.append(name)
            print(f"FAILED {name}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{name}: {len(data):,} bytes")
    if not only or any("dhs" in o for o in only):
        fetch_dhs_pages()
    if failures:
        raise SystemExit(f"failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
