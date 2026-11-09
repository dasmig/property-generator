// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Diego Dasso Migotto

#ifndef DASMIG_PROPERTYGEN_HPP
#define DASMIG_PROPERTYGEN_HPP

#include "core.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <ostream>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef DASMIG_PROPERTY_EMBED
#include "propertygen_data.hpp"
#endif

/// @file propertygen.hpp
/// @brief Property Generator library — homes for households: dwelling type, tenure, rooms, floor area, year built and housing cost, by country for C++23.
/// @author Diego Dasso Migotto (diegomigotto at hotmail dot com)
/// @see See doc/usage.md for the narrative tutorial and doc/data.md for the sources.

DASMIG_CORE_REQUIRE(1, 1);

namespace dasmig
{

/// @brief The kind of building a home is in.
enum class dwelling_type : std::uint8_t
{
    detached,      ///< A house standing on its own.
    semi_detached, ///< A house sharing a wall: semi-detached or terraced.
    flat_small,    ///< A flat in a building of fewer than ten dwellings.
    flat_large,    ///< A flat in a building of ten dwellings or more.
    informal,      ///< A shack or makeshift dwelling.
    other          ///< Rooms in a shared building, a mobile home, quarters attached to other premises.
};

/// @brief How the household holds its home.
enum class tenure : std::uint8_t
{
    owner_outright, ///< Owner without a mortgage or loan.
    owner_mortgage, ///< Owner repaying a mortgage or loan.
    tenant_market,  ///< Tenant at the market rent.
    tenant_reduced  ///< Tenant at a reduced rent (social, employer) or rent-free.
};

/// @brief Degree of urbanisation of the place.
enum class settlement : std::uint8_t
{
    city,  ///< A city (50,000 people and over).
    town,  ///< A town or suburb (5,000 to 49,999).
    rural  ///< A rural area.
};

/// @brief The data tables (see doc/data.md).
enum class property_table : std::uint8_t
{
    countries,   ///< countries.tsv: population, currency, area shares.
    households,  ///< households.tsv: household types and sizes.
    types,       ///< types.tsv: dwelling type shares by area.
    type_odds,   ///< type_odds.tsv: dwelling type odds by household size.
    tenures,     ///< tenures.tsv: tenure base shares by household type.
    tenure_odds, ///< tenure_odds.tsv: tenure odds by age, household and dwelling type.
    rooms,       ///< rooms.tsv: rooms by building group and household size.
    bedrooms,    ///< bedrooms.tsv: bedrooms given rooms.
    dwellings,   ///< dwellings.tsv: the rooms tilt and floor area per room by country.
    periods,     ///< periods.tsv: periods of construction.
    costs        ///< costs.tsv: housing cost burden by tenure.
};

/// @brief The key of a dwelling type, as in the tables and JSON.
/// @param t The type.
/// @return For example `"flat_large"`.
[[nodiscard]] constexpr std::string_view to_string(dwelling_type t) noexcept
{
    constexpr std::array<std::string_view, 6> names{"detached", "semi_detached", "flat_small",
                                                    "flat_large", "informal",     "other"};
    return names.at(static_cast<std::size_t>(t));
}

/// @brief The key of a tenure, as in the tables and JSON.
/// @param t The tenure.
/// @return For example `"tenant_market"`.
[[nodiscard]] constexpr std::string_view to_string(tenure t) noexcept
{
    constexpr std::array<std::string_view, 4> names{"owner_outright", "owner_mortgage", "tenant_market",
                                                    "tenant_reduced"};
    return names.at(static_cast<std::size_t>(t));
}

/// @brief The key of a settlement, as in the tables and JSON.
/// @param s The settlement.
/// @return `"city"`, `"town"` or `"rural"`.
[[nodiscard]] constexpr std::string_view to_string(settlement s) noexcept
{
    constexpr std::array<std::string_view, 3> names{"city", "town", "rural"};
    return names.at(static_cast<std::size_t>(s));
}

/// @brief The household types, in relationship-generator's names.
inline constexpr std::array<std::string_view, 7> property_household_types{
    "one_person", "couple", "nuclear", "single_parent", "with_parents", "multi_generation", "other"};

// NOLINTBEGIN(readability-redundant-member-init)

/// @brief What a property call asks for.
///
/// Every generation call takes one; `property_request{}` asks for the
/// defaults. Choices are never stored on the generator, so one call cannot
/// change the next. A given field is used as it is and the rest is drawn to
/// fit it (doc/usage.md).
struct property_request
{
    /// @brief The default reference date, 2023-07-01 (as id-generator and
    ///        finance-generator).
    static constexpr std::chrono::year_month_day default_reference_date{
        std::chrono::year{2023}, std::chrono::month{7}, std::chrono::day{1}};

    std::optional<std::string> country{};            ///< ISO alpha-2; unset: drawn by population.
    std::optional<settlement> area{};                ///< Unset: from place_population, else drawn.
    std::optional<std::uint64_t> place_population{}; ///< The place's population (city-generator); sets `area`.
    std::optional<std::uint8_t> household_size{};    ///< People in the household, 1 or more; unset: drawn.
    std::optional<std::string> household_type{};     ///< One of property_household_types; unset: drawn.
    std::optional<std::uint8_t> children{};          ///< Members under 18; the household is drawn to hold them.
    std::optional<std::uint8_t> anchor_age{};        ///< The reference person's age, 16 to 110; unset: 18 to 80.
    std::optional<core::money> household_income{};   ///< Gross annual, in the country's currency; enables monthly_cost.
    std::optional<dwelling_type> type{};             ///< Forced; the rest is drawn to fit.
    std::optional<tenure> holding{};                 ///< Forced; the rest is drawn to fit.
    std::chrono::year_month_day reference_date{default_reference_date}; ///< No home is built after it.
    bool weighted{true}; ///< False: countries are drawn uniformly, the rest still by the data.
};

/// @brief The evidence behind each field of one country's data.
///
/// Each is `"measured"` (a source for the country), `"modelled"` (the
/// country's figures through a stated model) or `"filled"` (other
/// countries' figures).
struct property_evidence
{
    std::string area;       ///< City, town and rural shares.
    std::string household;  ///< Household types and sizes.
    std::string type;       ///< Dwelling type shares.
    std::string tenure;     ///< Tenure shares.
    std::string rooms;      ///< Rooms.
    std::string floor_area; ///< Floor area per room.
    std::string period;     ///< Periods of construction.
    std::string cost;       ///< Housing cost burden.

    /// @brief One line: `area=measured household=measured ...`.
    /// @return The summary.
    [[nodiscard]] std::string to_string() const
    {
        return "area=" + area + " household=" + household + " type=" + type + " tenure=" + tenure +
               " rooms=" + rooms + " floor_area=" + floor_area + " period=" + period + " cost=" + cost;
    }
};

/// @brief A home: what building, how it is held, its size and age and, with
///        an income, what it costs.
///
/// Supports implicit conversion to std::string (the summary), streaming via
/// operator<< and JSON output via to_json().
class property
{
  public:
    std::string country_code;              ///< ISO alpha-2.
    settlement area{settlement::city};     ///< Degree of urbanisation.
    std::string household_type;            ///< One of property_household_types.
    std::uint8_t household_size{0};        ///< People in the household (given or drawn).
    dwelling_type type{dwelling_type::detached}; ///< The building.
    tenure holding{tenure::owner_outright};      ///< How it is held.
    std::uint8_t rooms{0};                 ///< Habitable rooms, the kitchen counted, bathrooms not.
    std::uint8_t bedrooms{0};              ///< Bedrooms; 0 for a studio, and for some homes of two rooms.
    std::uint16_t floor_area{0};           ///< Square metres.
    std::uint16_t year_built{0};           ///< Year of construction.
    std::optional<core::money> monthly_cost{}; ///< Rent, or the owner's mortgage and charges; with an income only.
    std::string evidence;                  ///< The weakest evidence of the data used.

    /// @brief True for a flat: the caller asks address-generator for a unit.
    /// @return Whether the home is a flat in a building.
    [[nodiscard]] bool in_building() const
    {
        return type == dwelling_type::flat_small || type == dwelling_type::flat_large;
    }

    /// @brief Retrieve the random seed used to generate this property.
    /// @return The call seed; pass it to get_property(request, seed) with
    ///         the same request and data to replay this property.
    [[nodiscard]] std::uint64_t seed() const { return _signature.seed; }

    /// @brief The seed and the data this property was generated from.
    /// @return The replay signature; `data` is pty::data_hash() at the
    ///         time of generation.
    [[nodiscard]] const core::seed_signature& signature() const { return _signature; }

