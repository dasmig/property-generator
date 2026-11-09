# Data and Method

What each table holds, where its figures come from, how a home is drawn from them, how well the draws match the sources, and what is known to be weak. The terms of each source are in [`LICENSE_DATA.txt`](../LICENSE_DATA.txt).

[TOC]

## Tiers

Both tiers hold the same 11 tables, with a few rows per country.

| Tier | Size | Differs by |
|------|------|------------|
| `full` | 0.56 MB | four decimals; a `source` column on every row that has one |
| `lite` | 0.26 MB | three decimals (`rooms.tsv` eight and `bedrooms.tsv` six, both tiers, since a strong tilt magnifies their small values); no `source` columns |

Draws from the two agree to within rounding: `scripts/validate_property.py` passes on both. `lite` is the tier compiled in with `DASMIG_PROPERTY_EMBED`.

## Tables

Every table is TSV with a first-line `#` comment naming its source, keyed as listed, layered and checked before it is applied ([usage](usage.md#extending-data)). `evidence` columns hold `measured`, `modelled` or `filled` ([Evidence](#evidence)).

| Table | Key | Columns | What it holds |
|-------|-----|---------|---------------|
| `countries.tsv` | `country_code` | `population`, `currency`, `currency_digits`, `city`, `town`, `rural`; `subregion`, `net_to_gross`, `reference_income`, `area_evidence` | the 199 countries, their currency, the share of households in cities, towns and rural areas, and the income the cost model is centred on |
| `households.tsv` | `country_code`, `household_type` | `share`, `size_1` to `size_10`; `evidence` | each household type's share and its sizes (10 means 10 or more) |
| `types.tsv` | `country_code`, `area` | the six dwelling types; `evidence`, `source` | dwelling type shares in cities, towns and rural areas |
| `type_odds.tsv` | `size` | the six dwelling types | how the type shifts with household size 1 to 6 (6 or more) |
| `tenures.tsv` | `country_code`, `household_type` | the four tenures; `evidence`, `source` | the base tenure shares: an `all` row per country, and rows by household type where measured |
| `tenure_odds.tsv` | `dimension`, `value` | the four tenures | how tenure shifts with age band, household type and dwelling type |
| `rooms.tsv` | `group`, `size` | `r1` to `r10` | rooms by building group (house, flat, other) and household size, before a country's shift and tilt |
| `bedrooms.tsv` | `rooms` | `b0` to `b9` | bedrooms given rooms |
| `dwellings.tsv` | `country_code`, `group` | `rooms_tilt`, `rooms_shift`, `m2_log_mean`, `m2_log_sd`, `m2_rooms_power`; `rooms_evidence`, `area_evidence`, `rooms_source`, `area_source` | per country and building group, the shift and tilt of the rooms table and the floor area's lognormal and power of rooms (`rooms_shift` and `m2_rooms_power` since 1.0.1; without them a table reads as 0 and 1, which 1.0.0 drew) |
| `periods.tsv` | `country_code`, `from` | `to`, `share`; `evidence`, `source` | the housing stock by period of construction |
| `costs.tsv` | `country_code`, `tenure` | `log_mean`, `log_sd`; `slope_below`, `slope_above`, `evidence`, `source` | the housing cost as a share of gross household income: a lognormal at the reference income, and how it falls as the income rises |

## Sources

| Source | Gives | Countries |
|--------|-------|-----------|
| **Eurostat EU-SILC**: `ilc_lvho01` dwelling type by degree of urbanisation; `ilc_lvho02` tenure by household type; `ilc_lvho03` rooms per person; `ilc_lvho28` the share of households whose housing costs exceed 25, 40, 50, 60 and 75% of disposable income, by tenure; `ilc_lvho32` average floor area, 2023 | type, tenure, rooms, floor area, cost | 32 to 34 European countries, latest year from 2021 |
| **Eurostat census 2021**: `cens_21dwbnr_r3` dwellings by building type, rooms and floor area; `cens_21dwop_r3` dwellings by period of construction | rooms, floor area, period | 31 countries (EU and EFTA) |
| **US Census Bureau**: ACS 2023 1-year PUMS (building, tenure, householder's age, household size, year built, household income, rent and owner costs as a share of income) and the AHS 2023 national PUF (rooms, bedrooms, unit size) | every US field, and the joint structure other countries take as odds | US |
| **National censuses and surveys**: China 2020 census long form (NBS); Japan 2023 Housing and Land Survey (Statistics Bureau); Brazil 2022 census (IBGE SIDRA 9880, 9932); Mexico 2020 census (INEGI); Pakistan 2023 census tables 25 and 26 (PBS, through the CRAN package PakPC2023); Philippines 2020 census (PSA OpenSTAT); India NSS Report No. 584, 2018 (NSO); Nigeria Living Standards Survey 2018-19 (NBS); Ghana 2021 census 10% housing sample (GSS); Egypt 2017 census household file (CAPMAS, through the ERF data portal); South Africa General Household Survey 2023 (Stats SA, with DataFirst's file for the formal split) | type, tenure, rooms, floor area, period, informal share, cost | 11 countries, 51% of the population served |
| **UN Statistics Division, Compendium of Housing Statistics 2011** (tables 2, 3 and 15; censuses 1995 to 2010) | tenure, rooms, informal share | 35 countries for tenure, 32 for rooms, 13 for the informal share |
| **DHS Program** indicators (`HC_RMSL`, rooms used for sleeping) | rooms, modelled | 62 countries |
| **UN SDG indicator 11.1.1** (`EN_LND_SLUM`, urban population living in slums, UN-Habitat) | the informal share, modelled | 194 countries |
| **World Bank** `SP.URB.TOTL.IN.ZS` (from UN World Urbanization Prospects) | urban share | 196 countries |
| **EC JRC GHS-DUC** (Global Human Settlement Layer, degree of urbanisation, R2023A) | city, town and rural shares | 196 countries |
| **OECD Income Distribution Database** (`INC_DISP`, `TAC`) | disposable over gross income | 40 countries |
| **UN World Population Prospects 2024** (growth rates since 1950, through the `wpp2024` R package's data) | the modelled period of construction | 197 countries |
| **relationship-generator**'s `households.tsv` (UN Database on Household Size and Composition) | household types and sizes | 199 countries |
| **country-generator** | population, currency (the locale's), minor unit, subregion, income level | 199 countries |
| **occupation-generator**'s `income.tsv` (ILOSTAT median earnings, or GDP per head where there is no survey) | the reference income | 193 countries |

Each row of the `full` tier names its source and year.

## Evidence

Each field of each country is one of:

- **measured**: from a census, survey or register of the country;
- **modelled**: the country's own figures through a stated model (rooms from rooms used for sleeping or from rooms per person, the period of construction from population growth, the cost from rent amounts, the informal share from the slum share);
- **filled**: the population-weighted mean of the countries with a figure, first among the subregion's, then the region's or the income level's, then the world's.

A result's `evidence` is the weakest of the fields it drew from; `pty::evidence(country)` gives each field's.

### Coverage

Shares of the 199 countries' population by evidence (`scripts/check_property.py` prints them):

| Field | measured | modelled | filled |
|-------|----------|----------|--------|
| area (city, town, rural) | 93.6% | 6.4% | |
| household | 98.3% | | 1.7% |
| dwelling type | 58.0% | | 42.0% |
| tenure | 68.8% | | 31.2% |
| rooms | 60.1% | 29.3% | 10.5% |
| floor area | 49.4% | | 50.6% |
| period of construction | 46.9% | 53.1% | |
| cost | 11.0% | 19.1% | 69.8% |

The measured share is dominated by India and China (35% of the population between them). Outside Europe, the US and the national sources, dwelling type is filled for every country, and cost for every country but China and Japan.

## Generation Model

Each field is drawn in turn, conditioned on the ones before. The call seed splits into one stream per step, so a field given in the request skips its draw and leaves the others' streams unchanged.

1. **Country** (`country`): given, or drawn by population.
2. **Area** (`area`): given; else from `place_population` (50,000 and over is a city, 5,000 to 49,999 a town, fewer is rural); else drawn from `countries.tsv`. Eurostat's degree of urbanisation classifies 1 km² grid cells, so a place's population is an approximation of it. The shares: Europe's EU-SILC countries keep GHS-DUC's degree of urbanisation, which their type tables use; elsewhere the rural share is the national definition's (World Bank), as census tables use, and GHS-DUC splits the urban part into cities and towns. Hong Kong, Macao, Singapore, Monaco and the Vatican are all city.
3. **Household** (`household`): type and size drawn together from the country's 7 × 10 table, within what the request fixes. Children need a household of at least one more person, and not a one-person or couple household.
4. **Age** (`age`): given, or uniform from 18 to 80, as `id-generator` and `finance-generator` draw it. It is not demographic.
5. **Dwelling type** (`type`): P(type | area, size) ∝ share(area, type) × odds(size, type) × factor(area, type). The odds are the US's (ACS PUMS, building by household size), damped by raising them to the power 0.5 so one country's structure is not copied. The factors are fitted when the tables load (30 rounds of proportional fitting over the country's household sizes), so the shares of `types.tsv` come back over the households.
6. **Tenure** (`tenure`): the household type's own row of `tenures.tsv` where measured, else the `all` row times the household type's odds; then times the odds of the age band and of the dwelling type. The base rows are calibrated in the build so that the draws, over the country's mix of types, ages and households, return the source's shares.
7. **Rooms and bedrooms** (`rooms`): rooms from `rooms.tsv` for the building group and household size, moved down `rooms_shift` rooms (between whole rooms by linear interpolation, what falls below one room kept at one) and tilted by exp(`rooms_tilt` × rooms); bedrooms from `bedrooms.tsv` given the rooms.
8. **Floor area** (`area_m2`): rooms^`m2_rooms_power` × a lognormal with the group's `m2_log_mean` and `m2_log_sd`, rounded to the square metre, at least 4.
9. **Year built** (`year`): a period of construction from `periods.tsv` among those that start by the reference year, then a year uniformly within it, never after the reference year.
10. **Cost** (`cost`, with an income only): monthly cost = gross annual income / 12 × min(1, burden). The burden is lognormal with the tenure's `log_sd` and a log median of `log_mean` + slope × ln(income / `reference_income`), the slope `slope_below` under the reference income and `slope_above` over it. An income of zero costs zero.

### Dwelling Type

Europe's figures are by degree of urbanisation (`ilc_lvho01`, which splits houses, semi-detached houses, flats in buildings under ten dwellings and flats in larger ones). The US's come from PUMS's units in structure. National tables mostly give one national split, often only house against flat. That split becomes city, town and rural shares through Europe's average ratio of each area to the nation, refitted so the areas add back to the national figure; a house or flat total is split into the two kinds with the subregion's measured shares, or Europe's.

The **informal** type is a shack or makeshift dwelling, not every home of earth or thatch. Sources disagree on that line, so it is taken, in order: from a national table that separates it (India's unserviceable katcha structures, Pakistan's jhuggis, Brazil's degraded or improvised dwellings, and the corresponding categories of Mexico, the Philippines, Nigeria, Ghana and South Africa); from the UN compendium's table 2 (13 countries); otherwise as 0.4 × SDG 11.1.1's urban slum share, at most 35%, and half that in rural areas. SDG 11.1.1 counts a household as living in a slum for overcrowding or for missing water, sanitation or durable housing, so it is far wider than informal dwellings and its definitions differ between countries (Bangladesh 3% against China 26% in the same series).

### Tenure

| Library | EU-SILC | US ACS | National tables |
|---------|---------|--------|-----------------|
| `owner_outright` | owner, no outstanding mortgage | owned free and clear | owned, paid off, inherited |
| `owner_mortgage` | owner with a mortgage or loan | owned with a mortgage or loan | still paying |
| `tenant_market` | tenant at market price | rented | rented |
| `tenant_reduced` | tenant at reduced price or free | occupied without payment of rent | rent-free, lent, employer or government housing |

Where a source gives owners without the mortgage split (the UN compendium, several censuses), the split comes from the subregion's measured countries of the same income level, or else from a split by income level (3% of owners with a mortgage in low-income countries, 6% lower-middle, 15% upper-middle). A source without a category of tenants has them split the same way.

The odds come from three places. Age: the US's householders by age band (ACS PUMS), damped by the power 0.8, since renting young and owning later holds widely; EU-SILC's tenure by age counts persons, so a young adult in the parents' home counts as an owner, and it is not used. Household type: the geometric mean over the EU-SILC countries, damped by 0.5. Dwelling type: the US's, damped by 0.5, with an informal dwelling a fifth as likely to carry a mortgage. Where EU-SILC gives rows by household type, one factor per tenure on every row makes the draws return the country's overall shares too.

### Rooms

Rooms are habitable rooms with the kitchen and without bathrooms, toilets and corridors, as the ACS, AHS and EU-SILC count them. A source that leaves the kitchen out (China's 间, Japan's 居住室, India's living rooms, Pakistan's census) is taken as one room more; Brazil's cômodos count bathrooms, which are taken off with table 9932.

The base table is the AHS's rooms by building group and household size, smoothed with the neighbouring sizes and the group's margin and then tilted back to each cell's own mean. Each country moves it down by a shift of s rooms and then tilts it by exp(θ × rooms), per building group, fitted to the best source it has. A tilt alone (1.0.0) reaches a smaller mean by piling homes onto one room, 49% of Latvia's flats against 18% of its dwellings in its census; a shift moves the shape whole. Over the 43 countries with a distribution the squared error of the shares is 1.82 with a tilt, 0.99 with a shift and 0.34 with both.

| Source | Fit | Evidence |
|--------|-----|----------|
| Eurostat census 2021, rooms by building type | shift and tilt to the house and flat distributions, separately | measured |
| a national or compendium distribution | shift and tilt to the shares and the mean | measured |
| a mean | shift | measured |
| DHS, rooms used for sleeping | shift to the 1, 2 and 3+ shares, through `bedrooms.tsv` | modelled |
| EU-SILC rooms per person | shift, × the mean household size | modelled |

A country without a source takes the mean shift and tilt of its subregion's measured countries, else its income level's, else the world's.

Bedrooms given rooms are the AHS's everywhere: one room is a studio, and a home has fewer bedrooms than rooms from two rooms on.

### Floor Area

Floor area is rooms^p × a lognormal, per building group. The power p and the spread left at a given number of rooms are the US's, regressed on the AHS's unit size bands (each band's lower and upper bound, so the band's width counts in the spread): 0.80 for flats, whose rooms get smaller as they multiply, and 1.18 for houses (1.13 for other dwellings). 1.0.0 multiplied rooms by an area per room (p = 1), which drew a ten-room flat at ten times a one-room one.

Eurostat's census floor-area bands by building type give 22 countries a house and a flat distribution. Each is fitted with an interval-censored lognormal (the bands' bounds, the first and last open), whose mean log sets the level; its spread, capped at the US's for the group (52% of Norway's houses are in the open band of 150 m² or more, where the fitted spread is extrapolation), less what the drawn rooms already spread (p² × the variance of log rooms) is the spread left, at least 0.15. Their other dwellings take the flats' parameters. Elsewhere the source's mean area per dwelling is matched over the country's rooms: EU-SILC's 2023 average (13 more countries), China's area per person × its household size, and Japan's, India's and the Philippines' figures; such a country's spread is that of the measured countries near it, and its house and flat levels sit half as far apart as the US's.

### Period of Construction

Measured from the Eurostat census 2021 (31 countries, eight periods from before 1919), the ACS's year built, Japan's survey, China's census and India's NSS (owned dwellings by years since built). Elsewhere it is modelled from UN WPP's population growth since 1950: each year adds the growth plus the dwellings replaced, and each dwelling survives at 1 − δ a year, with δ 1.2% in high-income countries, 2% upper-middle, 2.5% lower-middle and 3% low (about 1% fits the European census). The stock left from before 1950 is the band 1900 to 1949.

### Housing Cost

The cost is a share of income, since no open source gives rents and prices for most countries but the share of income spent on housing is measured widely:

- **Europe**: `ilc_lvho28` gives, per tenure, the shares of households above 25, 40, 50, 60 and 75% of disposable income; a lognormal is fitted through them.
- **US**: ACS PUMS gross rent and owner costs as a share of household income (GRPIP, OCPIP), which is gross. The ACS caps the share at 101%, and many low-income households are at the cap, so the lognormal is fitted to the median and the interquartile range rather than to the mean of logs. Households without income are left out. Rent-free tenants are not asked, so the reduced-rent level is the market level times Europe's ratio of the two.
- **China and Japan** (modelled): the market tenant's level from rent amounts against incomes (China's census median rent over the urban median disposable income of a household of 2.62; Japan's mean rent over the median income of private tenants), the other tenures at the US's ratios to it.
- **Everywhere else** (filled): the subregion's mean, else the region's, else the world's.

**Gross and disposable.** `occupation-generator`'s income is gross, and so is the request's. A burden on disposable income becomes one on gross income through the OECD's ratio of disposable to gross (`INC_DISP` / (`INC_DISP` + |`TAC`|), 40 countries, 0.66 for Denmark to 0.94 for Brazil and Costa Rica; 0.78 where it is not published), stored as `net_to_gross` in `countries.tsv`.

The share includes mortgage payments in the US and only mortgage interest in EU-SILC, so an owner with a mortgage pays less in Europe's figures than in the US's (in Italy, about as much as an owner without one).

**Income.** A household with a higher income pays more, but a smaller share. In the US microdata the median share falls from 92% of income for market tenants in the lowest fifth of incomes to 16% in the highest, and from 35% to 5% for owners outright. A lognormal by tenure alone would give a rich household the poor one's tail: an owner outright on 78,000 USD could pay 4,900 USD a month. So the burden's log median is a line in log income, fitted per tenure through the medians of the ten US income deciles, with one slope below the US's mean log household income and another above it, since rents have a floor:

| Tenure | Slope below | Slope above | Spread left (log sd) | Spread overall |
|--------|-------------|-------------|----------------------|----------------|
| `owner_outright` | −0.94 | −0.61 | 0.56 | 0.89 |
| `owner_mortgage` | −0.98 | −0.51 | 0.45 | 0.61 |
| `tenant_market` | −0.63 | −0.60 | 0.42 | 0.71 |

A reduced-rent tenant takes the market tenant's slopes. Every country takes the US's slopes, with its own level: its lognormal over all households is moved by the US's difference between that tenure's median and the median at the US's mean income, and its spread shrinks by the US's ratio of the spread left at a given income to the spread overall.

The line is centred on each country's `reference_income`: the US's geometric mean household income (70,925 USD in 2023) times the country's median earnings over the US's, both from `occupation-generator` (the geometric mean of the male and female medians). Germany's is 62,796 EUR, Brazil's 37,117 BRL and India's 206,623 INR. Eritrea, North Korea, South Sudan, Syria, the Vatican and Yemen have no earnings there; their `reference_income` is 0 and their burden does not depend on the income.

The median monthly cost of a market tenant at the reference income comes out at 1,552 USD in the US, 703 EUR in Germany, 960 EUR in France, 71,478 JPY in Japan, 812 BRL in Brazil and 4,058 INR in India.

## How Well It Matches

`scripts/validate_property.py` builds `scripts/sample_property.cpp`, draws 20,000 homes per country with an income, and compares the draws with the figures they came from. A check passes when the countries outside its tolerance are at most its allowance. On 2026-11-09 every check passed on both tiers:

| Check | Against | Tolerance | Result |
|-------|---------|-----------|--------|
| dwelling types | `types.tsv` over the areas | 0.015 a share | 199 of 199 |
| tenure | the source's shares before calibration | 0.03 a share | 199 of 199 |
| mean rooms | the source's mean, for countries fitted to one figure | 10% | 37 of 38 (North Korea 11%) |
| rooms shares | a distribution for all dwellings, the largest gap in a category | 0.10 | 30 of 33 (South Korea, North Korea, Türkiye: up to 0.18) |
| mean floor area | the source's mean area per dwelling | 15% | 17 of 17 |
| mean log floor area, houses and flats | the census bands' lognormal | 0.05 | 44 of 44 |
| spread of log floor area, houses and flats | the census bands' lognormal, capped at the US's | 0.10 | 39 of 44 (houses of Bulgaria, Slovenia, Sweden, the Netherlands and Croatia, wider by up to 0.16) |
| mean year built | `periods.tsv` | 1.5 years | 199 of 199 |
| median burden per tenure, at the reference income | `costs.tsv` | three times the median's sampling error, plus 1% | 199 of 199 |

And the US's joint structure against the microdata it came from, as the slope of the drawn log-odds on the microdata's (1 would copy it; the damping aims at 0.5, or 0.8 for age):

| Joint | Slope |
|-------|-------|
| tenure given dwelling type | 0.47 |
| tenure given age band | 0.74 |
| dwelling type given household size | 0.46 |
| mean rooms given building and household size | within 1.1% in every cell |
| median burden per tenure at a quarter of, half of, once, twice and four times the reference income, against the PUMS medians by income fifth | within 9.4% in the 9 cells inside the fifths' range |

The draws were also read by hand for the 20 most populous countries.

## Rebuilding the Data

The scripts are in `scripts/` and the downloads go to `raw_data/` (not in the repository). From the library's root:

```bash
python scripts/fetch_raw.py                       # downloads; keeps files already there
.venv/Scripts/python scripts/read_us.py           # US microdata -> raw_data/derived/us.json
.venv/Scripts/python scripts/read_national.py     # national tables -> raw_data/derived/national.tsv (needs xlrd, openpyxl, rdata)
.venv/Scripts/python scripts/read_sources.py      # every source -> raw_data/derived/measures.json (needs xlrd)
python scripts/prepare_tables.py                  # resources/full and resources/lite
python scripts/check_property.py [CC ...]         # checks both tiers, prints coverage and a country's rows
.venv/Scripts/python scripts/validate_property.py --tier full   # draws and compares
make embed                                        # dasmig/propertygen_data.hpp
```

`scripts/curated/census.tsv` holds national figures typed from reports that scripts cannot read (India, Nigeria, Ghana, Egypt, South Africa), one row per figure with its source. `relationship-generator` and `country-generator` are read from their directories next to this one. A rebuild from the same downloads is byte-identical.

## Known Limitations

- **Much of the world is filled.** Dwelling type is filled for 42% of the population, among them Indonesia, Bangladesh, Russia, Ethiopia, DR Congo, Vietnam, Iran and Kenya; East and Middle Africa take the mean of Africa's measured countries. Russia's tenure is filled.
- **The joint structure is the US's.** How type shifts with household size, how tenure shifts with type, and rooms given building and household size come from US microdata, damped, wherever a country has only its margins. Combinations rare in a country can come out.
- **Bedrooms depend only on rooms**, by the AHS's table, everywhere. Nothing bounds persons per bedroom, so a household of six in a home of one bedroom can be drawn.
- **A shift and a tilt per building group** cannot take every shape: South Korea's and Türkiye's peaks at four and three rooms come out flatter, and North Korea's 17% of one-room homes is not drawn. Where a census has many small homes, the rooms alone can spread the floor area wider than its census (houses of Bulgaria, Slovenia, Sweden, the Netherlands and Croatia, by up to 0.16 in log sd).
- **Definitions differ.** Rooms with or without the kitchen are adjusted by one room; the informal share rests on a proxy for most countries; the UN compendium's figures are from censuses of 1995 to 2010.
- **The cost depends on income and tenure only.** It does not depend on the home's size or the area. How the share falls with income is the US's everywhere, and the reference income takes the US's ratio of household income to median earnings, though households have more earners in some countries than others. Outside Europe and the US most of the level is filled: Great Britain's (Northern Europe's mean, as the UK left EU-SILC) gives a market tenant about 550 GBP a month at its reference income, low against its private rents. China's census rents give a market tenant's median of about 6% of gross income, low against other sources.
- **One earner.** The cost is against the household income passed in; a caller that passes one person's income makes the burden high.
- **The age is not drawn demographically**: without `anchor_age` it is uniform from 18 to 80.
- **No market value.** The price-to-income ratio waits for a later version.
