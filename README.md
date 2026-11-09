# Property Generator for C++

> **Requires C++23** (e.g., `-std=c++23` for GCC/Clang, `/std:c++latest` for MSVC).

[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](https://raw.githubusercontent.com/dasmig/property-generator/main/LICENSE.MIT)
[![CI](https://github.com/dasmig/property-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/dasmig/property-generator/actions/workflows/ci.yml)
[![GitHub Releases](https://img.shields.io/github/release/dasmig/property-generator.svg)](https://github.com/dasmig/property-generator/releases)
[![C++23](https://img.shields.io/badge/standard-C%2B%2B23-blue.svg)](https://en.cppreference.com/w/cpp/23)
[![Header-only](https://img.shields.io/badge/type-header--only-green.svg)](https://github.com/dasmig/property-generator#integration)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue.svg)](https://dasmig.github.io/property-generator/)

**[API Reference](https://dasmig.github.io/property-generator/)** · **[Usage Guide](doc/usage.md)** · **[Data and Method](doc/data.md)** · **[Releases](https://github.com/dasmig/property-generator/releases)**

A household's home in any of 199 countries: the dwelling type, whether it is owned or rented, the rooms and bedrooms, the floor area, the year it was built and what it costs each month. Each field fits the country, the area, the household and the ones drawn before it.

```
DE, city, flat in a large building, tenant at market rent, 1 room (studio), 38 m², built 1972, 717.49 EUR a month
US, town, detached house, owner with a mortgage, 5 rooms (2 bedrooms), 126 m², built 1994, 1324.45 USD a month
JP, city, flat in a large building, tenant at market rent, 2 rooms (no bedroom), 49 m², built 1996, 80204 JPY a month
BR, city, detached house, owner with a mortgage, 4 rooms (2 bedrooms), 126 m², built 1958, 686.55 BRL a month
IN, rural, detached house, owner without a mortgage, 3 rooms (1 bedroom), 54 m², built 1969, 470.50 INR a month
```

These homes are drawn for households with gross incomes of 52,000 EUR, 78,000 USD, 5,200,000 JPY, 60,000 BRL and 420,000 INR a year.

## Limits

- The homes are statistically plausible, not real ones. There is no address, price or market value (a later version may add the value).
- Much of the world has no source for some fields, and those fields take the mean of similar countries: the dwelling type for 42% of the world's people and the housing cost for 70%. Every result says how it was obtained (`evidence`), and [`doc/data.md`](doc/data.md#coverage) lists the coverage.
- How tenure shifts with age, how the dwelling type shifts with household size, and how the cost's share falls with income are the US's, damped, wherever a country has only its totals.

## Features

- **Homes That Fit the Household**. The dwelling type depends on the area and the household's size, the tenure on the household type, the reference person's age and the dwelling type, and the rooms on the building and the household's size. In Germany 81% of homes drawn for a 22-year-old are rented, against 39% for a 70-year-old.

- **199 Countries**. Dwelling types, tenure, rooms, floor area and period of construction from Eurostat's EU-SILC and 2021 census, US ACS and AHS microdata, eleven national censuses and surveys (China, Japan, Brazil, Mexico, Pakistan, the Philippines, India, Nigeria, Ghana, Egypt, South Africa), the UN's housing compendium and DHS surveys.

- **Housing Costs**. With a household income, the monthly rent or owner's costs, in the country's currency. A higher income pays more, but a smaller share of it.

- **Evidence on Every Result**. Each field of each country is `measured`, `modelled` or `filled`, and a result carries the weakest of those it drew from. `evidence(country)` gives each field's.

- **Composes with the Others**. A request takes the household of [relationship-generator](https://github.com/dasmig/relationship-generator), the income of [occupation-generator](https://github.com/dasmig/occupation-generator) and a place's population from [city-generator](https://github.com/dasmig/city-generator). Any field can be fixed, and the others are drawn around it.

- **Deterministic Seeding**. Per-call `get_property(request, seed)` for reproducible results, and `property::seed()` for replaying a previous generation with the same request and data.

- **Batch Generation**. Generate thousands of results from one seed, on several threads with the same output for any thread count, optionally unique by a key, and stream them as JSON Lines or CSV (see the usage guide).

- **Identical Everywhere**. A seed gives the same result on every compiler, standard library and CPU (GCC, Clang, MSVC, Emscripten; x86-64 and ARM64), checked by known-answer tests.

- **Extensible Data**. Load your own TSV layers on top of the shipped data to add, change or remove entries (`extend()`), checked before they are applied.

- **JSON and Replay**. `to_json()` on every result, and a `signature()` recording the seed and the data it came from.

- **Compiled-in Data**. Define `DASMIG_PROPERTY_EMBED` to build the `lite` tier into the program, for WebAssembly and other builds without files.

- **Multi-Instance Support**. Construct independent `pty` instances with their own data and random engine.

## Integration

[`propertygen.hpp`](https://github.com/dasmig/property-generator/blob/main/dasmig/propertygen.hpp) is the library [released here](https://github.com/dasmig/property-generator/releases). Keep [`core.hpp`](https://github.com/dasmig/property-generator/blob/main/dasmig/core.hpp) and the [`core/`](https://github.com/dasmig/property-generator/tree/main/dasmig/core) directory ([dasmig-core](https://github.com/dasmig/dasmig-core)) in the same directory. Add

```cpp
#include <dasmig/propertygen.hpp>
```

to the files you want to use it in, and supply the [`resources`](https://github.com/dasmig/property-generator/tree/main/resources) folder (or define `DASMIG_PROPERTY_EMBED`).

## Usage

```cpp
#include <dasmig/propertygen.hpp>
#include <iostream>

auto& gen = dasmig::pty::instance(); // loads the lite tier

dasmig::property_request request;
request.country = "DE";
request.household_income = dasmig::core::money::from_major(52'000, "EUR", 2);

auto v = gen.get_property(request);
std::cout << v << '\n';           // DE, city, flat in a large building, tenant at market rent, 1 room (studio), 38 m², ...
std::cout << v.to_json() << '\n'; // {"country_code":"DE","area":"city",...,"monthly_cost":{"amount":717.49,"currency":"EUR"},...}

// The same seed gives the same result everywhere.
auto again = gen.get_property(request, v.seed());
```

See the [usage guide](doc/usage.md) for everything else.

## Data

Dwelling types, tenure, rooms and floor area come from Eurostat, the US Census Bureau's microdata, national statistics offices, the UN's Compendium of Housing Statistics and the DHS Program; the areas from the World Bank and the EC's Global Human Settlement Layer; the period of construction from censuses or, elsewhere, from UN population growth; and housing costs from EU-SILC, the ACS and Chinese and Japanese rent figures, on incomes from occupation-generator. [`doc/data.md`](doc/data.md) gives each source, the model for every field, how well the draws match the sources and what is known to be weak, and [`LICENSE_DATA.txt`](LICENSE_DATA.txt) gives their terms.

## Building

```bash
make            # example
make test       # tests
make bench      # benchmarks, results in build/bench.tsv
make test-embed # tests with the lite tier compiled in
make coverage   # code coverage
make lint       # clang-tidy
make docs       # API docs
make embed      # regenerate dasmig/propertygen_data.hpp from resources/lite
```

## Compiler Support

Tested with:
- Clang 18+ (`-std=c++23`)
- GCC 14+ (`-std=c++23`)
- MSVC 19.38+ (`/std:c++latest`)
- Emscripten 3.1.74

## Dependencies

| Dependency | Version | Bundled | Purpose |
|-----------|---------|---------|---------|
| [dasmig-core](https://github.com/dasmig/dasmig-core) | 1.4 | Yes (`core.hpp`, `core/`) | Platform-independent random engine and distributions, data layers, JSON |
| [Catch2](https://github.com/catchorg/Catch2) | 3.x | Yes (amalgamated) | Unit testing |

## Related Libraries

| Library | Description |
|---------|-------------|
| [address-generator](https://github.com/dasmig/address-generator) | Postal addresses with real streets by place |
| [biodata-generator](https://github.com/dasmig/biodata-generator) | Procedural human physical characteristics |
| [birth-generator](https://github.com/dasmig/birth-generator) | Demographically plausible birthdays |
| [city-generator](https://github.com/dasmig/city-generator) | Weighted city selection by population |
| [country-generator](https://github.com/dasmig/country-generator) | Weighted country selection by population |
| [device-generator](https://github.com/dasmig/device-generator) | Devices, browsers, user agents and IP addresses that fit together |
| [email-generator](https://github.com/dasmig/email-generator) | Email addresses in each country's style |
| [entity-generator](https://github.com/dasmig/entity-generator) | ECS-based entity generation |
| [finance-generator](https://github.com/dasmig/finance-generator) | Bank accounts and payment cards in each country's form |
| [id-generator](https://github.com/dasmig/id-generator) | National identity numbers, passports and identity cards that fit a person and a date |
| [interest-generator](https://github.com/dasmig/interest-generator) | Religion, hobbies and favourite media by country, age and sex |
| [name-generator](https://github.com/dasmig/name-generator) | Culturally appropriate full names |
| [nickname-generator](https://github.com/dasmig/nickname-generator) | Gamer-style nicknames |
| [occupation-generator](https://github.com/dasmig/occupation-generator) | Employment status, education and occupation by country, age and sex |
| [persona-generator](https://github.com/dasmig/persona-generator) | Complete characters composed from the other generators |
| [phone-generator](https://github.com/dasmig/phone-generator) | Phone numbers valid in each country's numbering plan |
| [relationship-generator](https://github.com/dasmig/relationship-generator) | Families around a person: parents, siblings, partners and children |
| [trait-generator](https://github.com/dasmig/trait-generator) | Personality traits with conflicts, synergies and Big Five axes |
| [user-generator](https://github.com/dasmig/user-generator) | Complete user records: account, username, email, phone and address |
| [vehicle-generator](https://github.com/dasmig/vehicle-generator) | Cars and motorcycles with plates and VINs that fit their country and date |
| [weather-generator](https://github.com/dasmig/weather-generator) | Daily weather for any place on land and any date |

## License

This library is released under the [MIT License](https://opensource.org/licenses/MIT).

```
MIT License

Copyright (c) 2026 Diego Dasso Migotto
```