    /// @brief Human-readable summary.
    /// @return For example `"DE, city, flat in a large building, tenant at
    ///         market rent, 3 rooms (2 bedrooms), 74 m², built 1968"`.
    [[nodiscard]] std::string to_string() const
    {
        constexpr std::array<std::string_view, 6> types{
            "detached house", "semi-detached or terraced house", "flat in a small building",
            "flat in a large building", "informal dwelling", "other dwelling"};
        constexpr std::array<std::string_view, 4> holdings{
            "owner without a mortgage", "owner with a mortgage", "tenant at market rent",
            "tenant at a reduced rent or rent-free"};
        std::string out = country_code + ", " + std::string{dasmig::to_string(area)} + ", " +
                          std::string{types.at(static_cast<std::size_t>(type))} + ", " +
                          std::string{holdings.at(static_cast<std::size_t>(holding))} + ", " +
                          std::to_string(rooms) + (rooms == 1 ? " room" : " rooms");
        if (rooms == 1) out += " (studio)";
        else if (bedrooms == 0) out += " (no bedroom)";
        else out += " (" + std::to_string(bedrooms) + (bedrooms == 1 ? " bedroom)" : " bedrooms)");
        out += ", " + std::to_string(floor_area) + " m², built " + std::to_string(year_built);
        if (monthly_cost) out += ", " + monthly_cost->decimal() + " " + monthly_cost->currency + " a month";
        return out;
    }

    /// @brief Write this property as a JSON object.
    /// @param w Writer positioned where a value is allowed.
    void to_json(core::json_writer& w) const
    {
        w.begin_object()
            .field("country_code", country_code)
            .field("area", dasmig::to_string(area))
            .field("household_type", household_type)
            .field("household_size", static_cast<unsigned>(household_size))
            .field("type", dasmig::to_string(type))
            .field("holding", dasmig::to_string(holding))
            .field("rooms", static_cast<unsigned>(rooms))
            .field("bedrooms", static_cast<unsigned>(bedrooms))
            .field("floor_area", static_cast<unsigned>(floor_area))
            .field("year_built", static_cast<unsigned>(year_built))
            .key("monthly_cost");
        if (monthly_cost) monthly_cost->write_json(w);
        else w.value(nullptr);
        w.field("evidence", evidence).key("signature");
        _signature.to_json(w);
        w.end_object();
    }

    /// @brief This property as a JSON document.
    /// @return Compact JSON, for example `{"country_code":"DE","area":"city",...}`.
    [[nodiscard]] std::string to_json() const
    {
        core::json_writer w;
        to_json(w);
        return w.str();
    }

    /// @brief Implicit conversion to std::string.
    /// @return Summary string.
    operator std::string() const // NOLINT(hicpp-explicit-conversions)
    {
        return to_string();
    }

    /// @brief Stream the summary to an output stream.
    /// @param os Output stream.
    /// @param v The property to stream.
    /// @return The stream.
    friend std::ostream& operator<<(std::ostream& os, const property& v)
    {
        os << v.to_string();
        return os;
    }

  private:
    core::seed_signature _signature;
    friend class pty;
};

// NOLINTEND(readability-redundant-member-init)

/// @cond INTERNAL
namespace propertygen_detail
{

inline constexpr std::size_t type_count = 6;
inline constexpr std::size_t tenure_count = 4;
inline constexpr std::size_t area_count = 3;
inline constexpr std::size_t household_type_count = 7;
inline constexpr std::size_t group_count = 3;
inline constexpr std::size_t max_rooms = 10;
inline constexpr std::size_t max_size = 6;       // rooms and types by household size 1..6 (6 = 6 or more)
inline constexpr std::size_t max_household = 10; // household sizes 1..10 (10 = 10 or more)
inline constexpr std::size_t age_band_count = 6;
inline constexpr int type_factor_rounds = 30;    // as scripts/prepare_tables.py type_factors()

inline constexpr std::array<std::string_view, type_count> type_keys{"detached", "semi_detached", "flat_small",
                                                                    "flat_large", "informal",     "other"};
inline constexpr std::array<std::string_view, tenure_count> tenure_keys{"owner_outright", "owner_mortgage",
                                                                        "tenant_market", "tenant_reduced"};
inline constexpr std::array<std::string_view, area_count> area_keys{"city", "town", "rural"};
inline constexpr std::array<std::string_view, group_count> group_keys{"house", "flat", "other"};
inline constexpr std::array<std::string_view, age_band_count> age_bands{"16-24", "25-34", "35-44",
                                                                        "45-54", "55-64", "65-120"};
// The building group of each dwelling type: house, flat, other.
inline constexpr std::array<std::size_t, type_count> group_of{0, 0, 1, 1, 2, 2};

using type_vec = std::array<double, type_count>;
using tenure_vec = std::array<double, tenure_count>;
using room_vec = std::array<double, max_rooms>;

enum class evidence_level : std::uint8_t
{
    measured,
    modelled,
    filled
};

inline evidence_level parse_evidence(std::string_view text)
{
    if (text.empty() || text == "measured") return evidence_level::measured;
    if (text == "modelled") return evidence_level::modelled;
    if (text == "filled") return evidence_level::filled;
    throw std::invalid_argument("unknown evidence '" + std::string{text} + "'");
}

inline std::string evidence_name(evidence_level e)
{
    constexpr std::array<std::string_view, 3> names{"measured", "modelled", "filled"};
    return std::string{names.at(static_cast<std::size_t>(e))};
}

// The evidence of a row's column, or measured when the column is absent (a user's layer).
inline evidence_level row_evidence(const core::tsv_row& row, std::string_view column)
{
    return parse_evidence(row.has(column) ? row[column] : std::string_view{});
}

inline void weaken(evidence_level& e, evidence_level by) { e = std::max(e, by); }

template <std::size_t N>
std::optional<std::size_t> index_of(const std::array<std::string_view, N>& keys, std::string_view text)
{
    for (std::size_t i = 0; i < N; ++i)
    {
        if (keys.at(i) == text) return i;
    }
    return std::nullopt;
}

inline std::string upper(std::string_view text)
{
    std::string out{text};
    for (auto& c : out)
    {
        if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
    }
    return out;
}

// A weighted choice by linear scan over weight(0), ..., weight(n - 1): the
// first positive weight whose running sum exceeds uniform01 * total, else the
// last positive one. One engine value.
template <typename Weight>
std::size_t pick_by(core::rng& r, std::size_t n, Weight weight)
{
    double total = 0.0;
    for (std::size_t i = 0; i < n; ++i) total += weight(i);
    if (!(total > 0.0) || !std::isfinite(total)) throw std::invalid_argument("no positive weight to draw from");
    const double target = core::uniform01(r) * total;
    double acc = 0.0;
    std::size_t last = 0;
    for (std::size_t i = 0; i < n; ++i)
    {
        const double w = weight(i);
        if (!(w > 0.0)) continue;
        acc += w;
        last = i;
        if (target < acc) return i;
    }
    return last;
}

inline std::size_t pick(core::rng& r, std::span<const double> weights)
{
    return pick_by(r, weights.size(), [&](std::size_t i) { return weights[i]; });
}

struct band
{
    int from{0};
    int to{0};
    double share{0.0};
};

struct evidence_set
{
    evidence_level area{};
    evidence_level household{};
    evidence_level type{};
    evidence_level tenure{};
    evidence_level rooms{};
    evidence_level floor_area{};
    evidence_level period{};
    evidence_level cost{};
};

// The household asked for: type, size and children, each optional.
struct household_wish
{
    std::optional<std::size_t> type;
    std::optional<std::size_t> size;
    std::size_t children{0};
};

// What a draw has fixed so far.
struct draw_context
{
    std::size_t area{0};
    std::size_t household{0};
    std::size_t bucket{0}; // household size 1..6, less one
    int age{0};
    std::size_t type{0};
};

struct country_model
{
    std::string code;
    std::string currency;
    std::uint8_t digits{2};
    double population{0.0};
    std::array<double, area_count> area_share{};
    std::array<double, household_type_count> household_share{};
    std::array<std::array<double, max_household>, household_type_count> household_size{};
    std::array<type_vec, area_count> type_share{};
    std::array<type_vec, area_count> type_factor{};
    tenure_vec tenure_all{};
    std::array<std::optional<tenure_vec>, household_type_count> tenure_by_household{};
    std::array<double, group_count> rooms_tilt{};
    std::array<double, group_count> rooms_shift{}; // the base moved down this many rooms, then tilted; 0 by default
    std::array<double, group_count> m2_log_mean{};
    std::array<double, group_count> m2_log_sd{};
    std::array<double, group_count> m2_rooms_power{1.0, 1.0, 1.0}; // floor area grows as rooms^power
    std::array<std::array<room_vec, max_size>, group_count> rooms{}; // P(rooms | group, size), tilted
    std::vector<band> periods;                                       // sorted by `from`
    tenure_vec cost_log_mean{};
    tenure_vec cost_log_sd{};
    tenure_vec cost_below{};      // the log burden's slope on log(income / reference_income) below 0
    tenure_vec cost_above{};      // and above it
    double reference_income{0.0}; // 0: the burden does not depend on income
    evidence_set evidence;

