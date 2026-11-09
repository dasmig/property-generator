// Draws N homes per country and writes one row of margins per country, for
// scripts/validate_property.py. Usage: sample_property <tier dir> <count> <out.tsv>
//
// Each home is drawn with the country's reference income (countries.tsv; one
// million where it has none), so cost * 12 / income is the burden at the
// income costs.tsv's log_mean is given for.
#include "dasmig/propertygen.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>

namespace
{

double median(std::vector<double>& v)
{
    if (v.empty()) return 0.0;
    const auto mid = v.begin() + static_cast<std::ptrdiff_t>(v.size() / 2);
    std::ranges::nth_element(v, mid);
    return *mid;
}

} // namespace

// The joint structure for one country, for the check against microdata: P(tenure | type),
// P(tenure | age band), P(type | household size) and P(rooms | group, size), as rows of
// table, given, value, share. The anchor's age cycles through 18 to 80, as the default draw does.
struct currency_info
{
    std::string code;
    std::uint8_t digits{2};
    double reference{0.0};
};

int joint(const dasmig::pty& g, const std::string& country, const currency_info& cur, std::uint64_t count, const char* path)
{
    constexpr std::array<const char*, 6> types{"detached", "semi_detached", "flat_small", "flat_large", "informal", "other"};
    constexpr std::array<const char*, 4> tenures{"owner_outright", "owner_mortgage", "tenant_market", "tenant_reduced"};
    constexpr std::array<const char*, 3> groups{"house", "flat", "other"};
    constexpr std::array<int, 6> band_upper{24, 34, 44, 54, 64, 200};
    constexpr std::array<const char*, 6> bands{"16-24", "25-34", "35-44", "45-54", "55-64", "65-120"};
    std::map<std::pair<std::string, std::string>, std::map<std::string, double>> counts;
    dasmig::property_request request;
    request.country = country;
    for (std::uint64_t i = 0; i < count; ++i)
    {
        const auto age = static_cast<std::uint8_t>(18 + (i % 63));
        request.anchor_age = age;
        const auto p = g.get_property(request, i + 1);
        const std::string type = types.at(static_cast<std::size_t>(p.type));
        const std::string holding = tenures.at(static_cast<std::size_t>(p.holding));
        std::size_t band = 0;
        while (age > band_upper.at(band)) ++band;
        const auto size = std::to_string(std::min<int>(p.household_size, 6));
        const std::string group = groups.at(std::array<std::size_t, 6>{0, 0, 1, 1, 2, 2}.at(static_cast<std::size_t>(p.type)));
        counts[{"tenure_given_type", type}][holding] += 1;
        counts[{"tenure_given_age", bands.at(band)}][holding] += 1;
        counts[{"type_given_size", size}][type] += 1;
        counts[{"rooms_given_size", group + "|" + size}][std::to_string(p.rooms)] += 1;
    }
    // The median burden per tenure at multiples of the reference income.
    std::map<std::pair<std::string, std::string>, double> burden;
    for (const std::size_t t : {0U, 1U, 2U})
    {
        for (const double m : {0.25, 0.5, 1.0, 2.0, 4.0})
        {
            dasmig::property_request r;
            r.country = country;
            r.holding = static_cast<dasmig::tenure>(t);
            const double income = cur.reference * m;
            r.household_income = dasmig::core::money::from_major(income, cur.code, cur.digits);
            std::vector<double> b;
            for (std::uint64_t i = 0; i < count / 10; ++i)
            {
                b.push_back(g.get_property(r, i + 1).monthly_cost.value().major() * 12.0 / income);
            }
            burden[{tenures.at(t), std::to_string(static_cast<long long>(income))}] = median(b);
        }
    }
    std::ofstream out{path};
    out << "table\tgiven\tvalue\tshare\tn\n";
    for (const auto& [key, b] : burden)
    {
        out << "burden_given_income\t" << key.first << "|" << key.second << "\tmedian\t" << b << "\t" << count / 10 << "\n";
    }
    for (const auto& [key, dist] : counts)
    {
        double n = 0;
        for (const auto& [value, c] : dist) n += c;
        for (const auto& [value, c] : dist) out << key.first << "\t" << key.second << "\t" << value << "\t" << c / n << "\t" << n << "\n";
    }
    return 0;
}

