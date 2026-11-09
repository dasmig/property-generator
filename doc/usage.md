# Usage Guide

This guide covers every feature of the property-generator library. For a quick overview, see the [README](../README.md); for the sources and the model, see [Data and Method](data.md). For the full API reference, run `doxygen Doxyfile` from the repository root and open `doc/api/html/index.html`.

[TOC]

<!-- GitHub-rendered TOC (Doxygen uses [TOC] above instead) -->
<ul>
<li><a href="#quick-start">Quick Start</a></li>
<li><a href="#installation">Installation</a></li>
<li><a href="#loading-resources">Loading Resources</a></li>
<li><a href="#generating">Generating</a></li>
<li><a href="#the-request">The Request</a></li>
<li><a href="#housing-costs">Housing Costs</a></li>
<li><a href="#evidence">Evidence</a></li>
<li><a href="#with-the-other-generators">With the Other Generators</a></li>
<li><a href="#seeding-and-deterministic-generation">Seeding and Deterministic Generation</a></li>
<li><a href="#extending-data">Extending Data</a></li>
<li><a href="#replay-and-json">Replay and JSON</a></li>
<li><a href="#compiled-in-data">Compiled-in Data</a></li>
<li><a href="#thread-safety">Thread Safety</a></li>
<li><a href="#batch-generation">Batch Generation</a></li>
<li><a href="#error-reference">Error Reference</a></li>
</ul>

## Quick Start

```cpp
#include <dasmig/propertygen.hpp>
#include <iostream>

int main()
{
    auto& gen = dasmig::pty::instance();
    std::cout << gen.get_property(dasmig::property_request{}) << '\n';
    // for example: CN, city, flat in a large building, owner without a mortgage, 5 rooms (3 bedrooms), 139 m², built 1993
}
```

## Installation

Copy `dasmig/propertygen.hpp`, `dasmig/core.hpp` and the `dasmig/core/` directory into your include path, keeping them together. Supply `resources/` next to the program, or define `DASMIG_PROPERTY_EMBED` to compile the `lite` tier in.

## Loading Resources

`instance()` loads the `lite` tier on first use (or `full` if there is no `lite`), from the compiled-in copy or from the first of `resources/`, `../resources`, `property-generator/resources` and `../property-generator/resources` that has it.

```cpp
dasmig::pty gen;                                           // an empty, independent instance
bool ok = gen.load(dasmig::dataset::lite);                 // false when the tier is not found
gen.load(std::filesystem::path{"path/to/resources/lite"}); // a directory holding countries.tsv
gen.has_data();
gen.countries();                                           // the 199 country codes, sorted
```

Each `load` replaces the data and every layer loaded before. The two tiers hold the same tables and give the same draws to within rounding: `full` keeps every figure to four decimals and names each row's source, `lite` rounds to three and leaves the sources out.

## Generating

```cpp
auto v = gen.get_property(dasmig::property_request{});       // draws a seed from the instance engine
auto w = gen.get_property(dasmig::property_request{}, 1234); // deterministic; does not touch the engine

v.country_code;   // "DE"
v.area;           // dasmig::settlement::city
v.household_type; // "couple", one of dasmig::property_household_types
v.household_size; // 2
v.type;           // dasmig::dwelling_type::flat_large
v.holding;        // dasmig::tenure::tenant_market
v.rooms;          // 3: habitable rooms with the kitchen, without bathrooms
v.bedrooms;       // 2: 0 for a studio
v.floor_area;     // 74 (square metres)
v.year_built;     // 1968
v.monthly_cost;   // empty unless the request has an income
v.evidence;       // "measured", "modelled" or "filled"
v.in_building();  // true for a flat: ask address-generator for a unit
```