    // What the tables gave, checked when the model is built.
    unsigned household_rows{0};
    unsigned type_areas{0};   // a bit per area
    bool tenure_all_row{false};
    unsigned groups{0};       // a bit per building group
    unsigned cost_tenures{0}; // a bit per tenure
};

struct model
{
    std::vector<country_model> countries; // sorted by code
    std::unordered_map<std::string, std::uint32_t> index;
    std::vector<double> population;       // for weighted country draws
    std::vector<double> present;          // 1 for a country with people: unweighted draws
    std::array<type_vec, max_size> type_odds{};
    std::array<tenure_vec, age_band_count> tenure_age{};
    std::array<tenure_vec, household_type_count> tenure_household{};
    std::array<tenure_vec, type_count> tenure_type{};
    std::array<room_vec, max_rooms> bedrooms{}; // [rooms - 1][bedrooms]
};

using country_map = std::map<std::string, country_model, std::less<>>;
using room_base = std::array<std::array<std::optional<room_vec>, max_size>, group_count>;

} // namespace propertygen_detail
/// @endcond


/// @brief Property Generator: homes for households, by country.
///
/// The call seed splits into the streams `"country"`, `"area"`,
/// `"household"`, `"age"`, `"type"`, `"tenure"`, `"rooms"`, `"area_m2"`,
/// `"year"` and `"cost"`. A given field skips its draw and leaves every
/// other stream's draws unchanged (its value may still move, since later
/// fields are conditioned on it). Output is identical on every compiler and
/// platform (dasmig-core).
///
/// Can be used as a singleton via instance() or constructed independently.
///
/// @par Thread safety
/// Each instance is independent. Concurrent calls to get_property(request)
/// on the **same** instance require external synchronisation; the seeded
/// overloads are const and may run concurrently.
class pty
{
  public:
    /// @brief Default constructor — creates an empty generator with no data.
    pty() = default;

    pty(const pty&) = delete;                 ///< Not copyable.
    pty& operator=(const pty&) = delete;      ///< Not copyable.
    pty(pty&&) noexcept = default;            ///< Movable.
    pty& operator=(pty&&) noexcept = default; ///< Movable.
    ~pty() = default;                         ///< Destructor.

    /// @brief Access the global singleton instance.
    ///
    /// Loads the `lite` tier (or `full` if `lite` is missing) on first
    /// access, from compiled-in data or an auto-probed `resources/`.
    /// @return The singleton.
    static pty& instance()
    {
        static pty inst{auto_probe_tag{}};
        return inst;
    }

    // -- Generation -------------------------------------------------------

    /// @brief Generate a random property.
    /// @param request What to generate; property_request{} for the defaults.
    /// @return The property.
    /// @throws std::runtime_error If no data has been loaded.
    /// @throws std::invalid_argument If the request is invalid.
    [[nodiscard]] property get_property(const property_request& request)
    {
        return get_property(request, draw_seed_());
    }

    /// @brief Generate a deterministic property.
    /// @param request What to generate.
    /// @param call_seed Seed; the same request, seed and data give the same
    ///        result. Does not touch the instance engine.
    /// @return The property.
    /// @throws std::runtime_error If no data has been loaded.
    /// @throws std::invalid_argument If the request is invalid: an unknown
    ///         country or household type, a household that cannot hold the
    ///         given children or size, an age outside 16 to 110, an income
    ///         in another currency or negative, an invalid reference date or
    ///         one before the earliest period of construction.
    [[nodiscard]] property get_property(const property_request& request, std::uint64_t call_seed) const
    {
        namespace d = propertygen_detail;
        require_data_();
        if (!request.reference_date.ok()) throw std::invalid_argument("property_request: invalid reference_date");
        const int reference_year = static_cast<int>(request.reference_date.year());
        const core::rng call{call_seed};

        const d::country_model& c = request.country ? country_or_throw_(*request.country)
                                                    : draw_country_(call.split("country"), request.weighted);
        auto evidence = d::evidence_level::measured;
        d::draw_context at;
        at.area = pick_area_(c, request, call, evidence);
        const auto [household, size] = draw_household_(c, request, call);
        if (!request.household_type || !request.household_size) d::weaken(evidence, c.evidence.household);
        at.household = household;
        at.bucket = std::min<std::size_t>(size, d::max_size) - 1;
        at.age = anchor_age_(request, call);
        at.type = pick_type_(c, request, call, at, evidence);
        const std::size_t holding = pick_tenure_(c, request, call, at, evidence);

        property out;
        out._signature = {.seed = call_seed, .data = data_hash()};
        out.country_code = c.code;
        out.area = static_cast<settlement>(at.area);
        out.household_type = std::string{property_household_types.at(household)};
        out.household_size = static_cast<std::uint8_t>(size);
        out.type = static_cast<dwelling_type>(at.type);
        out.holding = static_cast<tenure>(holding);
        draw_size_(c, call, at, out);
        out.year_built = draw_year_(c, call, reference_year);
        d::weaken(evidence, std::max({c.evidence.rooms, c.evidence.floor_area, c.evidence.period}));
        if (request.household_income)
        {
            out.monthly_cost = draw_cost_(c, *request.household_income, call, holding);
            d::weaken(evidence, c.evidence.cost);
        }
        out.evidence = d::evidence_name(evidence);
        return out;
    }

    // -- Batch generation -------------------------------------------------

    /// @brief Generate a batch of property results from a seed drawn like
    ///        get_property() draws its own.
    /// @param request What every item is generated from.
    /// @param options Count, first index, threads and uniqueness.
    /// @return The results, in index order.
    [[nodiscard]] std::vector<property> get_property_batch(const property_request& request,
                                                           const core::batch_options& options)
    {
        return get_property_batch(request, options, draw_seed_());
    }

    /// @brief Generate a batch of property results, deterministically.
    ///
    /// Item `i` is exactly `get_property(request, core::item_seed(batch_seed,
    /// options.first + i))`, so an item replays on its own, a range can be
    /// generated directly, two batches that follow each other equal one, and
    /// the output does not depend on `options.threads`.
    ///
    /// @param request What every item is generated from.
    /// @param options Count, first index, threads and uniqueness (see
    ///        core::unique_rule; the rule must be made for `property`).
    /// @param batch_seed Seed of the whole batch.
    /// @return The results, in index order.
    /// @throws std::invalid_argument If the request or options are invalid.
    /// @throws std::runtime_error If no data has been loaded, or a unique
    ///         batch runs out of attempts.
    [[nodiscard]] std::vector<property> get_property_batch(const property_request& request,
                                                           const core::batch_options& options,
                                                           std::uint64_t batch_seed) const
    {
        return core::run_batch(options, batch_seed,
                               [&](std::uint64_t item_seed) { return get_property(request, item_seed); });
    }

    /// @brief Stream a batch of property results to a sink without holding
    ///        the whole batch.
    ///
    /// Generates the same items as get_property_batch() and calls
    /// `sink(index, item)` in index order on the calling thread; `index`
    /// includes `options.first`.
    ///
    /// @tparam Sink Callable taking `(std::uint64_t, property&)`; for example
    ///         core::jsonl_writer or core::csv_writer.
    /// @param request What every item is generated from.
    /// @param options Count, first index, threads and uniqueness.
    /// @param batch_seed Seed of the whole batch.
    /// @param sink Receives the items.
    template <typename Sink>
    void for_each_property(const property_request& request, const core::batch_options& options,
                           std::uint64_t batch_seed, Sink&& sink) const
    {
        core::for_each_batch(options, batch_seed, [&](std::uint64_t item_seed) { return get_property(request, item_seed); },
                             std::forward<Sink>(sink));
    }

    /// @brief Stream a batch of property results with a batch seed drawn
    ///        like get_property() draws its own.
    /// @tparam Sink Callable taking `(std::uint64_t, property&)`.
    /// @param request What every item is generated from.
    /// @param options Count, first index, threads and uniqueness.
    /// @param sink Receives the items.
    template <typename Sink>
    void for_each_property(const property_request& request, const core::batch_options& options, Sink&& sink)
    {
        for_each_property(request, options, draw_seed_(), std::forward<Sink>(sink));
    }

