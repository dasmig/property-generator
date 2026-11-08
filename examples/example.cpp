#include "../dasmig/propertygen.hpp"
#include <cstdint>
#include <iostream>

int main()
{
    // The singleton loads the lite tier (compiled in, or from resources/).
    auto& gen = dasmig::pty::instance();
    if (!gen.has_data())
    {
        std::cerr << "Could not load the property data.\n";
        return 1;
    }
    std::cout << "Homes in " << gen.countries().size() << " countries.\n\n";

    std::cout << "Anywhere, by population:\n";
    for (int i = 0; i < 5; ++i) std::cout << "  " << gen.get_property(dasmig::property_request{}) << '\n';

    // A household from relationship-generator, a place from city-generator and an
    // income from occupation-generator: the home is drawn to fit them.
    dasmig::property_request family;
    family.country = "BR";
    family.place_population = 1'200'000; // a city
    family.household_type = "nuclear";
    family.household_size = 4;
    family.children = 2;
    family.anchor_age = 38;
    family.household_income = dasmig::core::money::from_major(96'000, "BRL", 2);
    std::cout << "\nA family of four in a Brazilian city, earning 96,000 BRL a year:\n";
    for (int i = 0; i < 3; ++i) std::cout << "  " << gen.get_property(family) << '\n';

    std::cout << "\nSeed 42, twice:\n";
    const auto a = gen.get_property(dasmig::property_request{}, std::uint64_t{42});
    const auto b = gen.get_property(dasmig::property_request{}, std::uint64_t{42});
    std::cout << "  " << a.to_json() << '\n' << "  " << b.to_json() << '\n';

    std::cout << "\nWhat Japan's figures rest on: " << gen.evidence("JP").to_string() << '\n';
    return 0;
}