The fields are drawn in a fixed order, each conditioned on the ones before: the country, the area (city, town or rural), the household's type and size, the reference person's age, the dwelling type, the tenure, the rooms and bedrooms, the floor area, the year built and the cost. [Data and Method](data.md#generation-model) gives each step.

| Type | Meaning |
|------|---------|
| `detached` | A house standing on its own |
| `semi_detached` | A house sharing a wall: semi-detached or terraced |
| `flat_small` | A flat in a building of fewer than ten dwellings |
| `flat_large` | A flat in a building of ten dwellings or more |
| `informal` | A shack or makeshift dwelling |
| `other` | Rooms in a shared building, a mobile home, quarters attached to other premises |

| Tenure | Meaning |
|--------|---------|
| `owner_outright` | Owner without a mortgage or loan |
| `owner_mortgage` | Owner repaying a mortgage or loan |
| `tenant_market` | Tenant at the market rent |
| `tenant_reduced` | Tenant at a reduced rent (social, employer) or rent-free |

`dasmig::to_string()` gives the key of a type, tenure or settlement as the tables and JSON spell it.

## The Request

Every field of `property_request` is optional. A given field is used as it is and the rest is drawn to fit it.

| Field | Given | Unset |
|-------|-------|-------|
| `country` | ISO alpha-2, any case | drawn by population (uniformly with `weighted = false`) |
| `area` | `city`, `town` or `rural` | from `place_population`, else drawn from the country's shares |
| `place_population` | the place's people: 50,000 and over is a city, 5,000 to 49,999 a town, fewer is rural | |
| `household_type` | one of `one_person`, `couple`, `nuclear`, `single_parent`, `with_parents`, `multi_generation`, `other` | drawn with the size |
| `household_size` | 1 or more; above 10 is used as given and drawn as 10 or more | drawn with the type |
| `children` | members under 18; the household is drawn to hold them | none required |
| `anchor_age` | the reference person's age, 16 to 110 | drawn uniformly from 18 to 80 |
| `household_income` | gross annual, in the country's currency | no `monthly_cost` |
| `type` | forced | drawn |
| `holding` | forced | drawn |
| `reference_date` | no home is built after its year | 2023-07-01 |

```cpp
dasmig::property_request request;
request.country = "BR";
request.place_population = 1'200'000; // a city
request.household_type = "nuclear";
request.household_size = 4;
request.children = 2;
request.anchor_age = 38;
auto home = gen.get_property(request);
```

The household's type and size are drawn together from the country's table, within what the request fixes. A type and a size that cannot go together, such as a `one_person` household of three or a couple with children, are an error. Children need a household of at least one more person, and not a `one_person` or `couple` one.

The age shifts the tenure: in Germany 81% of homes drawn for a 22-year-old are rented, against 39% for a 70-year-old. A forced type or tenure leaves the other fields' random streams where they were: the year built of a forced flat comes from the same draw as it would have otherwise, although rooms and floor area follow the flat.

## Housing Costs

With `household_income` set, `monthly_cost` is what the household pays each month for its home: the rent, or the owner's mortgage payments and charges.

```cpp
request.country = "DE";
request.household_income = dasmig::core::money::from_major(48'000, "EUR", 2);
auto home = gen.get_property(request, 1);
home.holding;                 // dasmig::tenure::owner_outright
home.monthly_cost->decimal(); // "221.61": an owner outright pays upkeep and charges
home.monthly_cost->currency;  // "EUR"
```

The cost is the income times a share drawn from the country's distribution for the tenure, capped at the whole income: a tenant at market rent pays the most, an owner outright only upkeep and charges. A higher income pays more, but a smaller share of it: a German tenant at market rent pays a median of 460 EUR a month on 20,000 EUR a year (28%), 636 EUR on 48,000 (16%) and 908 EUR on 120,000 (9%). An income of zero costs zero. The income is gross, as `occupation-generator` gives it; sources that measure against disposable income are converted with the OECD's ratio of disposable to gross income ([how](data.md#housing-cost)). Without an income there is no cost, since one drawn from nothing would be invented. An income in another currency than the country's is an error.

## Evidence

Every country has every field, but not every country has a source for every field. The tables mark each row:

- **measured**: from a census, survey or register of the country;
- **modelled**: the country's own figures through a stated model, such as the period of construction from its population growth;
- **filled**: from other countries, the population-weighted mean of the subregion, then the region, then the world.

A result's `evidence` is the weakest of the fields it drew. `evidence(country)` gives each field's:

```cpp
gen.evidence("JP").to_string();
// area=measured household=measured type=measured tenure=measured rooms=measured floor_area=measured period=measured cost=modelled
```

[Data and Method](data.md#coverage) gives the shares of the world's population by evidence and field.

## With the Other Generators

The library takes plain values, so the others' results go straight into a request:

| Value | From |
|-------|------|
| `country` | `country-generator` or any result's `country_code` |
| `place_population` | `city-generator`'s city population |
| `household_type`, `household_size`, `children` | `relationship-generator`'s household; the type names are its own |
| `anchor_age` | `birth-generator` or `persona-generator` |
| `household_income` | `occupation-generator`'s income, gross annual |

`in_building()` tells the caller to give the address a unit: set `address-generator`'s `unit_chance` to 1.0 for a flat and 0.0 otherwise.

## Seeding and Deterministic Generation

- `get_property(request, seed)` gives the same result for the same request, seed and data, on every platform, without advancing the instance engine.
- `get_property(request)` draws a fresh seed from the instance engine, initially seeded from system entropy. There are no generator-level `seed()` or `unseed()` controls; for deterministic sequences, keep a `dasmig::core::rng` in the caller and pass its next value as the seed.
- `v.seed()` is the seed a result was generated from: `get_property(request, v.seed())` replays it with the same request and data.
- The call seed splits into the streams `country`, `area`, `household`, `age`, `type`, `tenure`, `rooms`, `area_m2`, `year` and `cost`. A given field skips its draw and leaves every other stream unchanged.

## Extending Data

The shipped data is a base layer. Files with the same columns as a table can be loaded on top of it to add rows, change them or remove them, without editing the shipped files. Each table has its key columns ([Data and Method](data.md#tables)): `types.tsv` is keyed by `country_code` and `area`, `costs.tsv` by `country_code` and `tenure`, and so on.

```cpp
// Override mode (the default): a row replaces the loaded row with its key; new keys are added.
gen.extend("mods/types.tsv");                 // a file named after its table
gen.extend("mods/");                          // a directory of table files, applied together

// From text, for example supplied by a WebAssembly host.
gen.extend_from_string(dasmig::property_table::types,
                       "country_code\tarea\tdetached\tsemi_detached\tflat_small\tflat_large\tinformal\tother\n"
                       "DE\tcity\t0.05\t0.05\t0.3\t0.6\t0\t0\n",
                       "scenario");

// Add mode refuses to touch keys that are already loaded.
gen.extend("mods/countries.tsv", dasmig::core::layer_mode::add);
```

- Every value in a layer is checked before anything changes. A bad layer throws `dasmig::core::tsv_error` with the file, line and column, and the data stays as it was.
- After a layer the tables must still fit together: a new country needs rows in every table, and every country needs a row for each area, building group and tenure. Otherwise `std::invalid_argument` names what is missing, and the data stays as it was.
- Columns not required by a table (`evidence`, `source`) may be left out of a layer; a row without `evidence` counts as measured.
- `layers(table)` lists what is loaded: source, mode, rows added, replaced and removed, and warnings such as unknown columns.
- `load(...)` replaces the base and drops every layer.

## Replay and JSON

Every result records the seed and the data it came from:

```cpp
auto v = gen.get_property(dasmig::property_request{});
v.signature().seed; // the call seed
v.signature().data; // gen.data_hash() when it was generated
```

`to_json()` gives the result as JSON, the form the WebAssembly layer and the game consume. Seeds are strings because JavaScript numbers cannot hold every 64-bit value. `to_json(writer)` writes into an existing `dasmig::core::json_writer`, for composing larger documents.

```json
{"country_code":"DE","area":"city","household_type":"one_person","household_size":1,"type":"flat_large",
 "holding":"tenant_market","rooms":1,"bedrooms":0,"floor_area":38,"year_built":1972,"monthly_cost":null,
 "evidence":"modelled","signature":{"seed":"0000000000000003","data":"df6af68d1dd6d658"}}
```

`monthly_cost` is `null` without an income, and `{"amount":787.34,"currency":"BRL"}` with one.

## Compiled-in Data

Define `DASMIG_PROPERTY_EMBED` before including the header to compile the `lite` tier into the program. `load(dataset::lite)` and `instance()` then use it and need no files. The compiled-in data has the same `data_hash()` as the files, so seeds replay the same either way.

`dasmig/propertygen_data.hpp` is generated from `resources/lite` by `make embed`; CI checks it is up to date.

## Thread Safety

Each `pty` instance is independent. Concurrent calls to `get_property(request)` on the **same** instance require external synchronisation (e.g. a `std::mutex`). The seeded overloads are const and may run concurrently.

## Batch Generation

Every seeded getter has batch forms: `get_property_batch` returns a `std::vector`, and `for_each_property` streams the items to a sink in index order without holding the batch.

```cpp
auto& gen = dasmig::pty::instance();
dasmig::property_request request;
request.country = "FR";

// 1,000 results from one batch seed, on four threads.
auto items = gen.get_property_batch(request, {.count = 1000, .threads = 4}, 42);

// Item 1 replays on its own: the batch seed and the index give its seed.
auto again = gen.get_property(request, dasmig::core::item_seed(42, 1));

// A million results to a file as JSON Lines, never all in memory.
std::ofstream out{"homes.jsonl"};
dasmig::core::jsonl_writer lines{out};
gen.for_each_property(request, {.count = 1'000'000, .threads = 0}, 42, lines);
```

- **Item seeds.** Item `i` is exactly `get_property(request, core::item_seed(batch_seed, first + i))`. A range can be generated directly (`first = 1000` starts at item 1000), two batches that follow each other equal one, and the output is the same for any `threads` (0 means the hardware count). Without a `batch_seed` one is drawn like the single getter draws its own.
- **Options.** `core::batch_options` has `count`, `first`, `threads` and `unique`. The request describes one item; the options describe the batch.
- **Uniqueness.** `.unique = core::unique_rule::by<property>(key)` regenerates an item whose key already appeared in the batch, with a deterministic retry seed, and throws `std::runtime_error` naming the item when the attempts run out.
- **Sinks.** `core::jsonl_writer` writes one `to_json()` per line, `core::csv_writer` flattens each result's JSON into dotted columns. Any callable `(std::uint64_t index, property&)` works.
- Batch calls use the same const getters from several threads, which the thread-safety rules above allow; the CI runs the batch tests under ThreadSanitizer.

## Error Reference

| Exception | When |
|-----------|------|
| `std::runtime_error` | Any generation call or `evidence()` before data is loaded |
| `std::invalid_argument` | An unknown country or household type; a household type, size and children that do not fit together; an anchor age outside 16 to 110; an income in another currency or negative; an invalid reference date, or one before the country's earliest period of construction; tables that no longer fit together after a layer; `extend(path)` with a file not named after a table |
| `dasmig::core::tsv_error` | A malformed table or layer (message gives file, line and column); the data is unchanged |