    // -- Queries ----------------------------------------------------------

    /// @brief The countries served.
    /// @return ISO alpha-2 codes, sorted.
    [[nodiscard]] std::vector<std::string> countries() const
    {
        std::vector<std::string> out;
        out.reserve(_model.countries.size());
        for (const auto& c : _model.countries) out.push_back(c.code);
        return out;
    }

    /// @brief The evidence behind each field of a country's data.
    /// @param country ISO alpha-2.
    /// @return Per field: measured, modelled or filled.
    /// @throws std::invalid_argument For an unknown country.
    [[nodiscard]] property_evidence evidence(std::string_view country) const
    {
        namespace d = propertygen_detail;
        const auto& e = country_or_throw_(country).evidence;
        return {.area = d::evidence_name(e.area),
                .household = d::evidence_name(e.household),
                .type = d::evidence_name(e.type),
                .tenure = d::evidence_name(e.tenure),
                .rooms = d::evidence_name(e.rooms),
                .floor_area = d::evidence_name(e.floor_area),
                .period = d::evidence_name(e.period),
                .cost = d::evidence_name(e.cost)};
    }

    // -- Data management --------------------------------------------------

    /// @brief Check whether any data has been loaded.
    /// @return True when the tables are loaded.
    [[nodiscard]] bool has_data() const { return !_model.countries.empty(); }

    /// @brief Load data from a resource directory, replacing all data and
    ///        layers loaded before.
    ///
    /// The directory must contain `countries.tsv`; the other tables are read
    /// when present and must, together, cover every country. A path without
    /// `countries.tsv` is ignored.
    ///
    /// @param dir Directory such as `resources/lite`.
    /// @throws core::tsv_error If a file is malformed; the data is then
    ///         unchanged.
    /// @throws std::invalid_argument If the tables do not fit together.
    void load(const std::filesystem::path& dir)
    {
        std::error_code ec;
        if (!std::filesystem::is_directory(dir, ec) ||
            !std::filesystem::is_regular_file(dir / file_name_(table::countries), ec))
        {
            return;
        }
        apply_(read_directory_(dir), core::layer_mode::replace, true);
    }

    /// @brief Load a dataset tier, replacing all data and layers loaded
    ///        before.
    ///
    /// Uses the compiled-in copy when the library is built with
    /// `DASMIG_PROPERTY_EMBED`, otherwise searches `resources/`,
    /// `../resources`, `property-generator/resources` and
    /// `../property-generator/resources`.
    ///
    /// @param tier The tier.
    /// @return False when the tier was not found.
    /// @throws core::tsv_error If a file is malformed.
    [[nodiscard]] bool load(dataset tier)
    {
        const std::string tier_dir{core::tier_name(tier)};
        const auto marker = tier_dir + "/" + std::string{file_name_(table::countries)};
        const auto root = core::find_resources(library_name_, marker);
        documents docs;
        for (const auto t : all_tables_)
        {
            docs.at(index_(t)) = core::load_resource(tier_dir + "/" + std::string{file_name_(t)}, embedded_files_(), root);
        }
        if (!docs.at(index_(table::countries))) return false;
        apply_(std::move(docs), core::layer_mode::replace, true);
        return true;
    }

    /// @brief Add data layers from a directory or a file.
    ///
    /// A directory may hold any of the table files; all are applied together
    /// or, if any fails, none. A file must have one of those names.
    ///
    /// @param path Directory or file.
    /// @param mode How the layers combine with the data loaded before.
    /// @throws core::tsv_error If a file cannot be read or a row is invalid;
    ///         the data is then unchanged.
    /// @throws std::invalid_argument If @p path is a file with another name,
    ///         or the tables do not fit together.
    void extend(const std::filesystem::path& path, core::layer_mode mode = core::layer_mode::override)
    {
        std::error_code ec;
        if (std::filesystem::is_directory(path, ec))
        {
            apply_(read_directory_(path), mode, false);
            return;
        }
        for (const auto t : all_tables_)
        {
            if (path.filename() == file_name_(t))
            {
                (void)extend(t, core::tsv_document::load(path), mode);
                return;
            }
        }
        throw std::invalid_argument("extend: expected one of the property tables (countries.tsv, types.tsv, ...), got " +
                                    path.filename().string());
    }

    /// @brief Add a data layer to one table.
    ///
    /// Rows are keyed by the table's key columns (see doc/data.md). In the
    /// default override mode a row replaces the loaded row with the same key
    /// and new keys are added; a row with `disabled` set to 1 removes its key.
    ///
    /// @param which The table.
    /// @param doc TSV with that table's columns.
    /// @param mode How the layer combines with the data loaded before.
    /// @return What the layer did (rows added, replaced, removed, warnings).
    /// @throws core::tsv_error If a row is invalid; the data is unchanged.
    /// @throws std::invalid_argument If the tables no longer fit together.
    const core::layer_info& extend(property_table which, core::tsv_document doc,
                                   core::layer_mode mode = core::layer_mode::override)
    {
        documents docs;
        docs.at(index_(which)).emplace(std::move(doc));
        apply_(std::move(docs), mode, false);
        return _tables.at(index_(which)).layers().back();
    }

    /// @brief Add a data layer to one table from TSV text (for example from
    ///        a WebAssembly host).
    /// @param which The table.
    /// @param text TSV with that table's columns.
    /// @param source Name used in errors.
    /// @param mode How the layer combines with the data loaded before.
    /// @return What the layer did.
    /// @throws core::tsv_error If a row is invalid; the data is unchanged.
    const core::layer_info& extend_from_string(property_table which, std::string_view text, std::string source,
                                               core::layer_mode mode = core::layer_mode::override)
    {
        return extend(which, core::tsv_document::parse(text, std::move(source)), mode);
    }

    /// @brief The layers in effect for one table, in order.
    /// @param which The table.
    /// @return The layer records.
    [[nodiscard]] const std::vector<core::layer_info>& layers(property_table which) const
    {
        return _tables.at(index_(which)).layers();
    }

    /// @brief Hash of the loaded data, recorded in each result's signature().
    /// @return A hash that changes when any table does; 0 when nothing is
    ///         loaded.
    [[nodiscard]] std::uint64_t data_hash() const
    {
        std::uint64_t h = 0;
        bool any = false;
        for (const auto& t : _tables)
        {
            any = any || !t.layers().empty();
            h = core::hash_combine(h, t.data_hash());
        }
        return any ? h : 0;
    }

  private:
    using table = property_table;
    using country_model = propertygen_detail::country_model;
    using evidence_level = propertygen_detail::evidence_level;

    // -- Tables -----------------------------------------------------------

    static constexpr std::string_view library_name_ = "property-generator";
    static constexpr std::size_t table_count_ = 11;
    static constexpr std::array<table, table_count_> all_tables_{
        table::countries, table::households, table::types,     table::type_odds, table::tenures, table::tenure_odds,
        table::rooms,     table::bedrooms,   table::dwellings, table::periods,   table::costs};

    using documents = std::array<std::optional<core::tsv_document>, table_count_>;
    using tables = std::array<core::layered_table, table_count_>;

    static constexpr std::size_t index_(table t) { return static_cast<std::size_t>(t); }

    static constexpr std::string_view file_name_(table t)
    {
        constexpr std::array<std::string_view, table_count_> names{
            "countries.tsv", "households.tsv", "types.tsv",     "type_odds.tsv", "tenures.tsv", "tenure_odds.tsv",
            "rooms.tsv",     "bedrooms.tsv",   "dwellings.tsv", "periods.tsv",   "costs.tsv"};
        return names.at(index_(t));
    }

    // The column names prefix + From, ..., prefix + To.
    template <std::size_t From, std::size_t To>
    static std::vector<std::string> numbered_(std::string_view prefix)
    {
        std::vector<std::string> out;
        for (std::size_t i = From; i <= To; ++i) out.push_back(std::string{prefix} + std::to_string(i));
        return out;
    }

    template <std::size_t N>
    static std::vector<std::string> keys_(const std::array<std::string_view, N>& keys)
    {
        return {keys.begin(), keys.end()};
    }

