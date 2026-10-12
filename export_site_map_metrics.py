"""Export district map metrics using the repository's electoral engines."""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

# Keep normal IDE/command-line runs from updating tracked repository bytecode.
sys.dont_write_bytecode = True

from baseline_engines import dhondt_apportion, get_national_party_caps
from custom_methods import CUSTOM_METHODS_REGISTRY, allocate_two_speed_pool_method
from data_parser import parse_stacked_country_file


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "references" / "mapa-teste-metricas-schema-example.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "mapa-teste-metricas-real.json"
MODELS = ("current", "proposal")
METRICS = ("wasted_votes_pct", "represented_parties_count")
REGION_IDS = (
    "aveiro", "beja", "braga", "braganca", "castelo-branco", "coimbra",
    "evora", "faro", "guarda", "leiria", "lisboa", "portalegre", "porto",
    "santarem", "setubal", "viana-do-castelo", "vila-real", "viseu",
    "acores", "madeira",
)

# Recognize the same structural columns/summary rows as data_parser.py.
SEAT_HEADERS = {
    "mandatos", "mandates", "seats", "mandatos_totais", "mandate", "sitze",
    "zuteilung", "anzahl_mandate", "mandat", "seat", "sitze_total",
}
TOTAL_HEADERS = {
    "totais", "total", "total_votes", "totais_votos", "sum", "stimmen_total",
    "votos_totais",
}
OVERRIDE_ROWS = {
    "total seats", "total_seats", "gesamttotal", "totais mandatos",
    "totais_mandatos", "total mandates", "total_mandates", "mandatos totais",
    "mandatos_totais", "national_mandates", "national_party_caps", "override_mandates",
}
SUMMARY_ROWS = {"total votes", "totais_votos", "totais votos", "sum votes", "gesamttotal_votos"}


