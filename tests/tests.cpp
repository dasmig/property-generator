#include "catch_amalgamated.hpp"
#include "../dasmig/propertygen.hpp"

#include <algorithm>
#include <filesystem>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

using dasmig::dwelling_type;
using dasmig::property_request;
using dasmig::settlement;
using dasmig::tenure;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static dasmig::pty make_loaded_generator()
{
    dasmig::pty gen;
    if (!gen.load(dasmig::dataset::lite))
    {
        for (const auto* candidate : {"resources/lite", "../resources/lite"})
        {
            if (std::filesystem::is_directory(candidate))
            {
                gen.load(std::filesystem::path{candidate});
                break;
            }
        }
    }
    REQUIRE(gen.has_data());
    return gen;
}

static property_request in(std::string country)
{
    property_request r;
    r.country = std::move(country);
    return r;
}

static dasmig::core::money eur(double amount)
{
    return dasmig::core::money::from_major(amount, "EUR", 2);
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

TEST_CASE("load(dataset::lite) loads every table", "[loading]")
{
    const auto gen = make_loaded_generator();
    REQUIRE(gen.countries().size() == 199);
    for (const auto t : {dasmig::property_table::countries, dasmig::property_table::households,
                         dasmig::property_table::types, dasmig::property_table::type_odds,
                         dasmig::property_table::tenures, dasmig::property_table::tenure_odds,
                         dasmig::property_table::rooms, dasmig::property_table::bedrooms,
                         dasmig::property_table::dwellings, dasmig::property_table::periods,
                         dasmig::property_table::costs})
    {
        REQUIRE(gen.layers(t).size() == 1);
    }
}

TEST_CASE("load - non-existent path is a no-op", "[loading]")
{
    dasmig::pty gen;
    gen.load(std::filesystem::path{"no/such/directory"});
    REQUIRE_FALSE(gen.has_data());
    REQUIRE(gen.data_hash() == 0);
}

#ifndef DASMIG_PROPERTY_EMBED // compiled-in data is never missing
TEST_CASE("load(dataset) returns false for a missing tier", "[loading]")
{
    const auto old_cwd = std::filesystem::current_path();
    const auto tmp = std::filesystem::temp_directory_path() / "pty_empty_dir";
    std::filesystem::create_directories(tmp);
    std::filesystem::current_path(tmp);
    dasmig::pty gen;
    const bool loaded = gen.load(dasmig::dataset::full);
    std::filesystem::current_path(old_cwd);
    std::filesystem::remove_all(tmp);
    REQUIRE_FALSE(loaded);
    REQUIRE_FALSE(gen.has_data());
}
#endif

TEST_CASE("the singleton loads data on first use", "[loading]")
{
    REQUIRE(dasmig::pty::instance().has_data());
}

TEST_CASE("the full tier loads and gives the same countries", "[loading]")
{
    dasmig::pty full;
    if (!full.load(dasmig::dataset::full)) SKIP("full tier not found");
    REQUIRE(full.countries() == make_loaded_generator().countries());
}

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

TEST_CASE("get_property throws when no data is loaded", "[generation]")
{
    dasmig::pty gen;
    REQUIRE_THROWS_AS(gen.get_property(property_request{}), std::runtime_error);
    REQUIRE_THROWS_AS(gen.get_property(property_request{}, std::uint64_t{1}), std::runtime_error);
    REQUIRE_THROWS_AS(gen.evidence("DE"), std::runtime_error);
}

TEST_CASE("get_property with a seed is deterministic", "[generation][seed]")
{
    const auto gen = make_loaded_generator();
    for (std::uint64_t s = 0; s < 100; ++s)
    {
        REQUIRE(gen.get_property(property_request{}, s).to_json() == gen.get_property(property_request{}, s).to_json());
    }
}

TEST_CASE("a result replays from its seed", "[generation][seed]")
{
    auto gen = make_loaded_generator();
    const auto v = gen.get_property(property_request{});
    REQUIRE(gen.get_property(property_request{}, v.seed()).to_json() == v.to_json());
}

TEST_CASE("explicit per-call seeds replay across generator instances", "[seed]")
{
    const auto first = make_loaded_generator();
    const auto second = make_loaded_generator();
    REQUIRE(first.get_property(property_request{}, 42).to_json() == second.get_property(property_request{}, 42).to_json());
}

TEST_CASE("every field is in range", "[generation]")
{
    const auto gen = make_loaded_generator();
    for (std::uint64_t s = 0; s < 3000; ++s)
    {
        const auto p = gen.get_property(property_request{}, s);
        REQUIRE(p.country_code.size() == 2);
        REQUIRE(p.household_size >= 1);
        REQUIRE(p.rooms >= 1);
        REQUIRE(p.rooms <= 10);
        REQUIRE(p.bedrooms < std::max<int>(p.rooms, 2));
        REQUIRE(p.floor_area >= 4);
        REQUIRE(p.year_built <= 2023);
        REQUIRE(p.year_built >= 1000);
        REQUIRE_FALSE(p.monthly_cost.has_value());
        REQUIRE((p.evidence == "measured" || p.evidence == "modelled" || p.evidence == "filled"));
        REQUIRE(p.in_building() == (p.type == dwelling_type::flat_small || p.type == dwelling_type::flat_large));
        REQUIRE((p.to_string().find("(studio)") != std::string::npos) == (p.rooms == 1));
    }
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

TEST_CASE("a given country is used, in any case; an unknown one is an error", "[request]")
{
    const auto gen = make_loaded_generator();
    REQUIRE(gen.get_property(in("de"), 1).country_code == "DE");
    REQUIRE_THROWS_AS(gen.get_property(in("XX"), 1), std::invalid_argument);
    REQUIRE_THROWS_AS(gen.evidence("XX"), std::invalid_argument);
}

TEST_CASE("the area follows the request, then the place's population", "[request]")
{
    const auto gen = make_loaded_generator();
    auto r = in("FR");
    r.area = settlement::rural;
    REQUIRE(gen.get_property(r, 3).area == settlement::rural);
    r.area.reset();
    for (const auto& [people, area] : std::map<std::uint64_t, settlement>{
             {50'000, settlement::city}, {49'999, settlement::town}, {5'000, settlement::town}, {4'999, settlement::rural}})
    {
        r.place_population = people;
        REQUIRE(gen.get_property(r, 3).area == area);
    }
}

TEST_CASE("household type and size are echoed and must agree", "[request]")
{
    const auto gen = make_loaded_generator();
    auto r = in("BR");
    r.household_type = "nuclear";
    r.household_size = 5;
    const auto p = gen.get_property(r, 9);
    REQUIRE(p.household_type == "nuclear");
    REQUIRE(p.household_size == 5);

    r.household_type = "one_person";
    r.household_size = 3;
    REQUIRE_THROWS_AS(gen.get_property(r, 9), std::invalid_argument);
    r.household_type = "commune";
    r.household_size.reset();
    REQUIRE_THROWS_AS(gen.get_property(r, 9), std::invalid_argument);
    r.household_type.reset();
    r.household_size = 0;
    REQUIRE_THROWS_AS(gen.get_property(r, 9), std::invalid_argument);

    // A size above 10 is used as given, drawn as 10 or more.
    r.household_size = 14;
    REQUIRE(gen.get_property(r, 9).household_size == 14);
}

TEST_CASE("children are held by a household that can hold them", "[request]")
{
    const auto gen = make_loaded_generator();
    auto r = in("IN");
    r.children = 3;
    for (std::uint64_t s = 0; s < 300; ++s)
    {
        const auto p = gen.get_property(r, s);
        REQUIRE(p.household_size >= 4);
        REQUIRE(p.household_type != "one_person");
        REQUIRE(p.household_type != "couple");
    }
    r.household_size = 3;
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
    r.household_size.reset();
    r.household_type = "couple";
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
}

TEST_CASE("the anchor age must be 16 to 110", "[request]")
{
    const auto gen = make_loaded_generator();
    auto r = in("US");
    r.anchor_age = 15;
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
    r.anchor_age = 111;
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
    r.anchor_age = 70;
    REQUIRE_NOTHROW(gen.get_property(r, 1));
}

TEST_CASE("young households rent more than old ones", "[request][stats]")
{
    const auto gen = make_loaded_generator();
    const auto renters = [&](std::uint8_t age)
    {
        auto r = in("DE");
        r.anchor_age = age;
        int n = 0;
        for (std::uint64_t s = 0; s < 4000; ++s)
        {
            const auto h = gen.get_property(r, s).holding;
            n += h == tenure::tenant_market || h == tenure::tenant_reduced;
        }
        return n;
    };
    REQUIRE(renters(22) > renters(70) + 600);
}

TEST_CASE("a forced type or tenure is kept and the other streams do not move", "[request][seed]")
{
    const auto gen = make_loaded_generator();
    for (std::uint64_t s = 0; s < 200; ++s)
    {
        const auto free = gen.get_property(in("GB"), s);
        auto r = in("GB");
        r.type = dwelling_type::flat_large;
        r.holding = tenure::tenant_reduced;
        const auto forced = gen.get_property(r, s);
        REQUIRE(forced.type == dwelling_type::flat_large);
        REQUIRE(forced.holding == tenure::tenant_reduced);
        REQUIRE(forced.in_building());
        REQUIRE(forced.area == free.area);
        REQUIRE(forced.household_type == free.household_type);
        REQUIRE(forced.household_size == free.household_size);
        REQUIRE(forced.year_built == free.year_built);
    }
}

TEST_CASE("an income gives a monthly cost in the country's currency", "[request][cost]")
{
    const auto gen = make_loaded_generator();
    auto r = in("DE");
    r.household_income = eur(48000);
    for (std::uint64_t s = 0; s < 500; ++s)
    {
        const auto p = gen.get_property(r, s);
        REQUIRE(p.monthly_cost.has_value());
        REQUIRE(p.monthly_cost->currency == "EUR");
        REQUIRE(p.monthly_cost->major() > 0.0);
        REQUIRE(p.monthly_cost->major() <= 4000.0); // at most the whole income
    }
    r.household_income = dasmig::core::money::from_major(48000, "USD", 2);
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
    r.household_income = eur(-1);
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
}

TEST_CASE("a higher income pays a smaller share of it", "[request][cost][stats]")
{
    const auto gen = make_loaded_generator();
    const auto median_share = [&](double income)
    {
        auto r = in("DE");
        r.holding = tenure::tenant_market;
        r.household_income = eur(income);
        std::vector<double> shares;
        for (std::uint64_t s = 0; s < 2001; ++s) shares.push_back(gen.get_property(r, s).monthly_cost->major() * 12.0 / income);
        std::ranges::nth_element(shares, shares.begin() + 1000);
        return shares[1000];
    };
    const double poor = median_share(15000);
    const double middle = median_share(60000);
    const double rich = median_share(240000);
    REQUIRE(poor > middle * 1.5);
    REQUIRE(middle > rich * 1.5);
    REQUIRE(rich * 240000 > middle * 60000); // but a larger amount

    // No income, no cost to share.
    auto r = in("DE");
    r.household_income = eur(0);
    REQUIRE(gen.get_property(r, 1).monthly_cost->minor == 0);
}

TEST_CASE("no home is built after the reference date", "[request]")
{
    const auto gen = make_loaded_generator();
    auto r = in("CN");
    r.reference_date = std::chrono::year{1995} / 3 / 1;
    for (std::uint64_t s = 0; s < 500; ++s) REQUIRE(gen.get_property(r, s).year_built <= 1995);
    r.reference_date = std::chrono::year{1700} / 1 / 1;
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
    r.reference_date = std::chrono::year{2023} / 2 / 30;
    REQUIRE_THROWS_AS(gen.get_property(r, 1), std::invalid_argument);
}

TEST_CASE("unweighted draws reach the small countries", "[request][stats]")
{
    const auto gen = make_loaded_generator();
    property_request r;
    r.weighted = false;
    std::set<std::string> seen;
    for (std::uint64_t s = 0; s < 4000; ++s) seen.insert(gen.get_property(r, s).country_code);
    REQUIRE(seen.size() > 190);
    REQUIRE(seen.contains("VA"));
}

// ---------------------------------------------------------------------------
// Statistics: the draws return the tables (validate_property.py checks all
// countries; these are spot checks)
// ---------------------------------------------------------------------------

TEST_CASE("dwelling types and tenure follow the data", "[stats]")
{
    const auto gen = make_loaded_generator();
    std::map<dwelling_type, int> types;
    std::map<tenure, int> holdings;
    constexpr int draws = 20000;
    for (std::uint64_t s = 0; s < draws; ++s)
    {
        const auto p = gen.get_property(in("JP"), s);
        ++types[p.type];
        ++holdings[p.holding];
    }
    // Japan, 2023 Housing and Land Survey: owners 61%; flats 47%.
    const double owners = holdings[tenure::owner_outright] + holdings[tenure::owner_mortgage];
    REQUIRE(owners / draws == Catch::Approx(0.61).margin(0.03));
    const double flats = types[dwelling_type::flat_small] + types[dwelling_type::flat_large];
    REQUIRE(flats / draws == Catch::Approx(0.47).margin(0.04));
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

TEST_CASE("evidence per field and per result", "[evidence]")
{
    const auto gen = make_loaded_generator();
    const auto us = gen.evidence("US");
    REQUIRE(us.type == "measured");
    REQUIRE(us.tenure == "measured");
    REQUIRE(us.rooms == "measured");
    REQUIRE(us.to_string().starts_with("area="));
    // A result's evidence is the weakest of the fields it drew.
    auto r = in("US");
    r.household_income = dasmig::core::money::from_major(70000, "USD", 2);
    const auto p = gen.get_property(r, 4);
    const std::set<std::string> fields{us.area,  us.household,  us.type,   us.tenure,
                                       us.rooms, us.floor_area, us.period, us.cost};
    const std::string weakest = fields.contains("filled") ? "filled" : fields.contains("modelled") ? "modelled" : "measured";
    REQUIRE(p.evidence == weakest);
}

// ---------------------------------------------------------------------------
// Conversion
// ---------------------------------------------------------------------------

TEST_CASE("string conversion and streaming give the summary", "[conversion]")
{
    const auto gen = make_loaded_generator();
    const auto v = gen.get_property(in("DE"), std::uint64_t{5});
    const std::string s = v;
    std::ostringstream os;
    os << v;
    REQUIRE(s == v.to_string());
    REQUIRE(os.str() == v.to_string());
    REQUIRE(s.starts_with("DE, "));
    REQUIRE(s.find(" m², built ") != std::string::npos);
    REQUIRE(dasmig::to_string(dwelling_type::semi_detached) == "semi_detached");
    REQUIRE(dasmig::to_string(tenure::tenant_market) == "tenant_market");
    REQUIRE(dasmig::to_string(settlement::town) == "town");
}

// ---------------------------------------------------------------------------
// Known answers (rule 2): the same seed and data give these exact results on
// every compiler and platform. A change here is a change of output and needs
// a major version.
// ---------------------------------------------------------------------------

TEST_CASE("known answers for fixed seeds", "[kat]")
{
    dasmig::pty gen;
    gen.load(std::filesystem::path{"resources/lite"});
    if (!gen.has_data()) gen.load(std::filesystem::path{"../resources/lite"});
    REQUIRE(gen.has_data());
    REQUIRE(gen.data_hash() == 0x4a55196d601f537dULL);

    REQUIRE(gen.get_property(property_request{}, std::uint64_t{1}).to_json() ==
            R"({"country_code":"ES","area":"town","household_type":"single_parent","household_size":2,"type":"flat_small","holding":"owner_mortgage","rooms":4,"bedrooms":1,"floor_area":56,"year_built":1989,"monthly_cost":null,"evidence":"modelled","signature":{"seed":"0000000000000001","data":"4a55196d601f537d"}})");
    REQUIRE(gen.get_property(in("DE"), std::uint64_t{3}).to_json() ==
            R"({"country_code":"DE","area":"city","household_type":"one_person","household_size":1,"type":"flat_large","holding":"tenant_market","rooms":1,"bedrooms":0,"floor_area":35,"year_built":1972,"monthly_cost":null,"evidence":"modelled","signature":{"seed":"0000000000000003","data":"4a55196d601f537d"}})");
    auto r = in("BR");
    r.household_income = dasmig::core::money::from_major(90000, "BRL", 2);
    REQUIRE(gen.get_property(r, std::uint64_t{5}).to_json() ==
            R"({"country_code":"BR","area":"city","household_type":"multi_generation","household_size":6,"type":"detached","holding":"tenant_market","rooms":4,"bedrooms":1,"floor_area":155,"year_built":2013,"monthly_cost":{"amount":787.34,"currency":"BRL"},"evidence":"filled","signature":{"seed":"0000000000000005","data":"4a55196d601f537d"}})");

    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (std::uint64_t s = 0; s < 10000; ++s)
    {
        for (const char c : gen.get_property(property_request{}, s).to_json())
        {
            h ^= static_cast<unsigned char>(c);
            h *= 0x100000001b3ULL;
        }
    }
    REQUIRE(h == 0xf630291d49de27d4ULL);
}

// ---------------------------------------------------------------------------
// JSON and signatures
// ---------------------------------------------------------------------------

TEST_CASE("to_json and signature", "[json]")
{
    const auto gen = make_loaded_generator();
    const auto v = gen.get_property(property_request{}, std::uint64_t{99});
    REQUIRE(v.signature().seed == 99);
    REQUIRE(v.seed() == 99);
    REQUIRE(v.signature().data == gen.data_hash());
    const auto json = v.to_json();
    REQUIRE(json.starts_with(R"({"country_code":")"));
    REQUIRE(json.find(R"("monthly_cost":null)") != std::string::npos);
    REQUIRE(json.find(R"("signature":{"seed":"0000000000000063")") != std::string::npos);

    dasmig::core::json_writer w;
    w.begin_array();
    v.to_json(w);
    w.end_array();
    REQUIRE(w.str() == "[" + json + "]");

    auto r = in("FR");
    r.household_income = eur(36000);
    REQUIRE(gen.get_property(r, 1).to_json().find(R"("monthly_cost":{"amount":)") != std::string::npos);
}

// ---------------------------------------------------------------------------
// Extending data (rule 8)
// ---------------------------------------------------------------------------

TEST_CASE("extend overrides rows and reloading drops the layers", "[extend]")
{
    auto gen = make_loaded_generator();
    const auto base_hash = gen.data_hash();
    const auto before = gen.get_property(in("DE"), std::uint64_t{7});

    // Every German home in a large block of flats.
    const auto& info = gen.extend_from_string(dasmig::property_table::types,
                                              "country_code\tarea\tdetached\tsemi_detached\tflat_small\tflat_large\tinformal\tother\n"
                                              "DE\tcity\t0\t0\t0\t1\t0\t0\n"
                                              "DE\ttown\t0\t0\t0\t1\t0\t0\n"
                                              "DE\trural\t0\t0\t0\t1\t0\t0\n",
                                              "flats.tsv");
    REQUIRE(info.replaced == 3);
    REQUIRE(gen.data_hash() != base_hash);
    REQUIRE(gen.layers(dasmig::property_table::types).size() == 2);
    for (std::uint64_t s = 0; s < 100; ++s) REQUIRE(gen.get_property(in("DE"), s).type == dwelling_type::flat_large);
    REQUIRE(gen.get_property(in("DE"), 7).signature().data == gen.data_hash());

    // Reloading the base drops every layer.
    REQUIRE(gen.load(dasmig::dataset::lite));
    REQUIRE(gen.data_hash() == base_hash);
    REQUIRE(gen.get_property(in("DE"), std::uint64_t{7}).to_json() == before.to_json());
}

TEST_CASE("a bad layer is rejected and leaves the data unchanged", "[extend][errors]")
{
    auto gen = make_loaded_generator();
    const auto hash = gen.data_hash();
    using dasmig::property_table;

    REQUIRE_THROWS_WITH(gen.extend_from_string(property_table::costs,
                                               "country_code\ttenure\tlog_mean\tlog_sd\nDE\ttenant_market\t-1.5\twide\n",
                                               "bad.tsv"),
                        "bad.tsv:2: column 'log_sd': expected a number, got 'wide'");
    REQUIRE_THROWS_AS(gen.extend_from_string(property_table::types,
                                             "country_code\tarea\tdetached\tsemi_detached\tflat_small\tflat_large\tinformal\tother\n"
                                             "DE\tsuburb\t1\t0\t0\t0\t0\t0\n",
                                             "area.tsv"),
                      dasmig::core::tsv_error);
    REQUIRE_THROWS_AS(gen.extend_from_string(property_table::tenures,
                                             "country_code\thousehold_type\towner_outright\towner_mortgage\ttenant_market\ttenant_reduced\n"
                                             "DE\tall\t0.5\t0.5\t-0.1\t0\n",
                                             "negative.tsv"),
                      dasmig::core::tsv_error);
    REQUIRE_THROWS_AS(gen.extend_from_string(property_table::periods, "country_code\tfrom\tto\nDE\t1900\t1910\n", "partial.tsv"),
                      dasmig::core::tsv_error); // required column missing
    // A country with no other table does not fit.
    REQUIRE_THROWS_AS(gen.extend_from_string(property_table::countries,
                                             "country_code\tpopulation\tcurrency\tcurrency_digits\tcity\ttown\trural\n"
                                             "ZZ\t1000\tEUR\t2\t0.5\t0.3\t0.2\n",
                                             "new.tsv"),
                      std::invalid_argument);
    REQUIRE_THROWS_AS(gen.extend(std::filesystem::path{"houses.tsv"}), std::invalid_argument);

    REQUIRE(gen.data_hash() == hash);
    REQUIRE(gen.layers(property_table::countries).size() == 1);
    REQUIRE(gen.countries().size() == 199);
}

#ifdef DASMIG_PROPERTY_EMBED
TEST_CASE("compiled-in data needs no files and matches them", "[embed]")
{
    const auto old_cwd = std::filesystem::current_path();
    const auto tmp = std::filesystem::temp_directory_path() / "pty_embed_dir";
    std::filesystem::create_directories(tmp);
    std::filesystem::current_path(tmp);
    dasmig::pty gen;
    const bool loaded = gen.load(dasmig::dataset::lite);
    std::filesystem::current_path(old_cwd);
    std::filesystem::remove_all(tmp);

    REQUIRE(loaded);
    REQUIRE(gen.layers(dasmig::property_table::countries).front().source == "embedded:lite/countries.tsv");
    REQUIRE(gen.data_hash() == 0x4a55196d601f537dULL); // same as the files
    REQUIRE(gen.get_property(property_request{}, std::uint64_t{1}).to_json() ==
            R"({"country_code":"ES","area":"town","household_type":"single_parent","household_size":2,"type":"flat_small","holding":"owner_mortgage","rooms":4,"bedrooms":1,"floor_area":56,"year_built":1989,"monthly_cost":null,"evidence":"modelled","signature":{"seed":"0000000000000001","data":"4a55196d601f537d"}})");
}
#endif

// ---------------------------------------------------------------------------
// Batch generation
// ---------------------------------------------------------------------------

TEST_CASE("property batch: items equal the single calls for any thread count", "[batch]")
{
    auto gen = make_loaded_generator();
    const auto request = property_request{};
    const auto batch = gen.get_property_batch(request, {.count = 200, .threads = 1}, 77);
    REQUIRE(batch.size() == 200);
    for (std::uint64_t i = 0; i < batch.size(); ++i)
    {
        REQUIRE(batch[i].to_json() == gen.get_property(request, dasmig::core::item_seed(77, i)).to_json());
    }

    // A range is computed directly, on any number of threads.
    const auto tail = gen.get_property_batch(request, {.count = 100, .first = 100, .threads = 4}, 77);
    REQUIRE(tail.size() == 100);
    for (std::size_t i = 0; i < tail.size(); ++i)
    {
        REQUIRE(tail[i].to_json() == batch[100 + i].to_json());
    }
    for (const std::size_t threads : {2U, 7U, 0U})
    {
        const auto other = gen.get_property_batch(request, {.count = 200, .threads = threads}, 77);
        REQUIRE(other.size() == batch.size());
        for (std::size_t i = 0; i < other.size(); ++i)
        {
            REQUIRE(other[i].to_json() == batch[i].to_json());
        }
    }

    // Without a seed the batch still has the requested size.
    REQUIRE(gen.get_property_batch(request, {.count = 5}).size() == 5);
}

TEST_CASE("property batch: streaming gives the same items in order", "[batch]")
{
    auto gen = make_loaded_generator();
    const auto request = property_request{};
    const auto batch = gen.get_property_batch(request, {.count = 300, .first = 10, .threads = 3}, 5);
    std::uint64_t next = 10;
    std::size_t seen = 0;
    gen.for_each_property(request, {.count = 300, .first = 10, .threads = 3}, 5,
                          [&](std::uint64_t index, const dasmig::property& item)
                          {
                              REQUIRE(index == next);
                              REQUIRE(item.to_json() == batch[seen].to_json());
                              ++next;
                              ++seen;
                          });
    REQUIRE(seen == batch.size());
}

TEST_CASE("property batch: known answer of 10,000 items", "[batch][kat]")
{
    auto gen = make_loaded_generator();
    const auto request = property_request{};
    std::uint64_t hash = 0xcbf29ce484222325ULL;
    gen.for_each_property(request, {.count = 10000, .threads = 4}, 1,
                          [&](std::uint64_t, const dasmig::property& item)
                          { hash = dasmig::core::hash_combine(hash, dasmig::core::fnv1a64(item.to_json())); });
    REQUIRE(hash == 0x25ed3a5dc34bedc2ULL);
}