    static core::table_schema schema_(table t)
    {
        namespace d = propertygen_detail;
        switch (t)
        {
        case table::countries:
            return {.key = {"country_code"},
                    .required = {"population", "currency", "currency_digits", "city", "town", "rural"},
                    .optional = {"subregion", "net_to_gross", "reference_income", "area_evidence"}};
        case table::households:
        {
            auto required = numbered_<1, d::max_household>("size_");
            required.insert(required.begin(), "share");
            return {.key = {"country_code", "household_type"}, .required = required, .optional = {"evidence"}};
        }
        case table::types:
            return {.key = {"country_code", "area"}, .required = keys_(d::type_keys), .optional = {"evidence", "source"}};
        case table::type_odds:
            return {.key = {"size"}, .required = keys_(d::type_keys), .optional = {}};
        case table::tenures:
            return {.key = {"country_code", "household_type"},
                    .required = keys_(d::tenure_keys),
                    .optional = {"evidence", "source"}};
        case table::tenure_odds:
            return {.key = {"dimension", "value"}, .required = keys_(d::tenure_keys), .optional = {}};
        case table::rooms:
            return {.key = {"group", "size"}, .required = numbered_<1, d::max_rooms>("r"), .optional = {}};
        case table::bedrooms:
            return {.key = {"rooms"}, .required = numbered_<0, d::max_rooms - 1>("b"), .optional = {}};
        case table::dwellings:
            return {.key = {"country_code", "group"},
                    .required = {"rooms_tilt", "m2_log_mean", "m2_log_sd"},
                    .optional = {"rooms_shift", "m2_rooms_power", "rooms_evidence", "area_evidence", "rooms_source", "area_source"}};
        case table::periods:
            return {.key = {"country_code", "from"}, .required = {"to", "share"}, .optional = {"evidence", "source"}};
        case table::costs:
            return {.key = {"country_code", "tenure"},
                    .required = {"log_mean", "log_sd"},
                    .optional = {"slope_below", "slope_above", "evidence", "source"}};
        }
        return {};
    }

    static tables make_tables_()
    {
        return {core::layered_table{schema_(table::countries)}, core::layered_table{schema_(table::households)},
                core::layered_table{schema_(table::types)},     core::layered_table{schema_(table::type_odds)},
                core::layered_table{schema_(table::tenures)},   core::layered_table{schema_(table::tenure_odds)},
                core::layered_table{schema_(table::rooms)},     core::layered_table{schema_(table::bedrooms)},
                core::layered_table{schema_(table::dwellings)}, core::layered_table{schema_(table::periods)},
                core::layered_table{schema_(table::costs)}};
    }

    static documents read_directory_(const std::filesystem::path& dir)
    {
        documents docs;
        for (const auto t : all_tables_)
        {
            const auto file = dir / file_name_(t);
            std::error_code ec;
            if (std::filesystem::is_regular_file(file, ec)) docs.at(index_(t)) = core::tsv_document::load(file);
        }
        return docs;
    }

    void apply_(documents docs, core::layer_mode mode, bool reset)
    {
        tables next = _tables;
        for (const auto t : all_tables_)
        {
            auto& doc = docs.at(index_(t));
            auto& tbl = next.at(index_(t));
            if (!doc)
            {
                if (reset) tbl.clear();
                continue;
            }
            (void)tbl.extend(std::move(*doc), mode, [t](const core::tsv_row& row) { validate_(t, row); });
        }
        auto built = build_model_(next);
        _tables = std::move(next);
        _model = std::move(built);
    }

    // -- Row checks -------------------------------------------------------

    static double share_(const core::tsv_row& row, std::string_view column)
    {
        const auto v = row.get<double>(column);
        if (!std::isfinite(v) || v < 0.0) throw row.error(column, "must be a non-negative number");
        return v;
    }

    // A whole number from 1 to `most`.
    static std::size_t count_(const core::tsv_row& row, std::string_view column, std::size_t most)
    {
        const auto v = row.get<int>(column);
        if (std::cmp_less(v, 1) || std::cmp_greater(v, most))
        {
            throw row.error(column, "must be 1 to " + std::to_string(most));
        }
        return static_cast<std::size_t>(v);
    }

    template <std::size_t N>
    static std::size_t key_index_(const core::tsv_row& row, std::string_view column,
                                  const std::array<std::string_view, N>& keys)
    {
        const auto i = propertygen_detail::index_of(keys, row[column]);
        if (!i) throw row.error(column, "unknown value '" + std::string{row[column]} + "'");
        return *i;
    }

    template <std::size_t N>
    static void shares_(const core::tsv_row& row, const std::array<std::string_view, N>& columns)
    {
        for (const auto c : columns) (void)share_(row, c);
    }

    static void check_evidence_(const core::tsv_row& row, std::string_view column)
    {
        if (!row.has(column)) return;
        try
        {
            (void)propertygen_detail::parse_evidence(row[column]);
        }
        catch (const std::invalid_argument& e)
        {
            throw row.error(column, e.what());
        }
    }

    static void finite_(const core::tsv_row& row, std::string_view column)
    {
        if (!std::isfinite(row.get<double>(column))) throw row.error(column, "must be finite");
    }

    static void validate_country_(const core::tsv_row& row)
    {
        if (row.get<double>("population") < 0.0) throw row.error("population", "must not be negative");
        const auto currency = row["currency"];
        if (currency.size() != 3 || !std::ranges::all_of(currency, [](char ch) { return ch >= 'A' && ch <= 'Z'; }))
        {
            throw row.error("currency", "must be three capital letters");
        }
        const auto digits = row.get<int>("currency_digits");
        if (digits < 0 || digits > 4) throw row.error("currency_digits", "must be 0 to 4");
        shares_(row, propertygen_detail::area_keys);
        if (row.has("reference_income")) (void)share_(row, "reference_income");
        check_evidence_(row, "area_evidence");
    }

    static void validate_household_(const core::tsv_row& row)
    {
        (void)key_index_(row, "household_type", property_household_types);
        (void)share_(row, "share");
        for (const auto& column : numbered_<1, propertygen_detail::max_household>("size_")) (void)share_(row, column);
        check_evidence_(row, "evidence");
    }

    static void validate_tenure_odds_(const core::tsv_row& row)
    {
        namespace d = propertygen_detail;
        const auto dim = row["dimension"];
        if (dim == "age") (void)key_index_(row, "value", d::age_bands);
        else if (dim == "household") (void)key_index_(row, "value", property_household_types);
        else if (dim == "type") (void)key_index_(row, "value", d::type_keys);
        else throw row.error("dimension", "must be age, household or type");
        shares_(row, d::tenure_keys);
    }

    static void validate_bedrooms_(const core::tsv_row& row)
    {
        const auto rooms = count_(row, "rooms", propertygen_detail::max_rooms);
        for (std::size_t b = 0; b < propertygen_detail::max_rooms; ++b)
        {
            const auto column = "b" + std::to_string(b);
            if (share_(row, column) > 0.0 && b >= std::max<std::size_t>(rooms, 2))
            {
                throw row.error(column, "a home has fewer bedrooms than rooms");
            }
        }
    }

    static void validate_(table t, const core::tsv_row& row)
    {
        namespace d = propertygen_detail;
        switch (t)
        {
        case table::countries: validate_country_(row); return;
        case table::households: validate_household_(row); return;
        case table::types:
            (void)key_index_(row, "area", d::area_keys);
            shares_(row, d::type_keys);
            check_evidence_(row, "evidence");
            return;
        case table::type_odds:
            (void)count_(row, "size", d::max_size);
            shares_(row, d::type_keys);
            return;
        case table::tenures:
            if (row["household_type"] != "all") (void)key_index_(row, "household_type", property_household_types);
            shares_(row, d::tenure_keys);
            check_evidence_(row, "evidence");
            return;
        case table::tenure_odds: validate_tenure_odds_(row); return;
        case table::rooms:
            (void)key_index_(row, "group", d::group_keys);
            (void)count_(row, "size", d::max_size);
            for (const auto& column : numbered_<1, d::max_rooms>("r")) (void)share_(row, column);
            return;
        case table::bedrooms: validate_bedrooms_(row); return;
        case table::dwellings:
            (void)key_index_(row, "group", d::group_keys);
            finite_(row, "rooms_tilt");
            if (row.has("rooms_shift"))
            {
                const auto shift = row.get<double>("rooms_shift");
                if (!(shift >= -9.0 && shift <= 9.0)) throw row.error("rooms_shift", "must be -9 to 9");
            }
            finite_(row, "m2_log_mean");
            (void)share_(row, "m2_log_sd");
            if (row.has("m2_rooms_power"))
            {
                const auto power = row.get<double>("m2_rooms_power");
                if (!(power >= 0.25 && power <= 2.0)) throw row.error("m2_rooms_power", "must be 0.25 to 2");
            }
            check_evidence_(row, "rooms_evidence");
            check_evidence_(row, "area_evidence");
            return;
        case table::periods:
            if (row.get<int>("to") < row.get<int>("from")) throw row.error("to", "must not be before from");
            (void)share_(row, "share");
            check_evidence_(row, "evidence");
            return;
        case table::costs:
            (void)key_index_(row, "tenure", d::tenure_keys);
            finite_(row, "log_mean");
            (void)share_(row, "log_sd");
            if (row.has("slope_below")) finite_(row, "slope_below");
            if (row.has("slope_above")) finite_(row, "slope_above");
            check_evidence_(row, "evidence");
            return;
        }
    }

