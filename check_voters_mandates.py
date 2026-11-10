"""Check each election's district Mandatos against 226-seat voter-based d'Hondt.

Run: python check_voters_mandates.py [path/to/data_Portugal.csv]
Accepts Inscritos or Eleitores; never writes to the source or generated reports.
Rule: https://www.tribunalconstitucional.pt/tc/legislacao030102.html
"""

import argparse
import csv
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True

from data_parser import REGISTERED_VOTER_HEADERS


TOTAL_MANDATES = 226  # 230 minus the four seats for overseas constituencies.
DEFAULT_SOURCE = Path(__file__).resolve().with_name("data_Portugal.csv")


def read_elections(source: Path) -> dict:
    """Read the stacked CSV strictly so invalid counts cannot become zero."""
    elections = {}
    year = None
    header = None
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for line_number, row in enumerate(csv.reader(stream, strict=True), 1):
            row = [cell.strip() for cell in row]
            if not row or not any(row):
                continue
            context = f"{source.name}, line {line_number}"
            if re.fullmatch(r"\d{4}", row[0]):
                if any(row[1:]) or row[0] in elections:
                    raise ValueError(f"{context}: invalid or duplicate election year.")
                year = row[0]
                elections[year] = {"voters": {}, "mandates": {}}
                header = None
                continue
            if year is None:
                raise ValueError(f"{context}: expected an election year.")
            if header is None:
                header = [cell.lower() for cell in row]
                voters = [i for i, name in enumerate(header) if name in REGISTERED_VOTER_HEADERS]
                if header[0] != "circulo" or header.count("mandatos") != 1 or len(voters) != 1:
                    raise ValueError(
                        f"{context}: expected Circulo, Mandatos, and exactly one Inscritos/Eleitores column."
                    )
                voter_idx = voters[0]
                mandate_idx = header.index("mandatos")
                continue
            if len(row) != len(header) or not row[0]:
                raise ValueError(f"{context}: expected {len(header)} columns and a district name.")
            district = row[0]
            if district.lower() in {"europa", "fora da europa"}:
                raise ValueError(f"{context}: overseas constituencies must be excluded from the 226 seats.")
            if district in elections[year]["voters"]:
                raise ValueError(f"{context}: duplicate district {district!r} in {year}.")
            for field, index in (("voters", voter_idx), ("mandates", mandate_idx)):
                number = row[index].replace(" ", "").replace("\xa0", "")
                if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", number):
                    raise ValueError(f"{context}: {row[index]!r} must be a positive integer ({header[index]}).")
                value = int(number.replace(",", ""))
                if value <= 0:
                    raise ValueError(f"{context}: {header[index]} must be a positive integer.")
                elections[year][field][district] = value
    if not elections:
        raise ValueError("No election years found.")
    for year, data in elections.items():
        if len(data["voters"]) != 20:
            raise ValueError(f"{year}: expected 20 domestic constituencies, found {len(data['voters'])}.")
    return elections


def apportion_mandates(voters: dict[str, int]) -> dict[str, int]:
    """Use exact quotients; tied quotients favor the smaller electorate.

    If electorates also tie, district name provides a stable ordering.
    """
    mandates = {district: 0 for district in sorted(voters)}
    for _ in range(TOTAL_MANDATES):
        winner = max(
            mandates,
            key=lambda district: (
                Fraction(voters[district], mandates[district] + 1), -voters[district]
            ),
        )
        mandates[winner] += 1
    return mandates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    try:
        elections = read_elections(args.source)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Check failed: {exc}", file=sys.stderr)
        return 2

    all_match = True
    for year, data in elections.items():
        calculated = apportion_mandates(data["voters"])
        stored = data["mandates"]
        differences = [district for district in stored if stored[district] != calculated[district]]
        if not differences:
            print(f"{year}: matches (all 20 districts; {TOTAL_MANDATES} mandates).")
            continue
        all_match = False
        print(f"{year}: MISMATCH (stored total: {sum(stored.values())}; calculated: {TOTAL_MANDATES}).")
        for district in differences:
            print(
                f"  {district}: stored={stored[district]}, calculated={calculated[district]}, "
                f"voters={data['voters'][district]}"
            )
    if all_match:
        print("matches")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