def region_id(name: str) -> str:
    """Normalize geography only; party/coalition names always remain untouched."""
    plain = "".join(
        c for c in unicodedata.normalize("NFKD", name.casefold())
        if not unicodedata.combining(c)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return {
        "regiao-autonoma-dos-acores": "acores",
        "regiao-autonoma-da-madeira": "madeira",
    }.get(slug, slug)


def discover_source() -> Path:
    source = ROOT / "data_Portugal.csv"
    if not source.is_file():
        raise FileNotFoundError(
            f"Expected data_Portugal.csv in the main repository folder: {ROOT}. "
            "Move the active Portugal dataset there before running the exporter."
        )
    return source


def load_regions(schema_path: Path) -> dict[str, Any]:
    with schema_path.open(encoding="utf-8-sig") as stream:
        reference = json.load(stream)
    if not isinstance(reference, dict) or not isinstance(reference.get("regions"), dict):
        raise ValueError("The schema reference must contain a regions object.")
    regions = reference["regions"]
    if set(regions) != set(REGION_IDS):
        raise ValueError("The schema reference must contain exactly the 20 expected map region ids.")
    for key, info in regions.items():
        if not isinstance(info, dict) or any(
            not isinstance(info.get(field), str) or not info[field].strip()
            for field in ("name", "geography_code")
        ):
            raise ValueError(f"Schema region {key!r} requires a name and geography_code.")
        if region_id(info["name"]) != key:
            raise ValueError(f"Schema region id {key!r} does not match its name.")
    return regions


def validate_source_rows(source_path: Path) -> dict[str, dict[str, Any]]:
    """Reject data the permissive existing parser could silently coerce or omit."""
    inventory: dict[str, dict[str, Any]] = {}
    year = None
    header = None
    seat_idx = None
    total_idx = None
    party_indices: list[int] = []

    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        for line_number, row in enumerate(csv.reader(stream, strict=True), 1):
            row = [cell.strip() for cell in row]
            if not row or not any(row):
                continue
            context = f"{source_path.name}, line {line_number}"
            if re.fullmatch(r"\d{4}", row[0]):
                if any(row[1:]):
                    raise ValueError(f"{context}: unexpected data on the election year row.")
                year = row[0]
                if year in inventory:
                    raise ValueError(f"{context}: duplicate election year {year}.")
                inventory[year] = {"districts": set(), "parties": [], "override": False}
                header = None
                continue
            if year is None:
                raise ValueError(f"{context}: expected an election year before data.")
            if header is None:
                header = row
                normalized = [re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_") for h in header]
                seats = [i for i, h in enumerate(normalized) if h in SEAT_HEADERS]
                totals = [i for i, h in enumerate(normalized) if h in TOTAL_HEADERS]
                if len(seats) != 1 or seats[0] == 0 or len(totals) != 1 or 0 in totals:
                    raise ValueError(f"{context}: expected one seats column and one valid-vote totals column.")
                seat_idx = seats[0]
                total_idx = totals[0] if totals else None
                party_indices = [i for i in range(1, len(header)) if i not in (seat_idx, total_idx)]
                parties = [header[i] for i in party_indices]
                if not header[0] or not parties or any(not p for p in parties) or len(set(header)) != len(header):
                    raise ValueError(f"{context}: empty or duplicate column/party names.")
                inventory[year]["parties"] = parties
                continue
            if len(row) != len(header) or not row[0]:
                raise ValueError(f"{context}: expected {len(header)} columns and a district/summary name.")
            special = row[0].lower() in OVERRIDE_ROWS | SUMMARY_ROWS
            for index in range(1, len(header)):
                if special and index in (seat_idx, total_idx) and not row[index]:
                    continue
                number = row[index].replace(" ", "").replace("\xa0", "")
                if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", number):
                    raise ValueError(
                        f"{context}, {year}/{row[0]}/{header[index]}: "
                        f"expected a non-negative integer, got {row[index]!r}."
                    )
            if row[0].lower() in OVERRIDE_ROWS:
                if inventory[year]["override"]:
                    raise ValueError(f"{context}: duplicate national mandate override.")
                inventory[year]["override"] = True
            elif row[0].lower() not in SUMMARY_ROWS:
                if row[0] in inventory[year]["districts"]:
                    raise ValueError(f"{context}: duplicate district {row[0]!r} in {year}.")
                inventory[year]["districts"].add(row[0])

    if not inventory:
        raise ValueError("No election years found in the Portugal source.")
    for year, info in inventory.items():
        if not info["parties"] or not info["districts"]:
            raise ValueError(f"{year}: missing election header or district rows.")
    return inventory


def load_elections(source_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    inventory = validate_source_rows(source_path)
    elections = parse_stacked_country_file(str(source_path))
    if set(elections) != set(inventory):
        raise ValueError("The parser did not include every source election year.")
    mappings = {}
    for year, data in elections.items():
        votes = data["votes"]
        caps = data["district_caps"]
        parties = data["parties_list"]
        if (
            set(votes) != inventory[year]["districts"] or set(caps) != set(votes)
            or set(data["total_votes_cast"]) != set(votes)
            or parties != inventory[year]["parties"]
            or (data["national_mandates"] is not None) != inventory[year]["override"]
        ):
            raise ValueError(f"{year}: the parser omitted or changed source rows/columns.")
        mapping = {}
        for district, party_votes in votes.items():
            if set(party_votes) != set(parties) or any(type(v) is not int or v < 0 for v in party_votes.values()):
                raise ValueError(f"{year}/{district}: invalid or missing party vote counts.")
            listed_votes = sum(party_votes.values())
            valid_votes = data["total_votes_cast"][district]
            if listed_votes <= 0 or type(caps[district]) is not int or caps[district] <= 0:
                raise ValueError(f"{year}/{district}: valid votes and district seats must be positive.")
            if valid_votes < listed_votes:
                raise ValueError(
                    f"{year}/{district}: Totais is smaller than the listed party vote sum "
                    f"(Totais={valid_votes}, listed={listed_votes})."
                )
            key = region_id(district)
            if key in REGION_IDS:
                if key in mapping:
                    raise ValueError(f"{year}: multiple districts map to region {key!r}.")
                mapping[key] = district
            else:
                raise ValueError(
                    f"{year}: unrecognized constituency {district!r}; calculations accept only "
                    "the 18 mainland districts, Açores and Madeira."
                )
        if set(mapping) != set(REGION_IDS):
            raise ValueError(f"{year}: missing map constituencies {sorted(set(REGION_IDS) - set(mapping))}.")
        mappings[year] = mapping
    return elections, mappings


def proposal_config() -> dict[str, Any]:
    matches = [m for m in CUSTOM_METHODS_REGISTRY if m["func"] is allocate_two_speed_pool_method]
    if len(matches) != 1:
        raise ValueError("Expected exactly one 2-Speed Danish Pool entry in CUSTOM_METHODS_REGISTRY.")
    return matches[0]


def validate_allocation(
    year: str, model: str, allocation: dict[str, dict[str, int]],
    data: dict[str, Any], targets: dict[str, int] | None = None,
) -> dict[str, int]:
    parties = data["parties_list"]
    if set(allocation) != set(data["votes"]):
        raise ValueError(f"{year}/{model}: incomplete allocation districts.")
    totals = {p: 0 for p in parties}
    for district, seats in allocation.items():
        if set(seats) != set(parties) or any(type(v) is not int or v < 0 for v in seats.values()):
            raise ValueError(f"{year}/{model}/{district}: invalid or incomplete seat allocation.")
        if sum(seats.values()) != data["district_caps"][district]:
            raise ValueError(f"{year}/{model}/{district}: allocated seats do not match district capacity.")
        for party in parties:
            totals[party] += seats[party]
    if targets is not None and totals != targets:
        raise ValueError(f"{year}/{model}: allocated national seats do not match party targets.")
    return totals


def district_metrics(
    votes: dict[str, int], seats: dict[str, int], represented: set[str],
    valid_votes: int,
) -> dict[str, float | int]:
    omitted_votes = valid_votes - sum(votes.values())
    if valid_votes <= 0 or omitted_votes < 0:
        raise ValueError("Valid-vote total must be positive and at least the listed vote sum.")
    # The agreed input format lists all relevant parties. Remaining valid votes
    # belong to omitted lists assumed to win no seats in either model.
    wasted = omitted_votes + sum(count for party, count in votes.items() if party not in represented)
    return {
        "wasted_votes_pct": round(100.0 * wasted / valid_votes, 6),
        "represented_parties_count": sum(count > 0 for count in seats.values()),
    }


def build_export(source_path: Path, schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    regions = load_regions(schema_path)
    elections, mappings = load_elections(source_path)
    method = proposal_config()
    kwargs = dict(method.get("kwargs", {}))
    values: dict[str, Any] = {model: {} for model in MODELS}
    totals_gaps = {}
    for year in sorted(elections):
        data = elections[year]
        votes = data["votes"]
        caps = data["district_caps"]
        national_votes = {p: sum(v[p] for v in votes.values()) for p in data["parties_list"]}
        targets = get_national_party_caps("portugal", national_votes, sum(caps.values()), data["national_mandates"])
        if (
            set(targets) != set(national_votes)
            or any(type(v) is not int or v < 0 for v in targets.values())
            or sum(targets.values()) != sum(caps.values())
            or any(targets[p] > 0 and national_votes[p] == 0 for p in targets)
        ):
            raise ValueError(f"{year}: national party targets are inconsistent with the source.")
        current = {district: dhondt_apportion(v, caps[district]) for district, v in votes.items()}
        validate_allocation(year, "current", current, data)
        proposal, reported_totals, _ = method["func"](votes, targets, caps, **kwargs)
        proposal_totals = validate_allocation(year, "proposal", proposal, data, targets)
        if reported_totals != proposal_totals:
            raise ValueError(f"{year}/proposal: reported party totals do not match allocated seats.")
        national_winners = {party for party, seats in proposal_totals.items() if seats > 0}
        for model, allocation in (("current", current), ("proposal", proposal)):
            values[model][year] = {}
            for key in regions:
                district = mappings[year][key]
                local_winners = {p for p, s in allocation[district].items() if s > 0}
                represented = local_winners if model == "current" else national_winners
                values[model][year][key] = district_metrics(
                    votes[district], allocation[district], represented,
                    data["total_votes_cast"][district],
                )
        totals_gaps[year] = sum(data["total_votes_cast"].values()) - sum(national_votes.values())

    payload = {
        "schema_version": 2,
        "demo": False,
        "description": "Métricas calculadas a partir do CSV de origem, com Totais como votos válidos "
        "e as hipóteses de cobertura identificadas nos metadados.",
        "models": {
            "current": {"label": "Sistema atual", "method": "Current District D'Hondt"},
            "proposal": {
                "label": "A nossa proposta", "method": "2-Speed Danish Pool",
                "registry_name": method["name"],
                "parameters": {k: v for k, v in kwargs.items() if not callable(v)},
            },
        },
        "metrics": {
            "wasted_votes_pct": {
                "label": "Votos desperdiçados (%)", "unit": "percent", "palette": "red",
                "definition": "Percentagem dos votos válidos sem representação: "
                "no círculo no sistema atual; a nível nacional na proposta.",
            },
            "represented_parties_count": {
                "label": "Partidos representados", "unit": "count", "palette": "teal",
                "definition": "Número de listas eleitorais com pelo menos um deputado no círculo; "
                "cada coligação conta como uma única entidade.",
            },
        },
        "years": sorted(elections),
        "regions": regions,
        "source": {
            "file": source_path.name,
            "valid_votes_basis": "Totais",
            "national_scope": "18_mainland_districts_plus_acores_and_madeira",
            "omitted_valid_votes_by_year": totals_gaps,
            "omitted_lists_assumed_unrepresented": any(totals_gaps.values()),
            "assumptions": ([
                "Omitted electoral lists win no seats in either model. Their valid votes "
                "(Totais minus listed votes) count as wasted. Seat allocation uses the listed "
                "votes only; results depend on this assumption."
            ] if any(totals_gaps.values()) else []),
            "note": "Totais contains all valid votes, including omitted electoral lists. "
            "All calculations use only the 18 mainland districts, Açores and Madeira. "
            "Other constituencies are rejected before seat allocation.",
        },
        "values": values,
    }
    validate_export(payload, elections, mappings, regions)
    return payload


def validate_export(
    payload: dict[str, Any], elections: dict[str, Any],
    mappings: dict[str, dict[str, str]], regions: dict[str, Any],
) -> None:
    if payload["years"] != sorted(elections) or set(payload["regions"]) != set(regions):
        raise ValueError("Export years or region ids do not match the source/schema.")
    if set(payload["values"]) != set(MODELS) or set(payload["models"]) != set(MODELS):
        raise ValueError("Export must contain exactly current and proposal models.")
    if set(payload["metrics"]) != set(METRICS):
        raise ValueError("Export must contain exactly the two supported metrics.")
    for model, years in payload["values"].items():
        if set(years) != set(elections):
            raise ValueError(f"{model}: incomplete election years.")
        for year, districts in years.items():
            if set(districts) != set(regions):
                raise ValueError(f"{model}/{year}: incomplete map regions.")
            for key, metrics in districts.items():
                context = f"{model}/{year}/{key}"
                if set(metrics) != set(METRICS):
                    raise ValueError(f"{context}: missing or unexpected metrics.")
                pct = metrics["wasted_votes_pct"]
                count = metrics["represented_parties_count"]
                if type(pct) not in (int, float) or not math.isfinite(pct) or not 0 <= pct <= 100:
                    raise ValueError(f"{context}: wasted_votes_pct must be a finite number in [0, 100].")
                max_count = min(len(elections[year]["parties_list"]), elections[year]["district_caps"][mappings[year][key]])
                if type(count) is not int or not 1 <= count <= max_count:
                    raise ValueError(f"{context}: represented_parties_count must be a valid integer.")


def write_export(payload: dict[str, Any], output_path: Path) -> None:
    """Replace the output only after validation and complete serialization."""
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output_path.parent,
            prefix=output_path.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    try:
        source = discover_source().resolve()
        schema = DEFAULT_SCHEMA.resolve()
        output = DEFAULT_OUTPUT.resolve()
        if output in (source, schema) or output.suffix.lower() != ".json":
            raise ValueError("Output must be a .json file distinct from the source and schema reference.")
        payload = build_export(source, schema)
        write_export(payload, output)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Source: {source}")
    print(f"Years: {', '.join(payload['years'])}")
    print(f"Proposal: {payload['models']['proposal']['method']} {payload['models']['proposal']['parameters']}")
    gaps = payload["source"]["omitted_valid_votes_by_year"]
    if any(gaps.values()):
        print("Assumption: omitted lists win no seats in either model; their votes count as wasted. "
              "Percentages use Totais (all valid votes). This assumption is recorded in the JSON.")
    combinations = len(MODELS) * len(payload["years"]) * len(payload["regions"]) * len(METRICS)
    print(f"Validation passed: {len(payload['years'])} years, {len(MODELS)} models, "
          f"{len(payload['regions'])} constituencies, {combinations} metric values. Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