    // -- The model built from the tables -----------------------------------

    static propertygen_detail::model build_model_(const tables& tbl)
    {
        namespace d = propertygen_detail;
        d::model m;
        const auto& at = [&](table t) -> const core::layered_table& { return tbl.at(index_(t)); };
        if (at(table::countries).empty()) return m;

        auto by_code = read_countries_(at(table::countries));
        read_households_(at(table::households), by_code);
        read_types_(at(table::types), by_code);
        read_tenures_(at(table::tenures), by_code);
        read_dwellings_(at(table::dwellings), by_code);
        read_periods_(at(table::periods), by_code);
        read_costs_(at(table::costs), by_code);
        read_type_odds_(at(table::type_odds), m);
        read_tenure_odds_(at(table::tenure_odds), m);
        read_bedrooms_(at(table::bedrooms), m);
        const auto base = read_rooms_(at(table::rooms));

        for (auto& [code, c] : by_code)
        {
            check_country_(c);
            derive_country_(c, base, m.type_odds);
            m.index.emplace(code, static_cast<std::uint32_t>(m.countries.size()));
            m.population.push_back(c.population);
            m.present.push_back(c.population > 0.0 ? 1.0 : 0.0);
            m.countries.push_back(std::move(c));
        }
        if (!std::ranges::any_of(m.population, [](double p) { return p > 0.0; }))
        {
            throw std::invalid_argument("countries.tsv: no country with a positive population");
        }
        return m;
    }

    static country_model& country_of_(propertygen_detail::country_map& by_code, const core::tsv_row& row,
                                      std::string_view file)
    {
        const auto it = by_code.find(row["country_code"]);
        if (it == by_code.end())
        {
            throw std::invalid_argument(std::string{file} + ": country " + std::string{row["country_code"]} +
                                        " is not in countries.tsv");
        }
        return it->second;
    }

    static propertygen_detail::country_map read_countries_(const core::layered_table& t)
    {
        namespace d = propertygen_detail;
        d::country_map out;
        for (const auto& row : t.rows())
        {
            country_model c;
            c.code = std::string{row["country_code"]};
            c.currency = std::string{row["currency"]};
            c.digits = static_cast<std::uint8_t>(row.get<int>("currency_digits"));
            c.population = row.get<double>("population");
            for (std::size_t a = 0; a < d::area_count; ++a) c.area_share.at(a) = row.get<double>(d::area_keys.at(a));
            c.evidence.area = d::row_evidence(row, "area_evidence");
            if (row.has("reference_income")) c.reference_income = row.get<double>("reference_income");
            auto code = c.code;
            out.emplace(std::move(code), std::move(c));
        }
        return out;
    }

