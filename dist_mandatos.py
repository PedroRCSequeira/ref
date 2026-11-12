"""Compare district mandate distributions and their domestic party totals.

Run: python dist_mandatos.py
Optional: python dist_mandatos.py path/to/data_Portugal.csv --output report.csv

All totals exclude the four overseas seats. District weights are Inscritos or
Eleitores. Party seats always use district d'Hondt on the supplied party votes.
All source years must pass the shared mandate check before analysis starts.
"""

import argparse
import csv
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True

from auxiliary.district_validation import DEFAULT_SOURCE, TOTAL_MANDATES, load_validated_elections
from export_site_map_metrics import load_elections


DEFAULT_OUTPUT = Path(__file__).resolve().with_name("dist_mandatos_excel.csv")
SCENARIOS = ("Guaranteed 1", "Guaranteed 2", "Sainte-Lague", "Equalized 11/12")
NOTES = (
    "All results exclude the four overseas mandates; votes and party labels come from the supplied CSV.",
    "Guaranteed 1/2: assign that many seats to every district, then distribute the remaining seats by d'Hondt starting at divisor 1.",
    "Sainte-Lague uses electorate divisors 1, 3, 5, ...; party allocation within every district always uses d'Hondt.",
    "Equalized 11/12: SIX largest electorates receive 12 seats; the other 14 receive 11 (226 total). Four receiving 12 would total 224.",
    "Current party totals are recomputed by district d'Hondt using the stored Mandatos, rather than national d'Hondt.",
    "Only supplied party vote columns can receive seats; omitted lists cannot be reconstructed from Totais.",
    "Exact quotient ties favor the smaller electorate/vote count, then alphabetical name if those counts also tie.",
    "Removal order runs from 225 down to 180; Change is the district's cumulative loss relative to 226 seats.",
    "Lost a party? names a party that goes from 1 seat to 0 in that district at that step; '-' means none.",
)
CSV_FIELDS = (
    "Year", "Analysis", "Scenario", "Total_mandates", "District", "Party",
    "Registered_voters", "Current_mandates", "New_mandates", "Change", "Step", "Lost_party", "Notes",
)


def allocate_seats(weights, total=TOTAL_MANDATES, *, guaranteed=0, divisor_step=1):
    """Return final seats and the sequence of discretionary seat recipients.

    Guaranteed seats are added to a fresh allocation of the remaining seats.
    Step 1 gives d'Hondt; step 2 gives standard Sainte-Lague.
    """
    if total < 0 or guaranteed < 0 or divisor_step not in (1, 2):
        raise ValueError("Invalid allocation parameters.")
    remaining = total - guaranteed * len(weights)
    if remaining < 0 or any(type(w) is not int or w < 0 for w in weights.values()):
        raise ValueError("Invalid weights or too many guaranteed mandates.")
    active = sorted(name for name, weight in weights.items() if weight > 0)
    if remaining and not active:
        raise ValueError("Cannot allocate mandates without positive weights.")
    discretionary = dict.fromkeys(sorted(weights), 0)
    order = []
    for _ in range(remaining):
        winner = max(active, key=lambda name: (
            Fraction(weights[name], divisor_step * discretionary[name] + 1), -weights[name]
        ))
        discretionary[winner] += 1
        order.append(winner)
    return {name: count + guaranteed for name, count in discretionary.items()}, order


def equalized_seats(voters):
    """11 each plus one for the six largest electorates, retaining 226 seats."""
    if len(voters) != 20:
        raise ValueError("The equalized scenario requires 20 domestic constituencies.")
    largest = set(sorted(voters, key=lambda name: (-voters[name], name))[:6])
    return {name: 11 + (name in largest) for name in voters}


def party_totals(votes, district_seats, parties):
    totals = dict.fromkeys(parties, 0)
    for district, seats in district_seats.items():
        allocation, _ = allocate_seats(votes[district], seats)
        for party, count in allocation.items():
            totals[party] += count
    return totals


