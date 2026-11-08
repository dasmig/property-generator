// Benchmarks for property-generator; see bench.hpp for the options.

#include "../dasmig/propertygen.hpp"
#include "bench.hpp"

int main(int argc, char** argv)
{
    dasmig::bench::runner run{"property-generator", argc, argv};

    run.load("load", [&] {
        dasmig::pty gen;
        return gen.load(run.tier());
    });

    dasmig::pty gen;
    if (!gen.load(run.tier())) return run.missing_tier();

    run.calls("get_property", [&](std::uint64_t seed) { return gen.get_property({}, seed); });
    run.calls("get_property to_json", [&](std::uint64_t seed) {
        return gen.get_property({}, seed).to_json();
    });

    dasmig::property_request with_income;
    with_income.country = "DE";
    with_income.household_income = dasmig::core::money::from_major(48000, "EUR", 2);
    run.calls("get_property with an income", [&](std::uint64_t seed) { return gen.get_property(with_income, seed); });

    run.batches("get_property_batch", [&](std::size_t count, std::size_t threads, std::uint64_t seed) {
        return gen.get_property_batch({}, {.count = count, .threads = threads}, seed);
    });

    return run.finish();
}