    static void read_households_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "households.tsv");
            const auto h = *d::index_of(property_household_types, row["household_type"]);
            c.household_share.at(h) = row.get<double>("share");
            for (std::size_t i = 0; i < d::max_household; ++i)
            {
                c.household_size.at(h).at(i) = row.get<double>("size_" + std::to_string(i + 1));
            }
            d::weaken(c.evidence.household, d::row_evidence(row, "evidence"));
            ++c.household_rows;
        }
    }

    static void read_types_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "types.tsv");
            const auto a = *d::index_of(d::area_keys, row["area"]);
            for (std::size_t k = 0; k < d::type_count; ++k) c.type_share.at(a).at(k) = row.get<double>(d::type_keys.at(k));
            d::weaken(c.evidence.type, d::row_evidence(row, "evidence"));
            c.type_areas |= 1U << a;
        }
    }

    static void read_tenures_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "tenures.tsv");
            d::tenure_vec v{};
            for (std::size_t k = 0; k < d::tenure_count; ++k) v.at(k) = row.get<double>(d::tenure_keys.at(k));
            if (row["household_type"] == "all")
            {
                c.tenure_all = v;
                c.tenure_all_row = true;
                c.evidence.tenure = d::row_evidence(row, "evidence");
                continue;
            }
            c.tenure_by_household.at(*d::index_of(property_household_types, row["household_type"])) = v;
        }
    }

    static void read_dwellings_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "dwellings.tsv");
            const auto g = *d::index_of(d::group_keys, row["group"]);
            c.rooms_tilt.at(g) = row.get<double>("rooms_tilt");
            c.rooms_shift.at(g) = row.has("rooms_shift") ? row.get<double>("rooms_shift") : 0.0;
            c.m2_log_mean.at(g) = row.get<double>("m2_log_mean");
            c.m2_log_sd.at(g) = row.get<double>("m2_log_sd");
            c.m2_rooms_power.at(g) = row.has("m2_rooms_power") ? row.get<double>("m2_rooms_power") : 1.0;
            d::weaken(c.evidence.rooms, d::row_evidence(row, "rooms_evidence"));
            d::weaken(c.evidence.floor_area, d::row_evidence(row, "area_evidence"));
            c.groups |= 1U << g;
        }
    }

    static void read_periods_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "periods.tsv");
            c.periods.push_back({.from = row.get<int>("from"), .to = row.get<int>("to"), .share = row.get<double>("share")});
            d::weaken(c.evidence.period, d::row_evidence(row, "evidence"));
        }
    }

    static void read_costs_(const core::layered_table& t, propertygen_detail::country_map& by_code)
    {
        namespace d = propertygen_detail;
        for (const auto& row : t.rows())
        {
            auto& c = country_of_(by_code, row, "costs.tsv");
            const auto k = *d::index_of(d::tenure_keys, row["tenure"]);
            c.cost_log_mean.at(k) = row.get<double>("log_mean");
            c.cost_log_sd.at(k) = row.get<double>("log_sd");
            c.cost_below.at(k) = row.has("slope_below") ? row.get<double>("slope_below") : 0.0;
            c.cost_above.at(k) = row.has("slope_above") ? row.get<double>("slope_above") : 0.0;
            d::weaken(c.evidence.cost, d::row_evidence(row, "evidence"));
            c.cost_tenures |= 1U << k;
        }
    }

    // The shared odds tables; a missing row is neutral.
    static void read_type_odds_(const core::layered_table& t, propertygen_detail::model& m)
    {
        namespace d = propertygen_detail;
        for (auto& v : m.type_odds) v.fill(1.0);
        for (const auto& row : t.rows())
        {
            auto& v = m.type_odds.at(static_cast<std::size_t>(row.get<int>("size")) - 1);
            for (std::size_t k = 0; k < d::type_count; ++k) v.at(k) = row.get<double>(d::type_keys.at(k));
        }
    }

    static propertygen_detail::tenure_vec& tenure_odds_row_(propertygen_detail::model& m, const core::tsv_row& row)
    {
        namespace d = propertygen_detail;
        const auto dim = row["dimension"];
        if (dim == "age") return m.tenure_age.at(*d::index_of(d::age_bands, row["value"]));
        if (dim == "household") return m.tenure_household.at(*d::index_of(property_household_types, row["value"]));
        return m.tenure_type.at(*d::index_of(d::type_keys, row["value"]));
    }

    static void read_tenure_odds_(const core::layered_table& t, propertygen_detail::model& m)
    {
        namespace d = propertygen_detail;
        for (auto& v : m.tenure_age) v.fill(1.0);
        for (auto& v : m.tenure_household) v.fill(1.0);
        for (auto& v : m.tenure_type) v.fill(1.0);
        for (const auto& row : t.rows())
        {
            auto& v = tenure_odds_row_(m, row);
            for (std::size_t k = 0; k < d::tenure_count; ++k) v.at(k) = row.get<double>(d::tenure_keys.at(k));
        }
    }

    static void read_bedrooms_(const core::layered_table& t, propertygen_detail::model& m)
    {
        namespace d = propertygen_detail;
        std::array<bool, d::max_rooms> have{};
        for (const auto& row : t.rows())
        {
            const auto rooms = static_cast<std::size_t>(row.get<int>("rooms"));
            for (std::size_t b = 0; b < d::max_rooms; ++b) m.bedrooms.at(rooms - 1).at(b) = row.get<double>("b" + std::to_string(b));
            have.at(rooms - 1) = true;
        }
        for (std::size_t r = 0; r < d::max_rooms; ++r)
        {
            if (!have.at(r)) throw std::invalid_argument("bedrooms.tsv: no row for " + std::to_string(r + 1) + " rooms");
        }
    }

    static propertygen_detail::room_base read_rooms_(const core::layered_table& t)
    {
        namespace d = propertygen_detail;
        d::room_base base{};
        for (const auto& row : t.rows())
        {
            d::room_vec v{};
            for (std::size_t r = 0; r < d::max_rooms; ++r) v.at(r) = row.get<double>("r" + std::to_string(r + 1));
            base.at(*d::index_of(d::group_keys, row["group"])).at(static_cast<std::size_t>(row.get<int>("size")) - 1) = v;
        }
        for (std::size_t g = 0; g < d::group_count; ++g)
        {
            for (std::size_t s = 0; s < d::max_size; ++s)
            {
                if (base.at(g).at(s)) continue;
                throw std::invalid_argument("rooms.tsv: no row for " + std::string{d::group_keys.at(g)} + ", size " +
                                            std::to_string(s + 1));
            }
        }
        return base;
    }

    // Every country needs a row in every table.
    static void check_country_(const country_model& c)
    {
        const auto missing = [&](std::string_view what)
        { return std::invalid_argument("the property tables do not fit together: " + c.code + " has no " + std::string{what}); };
        if (c.household_rows == 0) throw missing("households.tsv rows");
        if (c.type_areas != 0b111U) throw missing("types.tsv row for each of city, town and rural");
        if (!c.tenure_all_row) throw missing("tenures.tsv 'all' row");
        if (c.groups != 0b111U) throw missing("dwellings.tsv row for each of house, flat and other");
        if (c.periods.empty()) throw missing("periods.tsv rows");
        if (c.cost_tenures != 0b1111U) throw missing("costs.tsv row for each tenure");
        if (!std::ranges::any_of(c.household_share, [](double x) { return x > 0.0; }))
        {
            throw missing("household with a positive share");
        }
    }

    // Household sizes 1..6 (6 = 6 or more) over the household types.
    static std::array<double, propertygen_detail::max_size> size_shares_(const country_model& c)
    {
        namespace d = propertygen_detail;
        std::array<double, d::max_size> sizes{};
        double total = 0.0;
        for (std::size_t h = 0; h < d::household_type_count; ++h)
        {
            double row_total = 0.0;
            for (const double p : c.household_size.at(h)) row_total += p;
            if (!(row_total > 0.0)) continue;
            for (std::size_t i = 0; i < d::max_household; ++i)
            {
                const double p = core::math::fenced(c.household_share.at(h) * c.household_size.at(h).at(i)) / row_total;
                sizes.at(std::min(i, d::max_size - 1)) += p;
                total += p;
            }
        }
        for (auto& p : sizes) p /= total;
        return sizes;
    }

    // The arrays a draw reads: periods in order, type factors, P(rooms | group, size) tilted by exp(tilt * rooms).
    static void derive_country_(country_model& c, const propertygen_detail::room_base& base,
                                const std::array<propertygen_detail::type_vec, propertygen_detail::max_size>& type_odds)
    {
        namespace d = propertygen_detail;
        std::ranges::sort(c.periods, {}, &d::band::from);
        const auto sizes = size_shares_(c);
        for (std::size_t a = 0; a < d::area_count; ++a) c.type_factor.at(a) = type_factors_(c.type_share.at(a), sizes, type_odds);
        for (std::size_t g = 0; g < d::group_count; ++g)
        {
            for (std::size_t s = 0; s < d::max_size; ++s)
            {
                const auto& b = c.rooms_shift.at(g) == 0.0 ? *base.at(g).at(s) : shifted_(*base.at(g).at(s), c.rooms_shift.at(g));
                for (std::size_t r = 0; r < d::max_rooms; ++r)
                {
                    c.rooms.at(g).at(s).at(r) = b.at(r) * core::math::exp(c.rooms_tilt.at(g) * static_cast<double>(r + 1));
                }
            }
        }
    }

    // The base moved down `shift` rooms (negative: up), between whole rooms by linear interpolation;
    // what would fall below one room is one room, above the last the last. As scripts/prepare_tables.py
    // shifted().
    static propertygen_detail::room_vec shifted_(const propertygen_detail::room_vec& base, double shift)
    {
        namespace d = propertygen_detail;
        const double lo = std::floor(shift);
        const double frac = shift - lo;
        const auto whole = static_cast<std::ptrdiff_t>(lo);
        const auto last = static_cast<std::ptrdiff_t>(d::max_rooms) - 1;
        d::room_vec out{};
        for (std::ptrdiff_t r = 0; r <= last; ++r)
        {
            const double p = base.at(static_cast<std::size_t>(r));
            out.at(static_cast<std::size_t>(std::clamp(r - whole, std::ptrdiff_t{0}, last))) += p * (1.0 - frac);
            out.at(static_cast<std::size_t>(std::clamp(r - whole - 1, std::ptrdiff_t{0}, last))) += p * frac;
        }
        return out;
    }

    // Per-type factors so that drawing P(type | size) proportional to shares x odds(size) x f over the
    // country's household sizes returns `shares`; the loop of scripts/prepare_tables.py type_factors().
    static propertygen_detail::type_vec type_factors_(const propertygen_detail::type_vec& shares,
                                                      const std::array<double, propertygen_detail::max_size>& sizes,
                                                      const std::array<propertygen_detail::type_vec, propertygen_detail::max_size>& odds)
    {
        namespace d = propertygen_detail;
        d::type_vec f{};
        f.fill(1.0);
        for (int round = 0; round < d::type_factor_rounds; ++round)
        {
            d::type_vec mix{};
            for (std::size_t s = 0; s < d::max_size; ++s)
            {
                d::type_vec w{};
                double total = 0.0;
                for (std::size_t k = 0; k < d::type_count; ++k)
                {
                    w.at(k) = shares.at(k) * odds.at(s).at(k) * f.at(k);
                    total += w.at(k);
                }
                if (!(total > 0.0)) continue;
                for (std::size_t k = 0; k < d::type_count; ++k) mix.at(k) += core::math::fenced(sizes.at(s) * w.at(k)) / total;
            }
            for (std::size_t k = 0; k < d::type_count; ++k)
            {
                if (mix.at(k) > 0.0 && shares.at(k) > 0.0) f.at(k) *= shares.at(k) / mix.at(k);
            }
        }
        return f;
    }

    // -- Requests ------------------------------------------------------------

    [[nodiscard]] const country_model& country_or_throw_(std::string_view code) const
    {
        require_data_();
        const auto it = _model.index.find(propertygen_detail::upper(code));
        if (it == _model.index.end()) throw std::invalid_argument("unknown country '" + std::string{code} + "'");
        return _model.countries.at(it->second);
    }

    [[nodiscard]] const country_model& draw_country_(core::rng r, bool weighted) const
    {
        return _model.countries.at(propertygen_detail::pick(r, weighted ? _model.population : _model.present));
    }

    // Eurostat's thresholds for cities and towns (applied to a place count, not a grid cluster).
    static std::size_t area_of_population_(std::uint64_t people)
    {
        constexpr std::uint64_t city = 50'000;
        constexpr std::uint64_t town = 5'000;
        if (people >= city) return 0;
        if (people >= town) return 1;
        return 2;
    }

    static std::size_t age_band_(int age)
    {
        constexpr std::array<int, 5> upper{24, 34, 44, 54, 64};
        for (std::size_t i = 0; i < upper.size(); ++i)
        {
            if (age <= upper.at(i)) return i;
        }
        return upper.size();
    }

    static std::size_t pick_area_(const country_model& c, const property_request& request, const core::rng& call,
                                  evidence_level& evidence)
    {
        if (request.area) return static_cast<std::size_t>(*request.area);
        if (request.place_population) return area_of_population_(*request.place_population);
        auto r = call.split("area");
        propertygen_detail::weaken(evidence, c.evidence.area);
        return propertygen_detail::pick(r, c.area_share);
    }

    static int anchor_age_(const property_request& request, const core::rng& call)
    {
        if (request.anchor_age)
        {
            const int age = *request.anchor_age;
            if (age < 16 || age > 110) throw std::invalid_argument("property_request: anchor_age must be 16 to 110");
            return age;
        }
        auto r = call.split("age");
        return core::uniform_int(r, 18, 80);
    }

    // The household's type, size and children as asked, checked against each other.
    static propertygen_detail::household_wish wish_of_(const property_request& request)
    {
        propertygen_detail::household_wish w;
        if (request.household_type)
        {
            w.type = propertygen_detail::index_of(property_household_types, *request.household_type);
            if (!w.type) throw std::invalid_argument("unknown household_type '" + *request.household_type + "'");
        }
        if (request.household_size)
        {
            if (*request.household_size == 0) throw std::invalid_argument("property_request: household_size must be 1 or more");
            w.size = *request.household_size;
        }
        w.children = request.children.value_or(0);
        if (w.size && w.children >= *w.size)
        {
            throw std::invalid_argument("property_request: children must be fewer than household_size");
        }
        return w;
    }

    // Whether the (type, size) cell `cell` = type * max_household + size - 1 fits the wish.
    static bool cell_fits_(const propertygen_detail::household_wish& w, std::size_t cell)
    {
        namespace d = propertygen_detail;
        const std::size_t h = cell / d::max_household;
        const std::size_t s = cell % d::max_household;
        if (w.type && h != *w.type) return false;
        if (w.children > 0 && h <= 1) return false; // one_person and couple hold no children
        if (w.size && s != std::min<std::size_t>(*w.size, d::max_household) - 1) return false;
        return s >= w.children;                     // room for the children and an adult
    }

    // The household type and size: a joint draw over (type, size) within the request's constraints.
    [[nodiscard]] static std::pair<std::size_t, std::size_t> draw_household_(const country_model& c,
                                                                             const property_request& request,
                                                                             const core::rng& call)
    {
        namespace d = propertygen_detail;
        const auto wish = wish_of_(request);
        if (wish.type && wish.size)
        {
            // Both given: they must agree, and nothing is drawn.
            const auto bucket = std::min<std::size_t>(*wish.size, d::max_household) - 1;
            if (!(c.household_size.at(*wish.type).at(bucket) > 0.0) || (wish.children > 0 && *wish.type <= 1))
            {
                throw std::invalid_argument("property_request: a " + *request.household_type + " household of " +
                                            std::to_string(*wish.size) + " does not fit");
            }
            return {*wish.type, *wish.size};
        }
        std::array<double, d::household_type_count * d::max_household> w{};
        for (std::size_t i = 0; i < w.size(); ++i)
        {
            if (!cell_fits_(wish, i)) continue;
            const std::size_t h = i / d::max_household;
            w.at(i) = c.household_share.at(h) * c.household_size.at(h).at(i % d::max_household);
        }
        if (!std::ranges::any_of(w, [](double x) { return x > 0.0; }))
        {
            throw std::invalid_argument("property_request: no household of " + c.code + " fits the given type, size and children");
        }
        auto r = call.split("household");
        const auto i = d::pick(r, w);
        return {i / d::max_household, wish.size.value_or((i % d::max_household) + 1)};
    }

    [[nodiscard]] std::size_t pick_type_(const country_model& c, const property_request& request, const core::rng& call,
                                         const propertygen_detail::draw_context& at, evidence_level& evidence) const
    {
        namespace d = propertygen_detail;
        if (request.type) return static_cast<std::size_t>(*request.type);
        auto r = call.split("type");
        d::type_vec w{};
        for (std::size_t k = 0; k < d::type_count; ++k)
        {
            w.at(k) = c.type_share.at(at.area).at(k) * _model.type_odds.at(at.bucket).at(k) * c.type_factor.at(at.area).at(k);
        }
        d::weaken(evidence, c.evidence.type);
        return d::pick(r, w);
    }

    [[nodiscard]] std::size_t pick_tenure_(const country_model& c, const property_request& request, const core::rng& call,
                                           const propertygen_detail::draw_context& at, evidence_level& evidence) const
    {
        namespace d = propertygen_detail;
        if (request.holding) return static_cast<std::size_t>(*request.holding);
        auto r = call.split("tenure");
        const auto& own = c.tenure_by_household.at(at.household);
        const auto& age = _model.tenure_age.at(age_band_(at.age));
        const auto& type = _model.tenure_type.at(at.type);
        d::tenure_vec w{};
        for (std::size_t k = 0; k < d::tenure_count; ++k)
        {
            const double base = own ? own->at(k) : c.tenure_all.at(k) * _model.tenure_household.at(at.household).at(k);
            w.at(k) = base * age.at(k) * type.at(k);
        }
        d::weaken(evidence, c.evidence.tenure);
        return d::pick(r, w);
    }

    // Rooms, bedrooms and floor area: rooms to the group's power (1 by default: rooms times an
    // area per room) times a lognormal.
    void draw_size_(const country_model& c, const core::rng& call, const propertygen_detail::draw_context& at,
                    property& out) const
    {
        namespace d = propertygen_detail;
        const std::size_t group = d::group_of.at(at.type);
        auto rooms_r = call.split("rooms");
        const std::size_t rooms = d::pick(rooms_r, c.rooms.at(group).at(at.bucket)) + 1;
        const std::size_t bedrooms = d::pick(rooms_r, _model.bedrooms.at(rooms - 1));
        auto m2_r = call.split("area_m2");
        const double per_room = core::lognormal(m2_r, c.m2_log_mean.at(group), c.m2_log_sd.at(group));
        const double power = c.m2_rooms_power.at(group);
        const double scale = power == 1.0 ? static_cast<double>(rooms)
                                          : core::math::exp(power * core::math::log(static_cast<double>(rooms)));
        const double m2 = core::math::fenced(scale * per_room);
        out.rooms = static_cast<std::uint8_t>(rooms);
        out.bedrooms = static_cast<std::uint8_t>(bedrooms);
        out.floor_area = static_cast<std::uint16_t>(std::clamp(std::floor(m2 + 0.5), 4.0, 65535.0));
    }

    // Year built: a period, then a year in it, never after the reference year.
    static std::uint16_t draw_year_(const country_model& c, const core::rng& call, int reference_year)
    {
        namespace d = propertygen_detail;
        if (std::ranges::none_of(c.periods, [&](const d::band& b) { return b.from <= reference_year && b.share > 0.0; }))
        {
            throw std::invalid_argument("property_request: reference_date is before the earliest period of construction of " + c.code);
        }
        auto r = call.split("year");
        const auto& period = c.periods.at(d::pick_by(r, c.periods.size(), [&](std::size_t i)
                                                     {
                                                         const auto& b = c.periods.at(i);
                                                         return b.from <= reference_year ? b.share : 0.0;
                                                     }));
        return static_cast<std::uint16_t>(core::uniform_int(r, period.from, std::min(period.to, reference_year)));
    }

    // Housing cost: a lognormal share of gross income, at most all of it, whose median falls as the
    // income rises above the country's reference income (doc/data.md).
    static core::money draw_cost_(const country_model& c, const core::money& income, const core::rng& call,
                                  std::size_t holding)
    {
        if (income.currency != c.currency)
        {
            throw std::invalid_argument("property_request: household_income is in " + income.currency + ", " + c.code +
                                        " uses " + c.currency);
        }
        if (income.minor < 0) throw std::invalid_argument("property_request: household_income is negative");
        auto r = call.split("cost");
        double mu = c.cost_log_mean.at(holding);
        if (c.reference_income > 0.0 && income.minor > 0)
        {
            const double d = core::math::log(income.major() / c.reference_income);
            mu += core::math::fenced((d < 0.0 ? c.cost_below.at(holding) : c.cost_above.at(holding)) * d);
        }
        const double burden = std::min(1.0, core::lognormal(r, mu, c.cost_log_sd.at(holding)));
        return core::money::from_major(income.major() * burden / 12.0, c.currency, c.digits);
    }

    // -- State ------------------------------------------------------------

    tables _tables{make_tables_()};
    propertygen_detail::model _model;
    core::rng _engine{core::rng::from_entropy()};

    struct auto_probe_tag {};

    explicit pty(auto_probe_tag /*tag*/)
    {
        if (!load(dataset::lite)) (void)load(dataset::full);
    }

    // -- Helpers ----------------------------------------------------------

    static std::span<const core::embedded_file> embedded_files_()
    {
#ifdef DASMIG_PROPERTY_EMBED
        return embedded::propertygen::files;
#else
        return {};
#endif
    }

    std::uint64_t draw_seed_() { return _engine(); }

    void require_data_() const
    {
        if (!has_data()) throw std::runtime_error("No property data loaded. Call load() first.");
    }
};

} // namespace dasmig

#endif // DASMIG_PROPERTYGEN_HPP