int main(int argc, char** argv)
{
    if (argc != 4 && !(argc == 6 && std::string{argv[4]} == "--joint"))
    {
        std::cerr << "usage: sample_property <tier dir> <count> <out.tsv> [--joint <country>]\n";
        return 2;
    }
    const std::filesystem::path dir{argv[1]};
    dasmig::pty g;
    g.load(dir);
    if (!g.has_data())
    {
        std::cerr << "no data in " << dir << "\n";
        return 1;
    }
    std::map<std::string, currency_info> currency;
    const auto countries = dasmig::core::tsv_document::load(dir / "countries.tsv");
    for (const auto& row : countries.rows())
    {
        currency[std::string{row["country_code"]}] = {std::string{row["currency"]},
                                                      static_cast<std::uint8_t>(row.get<int>("currency_digits")),
                                                      row.get<double>("reference_income")};
    }
    if (argc == 6) return joint(g, argv[5], currency.at(argv[5]), std::strtoull(argv[2], nullptr, 10), argv[3]);

    const auto count = static_cast<std::uint64_t>(std::strtoull(argv[2], nullptr, 10));
    constexpr std::array<const char*, 6> type_names{"detached", "semi_detached", "flat_small",
                                                    "flat_large", "informal",     "other"};
    constexpr std::array<const char*, 4> tenure_names{"owner_outright", "owner_mortgage", "tenant_market",
                                                      "tenant_reduced"};
    std::ofstream out{argv[3]};
    out << "country\tn";
    for (const auto* k : type_names) out << "\tt_" << k;
    for (const auto* k : tenure_names) out << "\th_" << k;
    out << "\trooms_mean";
    for (int r = 1; r <= 10; ++r) out << "\tr" << r;
    out << "\tbedrooms_mean\tfloor_mean\tyear_mean";
    for (const auto* g : {"house", "flat"}) out << "\tlf_" << g << "_n\tlf_" << g << "_mean\tlf_" << g << "_sd";
    for (const auto* k : tenure_names) out << "\tb_" << k;
    out << "\n";

    constexpr double default_income = 1'000'000.0; // where a country has no reference income
    std::uint64_t seed = 1;
    for (const auto& code : g.countries())
    {
        const auto& cur = currency.at(code);
        const double income_major = cur.reference > 0.0 ? cur.reference : default_income;
        dasmig::property_request request;
        request.country = code;
        request.household_income = dasmig::core::money::from_major(income_major, cur.code, cur.digits);
        std::array<double, 6> types{};
        std::array<double, 4> holdings{};
        std::array<double, 10> rooms{};
        std::array<std::vector<double>, 4> burden;
        double room_sum = 0;
        double bed_sum = 0;
        double floor_sum = 0;
        double year_sum = 0;
        // log floor area by building group (houses: detached and semi-detached; flats: both sizes)
        std::array<double, 2> lf_n{};
        std::array<double, 2> lf_sum{};
        std::array<double, 2> lf_sq{};
        for (std::uint64_t i = 0; i < count; ++i)
        {
            const auto p = g.get_property(request, seed++);
            types.at(static_cast<std::size_t>(p.type)) += 1;
            holdings.at(static_cast<std::size_t>(p.holding)) += 1;
            rooms.at(p.rooms - 1U) += 1;
            room_sum += p.rooms;
            bed_sum += p.bedrooms;
            floor_sum += p.floor_area;
            year_sum += p.year_built;
            const bool house = p.type == dasmig::dwelling_type::detached || p.type == dasmig::dwelling_type::semi_detached;
            if (house || p.in_building())
            {
                const std::size_t group = house ? 0 : 1;
                const double l = std::log(static_cast<double>(p.floor_area));
                lf_n.at(group) += 1;
                lf_sum.at(group) += l;
                lf_sq.at(group) += l * l;
            }
            burden.at(static_cast<std::size_t>(p.holding)).push_back(p.monthly_cost.value().major() * 12.0 / income_major);
        }
        const auto n = static_cast<double>(count);
        out << code << "\t" << count;
        for (const double t : types) out << "\t" << t / n;
        for (const double h : holdings) out << "\t" << h / n;
        out << "\t" << room_sum / n;
        for (const double r : rooms) out << "\t" << r / n;
        out << "\t" << bed_sum / n << "\t" << floor_sum / n << "\t" << year_sum / n;
        for (std::size_t group = 0; group < 2; ++group)
        {
            const double m = lf_n.at(group) > 0 ? lf_sum.at(group) / lf_n.at(group) : 0.0;
            const double v = lf_n.at(group) > 0 ? lf_sq.at(group) / lf_n.at(group) - m * m : 0.0;
            out << "\t" << lf_n.at(group) << "\t" << m << "\t" << std::sqrt(std::max(v, 0.0));
        }
        for (auto& b : burden) out << "\t" << median(b);
        out << "\n";
    }
    return 0;
}
