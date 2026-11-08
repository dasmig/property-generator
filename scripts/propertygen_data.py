"""Shared helpers for property-generator's data build (stdlib only)."""
import csv
import json
import math
from pathlib import Path

csv.field_size_limit(10**8)

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "scripts" / "curated"
RAW = ROOT / "raw_data"
RESOURCES = ROOT / "resources"
SIBLINGS = ROOT.parent
TIERS = ("lite", "full")

TYPES = ("detached", "semi_detached", "flat_small", "flat_large", "informal", "other")
TENURES = ("owner_outright", "owner_mortgage", "tenant_market", "tenant_reduced")
AREAS = ("city", "town", "rural")
HOUSEHOLD_TYPES = ("one_person", "couple", "nuclear", "single_parent", "with_parents", "multi_generation", "other")
EVIDENCE_ORDER = ("measured", "census", "compendium", "filled", "modelled")
# Eurostat's geo codes that are not ISO alpha-2.
EUROSTAT_GEO = {"EL": "GR", "UK": "GB"}


def read_tsv(path):
    """Rows of a TSV as dicts; `#` lines are comments, short rows are padded."""
    with open(path, encoding="utf-8", newline="") as f:
        lines = [line for line in f.read().split("\n") if line and not line.startswith("#")]
    header = lines[0].rstrip("\r").split("\t")
    rows = []
    for line in lines[1:]:
        cells = line.rstrip("\r").split("\t")
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def fmt(x, digits=4):
    """A share or ratio as short text: no trailing zeros, no exponent."""
    if x is None or x == "":
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, int):
        return str(x)
    text = f"{x:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def write_table(tier, name, comment, columns, rows, digits=4):
    """Write resources/<tier>/<name> with the source in its first line."""
    path = RESOURCES / tier / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {comment}\n")
        f.write("\t".join(columns) + "\n")
        for row in rows:
            cells = [fmt(row.get(c, ""), digits) for c in columns]
            for cell in cells:
                if "\t" in cell or "\n" in cell:
                    raise ValueError(f"{name}: a control character in {cell!r}")
            f.write("\t".join(cells) + "\n")
    return path


def write_all_tiers(name, comment, columns, rows, digits=None):
    """full keeps every column; lite, which is compiled in, leaves out the source texts (the
    evidence stays, the result reports it) and keeps three decimals, to stay under 0.2 MB. Readers
    normalise every row, so rounding does not bias a draw. `digits` sets both tiers, for the small
    tables whose tiny values a strong tilt magnifies (rooms.tsv)."""
    write_table("full", name, comment, columns, rows, digits or 4)
    lite = [c for c in columns if c != "source" and not c.endswith("_source")]
    write_table("lite", name, comment + ("; sources in the full tier" if lite != columns else ""), lite, rows, digits or 3)


def eurostat(name):
    """A saved Eurostat JSON-stat file as {(dim values...): value} plus the dimension order.

    Geo codes are turned into ISO alpha-2 and aggregates (EU27_2020, EA20, ...) dropped."""
    d = json.loads((RAW / "eurostat" / f"{name}.json").read_text(encoding="utf-8"))
    ids, size = d["id"], d["size"]
    index = [{v: k for k, v in d["dimension"][dim]["category"]["index"].items()} for dim in ids]
    stride = [1] * len(size)
    for i in range(len(size) - 2, -1, -1):
        stride[i] = stride[i + 1] * size[i + 1]
    out = {}
    gi = ids.index("geo")
    for k, v in d["value"].items():
        k = int(k)
        key = [index[i][(k // stride[i]) % size[i]] for i in range(len(size))]
        geo = EUROSTAT_GEO.get(key[gi], key[gi])
        if len(geo) != 2:
            continue
        key[gi] = geo
        out[tuple(key)] = v
    return ids, out


def latest(ids, values, fixed, years=None):
    """{geo: (year, value)} for the latest year where `fixed` (dim -> code) matches."""
    gi, ti = ids.index("geo"), ids.index("time")
    pos = {ids.index(k): v for k, v in fixed.items()}
    best = {}
    for key, v in values.items():
        if any(key[i] != want for i, want in pos.items()):
            continue
        if years and key[ti] not in years:
            continue
        g, t = key[gi], key[ti]
        if g not in best or t > best[g][0]:
            best[g] = (t, v)
    return best


def normalise(shares):
    total = sum(shares)
    if total <= 0:
        raise ValueError(f"shares sum to {total}")
    return [s / total for s in shares]


def weighted_mean(pairs):
    """Mean of (weight, value) pairs; None when there is no weight."""
    w = sum(p for p, _ in pairs)
    return sum(p * v for p, v in pairs) / w if w > 0 else None


def lognormal_from_mean_sd(mean, sd):
    sigma2 = math.log(1 + (sd / mean) ** 2)
    return math.log(mean) - sigma2 / 2, math.sqrt(sigma2)