def build_analysis(source):
    voter_elections = load_validated_elections(source)
    elections, _ = load_elections(source)
    if set(elections) != set(voter_elections):
        raise ValueError("Voter and party data do not contain the same election years.")
    results = {}
    for year in sorted(elections):
        election = elections[year]
        voters = voter_elections[year]["voters"]
        current = voter_elections[year]["mandates"]
        if current != election["district_caps"]:
            raise ValueError(f"{year}: voter and party data disagree about district mandates.")
        _, order = allocate_seats(voters)
        scenarios = {
            SCENARIOS[0]: allocate_seats(voters, guaranteed=1)[0],
            SCENARIOS[1]: allocate_seats(voters, guaranteed=2)[0],
            SCENARIOS[2]: allocate_seats(voters, divisor_step=2)[0],
            SCENARIOS[3]: equalized_seats(voters),
        }
        # Highest-averages allocations are nested: remove the last awarded seat
        # to get the allocation for one fewer mandate, including the same ties.
        reduced = current.copy()
        removals = []
        for total in range(TOTAL_MANDATES - 1, 179, -1):
            district = order[total]
            before, _ = allocate_seats(election["votes"][district], reduced[district])
            reduced[district] -= 1
            after, _ = allocate_seats(election["votes"][district], reduced[district])
            lost_party = next(
                (party for party, seats in before.items() if seats == 1 and after[party] == 0),
                "-",
            )
            removals.append({
                "district": district, "total": total, "new": reduced[district],
                "change": reduced[district] - current[district],
                "lost_party": lost_party,
            })
        allocations = {"Current": current, **scenarios}
        parties = {
            name: party_totals(election["votes"], caps, election["parties_list"])
            for name, caps in allocations.items()
        }
        for name, caps in allocations.items():
            if sum(caps.values()) != TOTAL_MANDATES or sum(parties[name].values()) != TOTAL_MANDATES:
                raise ValueError(f"{year}/{name}: mandates do not sum to {TOTAL_MANDATES}.")
        results[year] = {
            "voters": voters, "current": current, "scenarios": scenarios,
            "removals": removals, "parties": parties,
        }
    return results


def print_table(headers, rows):
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    for row in [headers, *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


def print_report(results):
    print("DISTRICT MANDATE ANALYSIS")
    for note in NOTES:
        print(f"- {note}")
    for year, data in results.items():
        print(f"\n{year}\n")
        print("District allocations: each scenario shows mandates (change from current)")
        rows = []
        for district in data["current"]:
            current = data["current"][district]
            row = [district, str(current)]
            for caps in data["scenarios"].values():
                row.append(f"{caps[district]} ({caps[district] - current:+d})")
            rows.append(row)
        print_table(["District", "Current", *SCENARIOS], rows)
        print("\nOrdered losses as total mandates decrease (cumulative change):")
        print_table(
            ["District", "Change", "Total mandates", "Lost a party?"],
            [[loss["district"], f"{loss['change']:+d}", loss["total"], loss["lost_party"]]
             for loss in data["removals"]],
        )
        print("\nParty totals: each scenario shows mandates (change from current)")
        rows = []
        current = data["parties"]["Current"]
        for party in sorted(current, key=lambda p: (-current[p], p)):
            row = [party, str(current[party])]
            for scenario in SCENARIOS:
                count = data["parties"][scenario][party]
                row.append(f"{count} ({count - current[party]:+d})")
            rows.append(row)
        rows.append(["TOTAL", "226", *["226 (0)"] * len(SCENARIOS)])
        print_table(["Party", "Current", *SCENARIOS], rows)


def report_rows(results):
    for note in NOTES:
        yield {"Analysis": "Notes", "Notes": note}
    for year, data in results.items():
        for scenario, caps in data["scenarios"].items():
            for district in data["current"]:
                current = data["current"][district]
                yield {
                    "Year": year, "Analysis": "District allocation", "Scenario": scenario,
                    "Total_mandates": TOTAL_MANDATES, "District": district,
                    "Registered_voters": data["voters"][district], "Current_mandates": current,
                    "New_mandates": caps[district], "Change": caps[district] - current,
                }
        for step, loss in enumerate(data["removals"], 1):
            district = loss["district"]
            yield {
                "Year": year, "Analysis": "Removal order", "Scenario": "d'Hondt",
                "Total_mandates": loss["total"], "District": district,
                "Registered_voters": data["voters"][district],
                "Current_mandates": data["current"][district], "New_mandates": loss["new"],
                "Change": loss["change"], "Step": step, "Lost_party": loss["lost_party"],
            }
        current = data["parties"]["Current"]
        for scenario in SCENARIOS:
            for party in sorted(current, key=lambda p: (-current[p], p)):
                count = data["parties"][scenario][party]
                yield {
                    "Year": year, "Analysis": "Party totals", "Scenario": scenario,
                    "Total_mandates": TOTAL_MANDATES, "Party": party,
                    "Current_mandates": current[party], "New_mandates": count,
                    "Change": count - current[party],
                }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        if args.source.resolve() == args.output.resolve():
            raise ValueError("The report path must differ from the source CSV.")
        results = build_analysis(args.source)
        # UTF-8 BOM lets Excel recognize Portuguese accents.
        with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(report_rows(results))
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1
    print(f"Mandate validation passed for all {len(results)} election years.\n")
    print_report(results)
    print(f"\nCSV report saved to: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
