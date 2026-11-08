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

    run.batches("get_property_batch", [&](std::size_t count, std::size_t threads, std::uint64_t seed) {
        return gen.get_property_batch({}, {.count = count, .threads = threads}, seed);
    });

    return run.finish();
}
