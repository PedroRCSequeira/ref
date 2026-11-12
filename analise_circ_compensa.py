"""Find the smallest compensatory circle matching national d'Hondt (226 seats).

Run: python analise_circ_compensa.py
Optional: python analise_circ_compensa.py source.csv --csv report.csv --graph trend.png

Use excess-based jumps, redistributing the remaining district mandates by
registered electorate. The circle fills each party's shortfall to its fixed
226-seat national target. The four overseas mandates are never included.
"""

import argparse
import csv
import os
import sys
import textwrap
from itertools import zip_longest
from pathlib import Path

sys.dont_write_bytecode = True

from auxiliary.district_validation import DEFAULT_SOURCE, TOTAL_MANDATES, load_validated_elections
from dist_mandatos import allocate_seats
from export_site_map_metrics import load_elections


ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / "analise_circ_compensa.csv"
DEFAULT_GRAPH = ROOT / "TREND_Compensatory_Circle_Size.png"
RED_BACKGROUND = "\033[41;97m"
YELLOW_BACKGROUND = "\033[43;30m"
RESET_COLOR = "\033[0m"
NOTES = (
    "226 domestic mandates only; the four overseas mandates are excluded.",
    "National targets: d'Hondt on the sum of the supplied domestic party votes; coalition names remain unchanged.",
    "Remaining district mandates: d'Hondt on Inscritos/Eleitores; party seats: d'Hondt separately in each district.",
    "Start at C=0; add the sum of positive district-party excesses to C until no party exceeds its national target.",
    "Compensatory seats equal national target minus remaining district seats, rather than a fresh allocation of C seats.",
    "Exact quotient ties favor smaller electorate/vote counts, then alphabetical name if those counts also tie.",
    "Only supplied party columns are used; votes for omitted lists cannot be reconstructed from Totais.",
    "Cells show original(change) mandates with signed changes; unchanged cells omit parentheses; final totals include the circle.",
    "District party cells: red means all local representation lost; yellow means some seats lost with representation retained.",
)


def district_allocation(votes, caps, parties):
    """Allocate party seats locally, keeping the supplied display order."""
    matrix = {}
    totals = dict.fromkeys(parties, 0)
    for district, cap in caps.items():
        seats, _ = allocate_seats(votes[district], cap)
        if sum(seats.values()) != cap:
            raise ValueError(f"{district}: party mandates do not match district capacity.")
        matrix[district] = {party: seats[party] for party in parties}
        for party in parties:
            totals[party] += seats[party]
    return matrix, totals


def positive_excess(totals, targets):
    return sum(max(totals[party] - targets[party], 0) for party in targets)


def analyse_election(votes, voters, current_caps, parties, *, total=TOTAL_MANDATES):
    """Use cumulative excess jumps and verify the cutoff at C and C-1.

    With fixed exact tie rules, d'Hondt allocations are nested as the house
    shrinks. Each additional circle seat removes one district-party seat, so
    an excess E requires at least E further removals. Jumping C += E therefore
    cannot skip a feasible circle size. This minimum is conditional on keeping
    electorate-based d'Hondt for the remaining district mandates.
    """
    if type(total) is not int or total <= 0 or sum(current_caps.values()) != total:
        raise ValueError("Original district mandates must sum to the positive seat target.")
    if not parties or len(set(parties)) != len(parties):
        raise ValueError("Expected distinct party names.")
    if set(voters) != set(current_caps) or set(votes) != set(current_caps):
        raise ValueError("Electorates, votes, and mandates must contain the same districts.")
    if any(set(district_votes) != set(parties) for district_votes in votes.values()):
        raise ValueError("Every district must have the supplied party columns.")
    baseline_caps, _ = allocate_seats(voters, total)
    if baseline_caps != current_caps:
        raise ValueError("Original mandates do not match electorate-based d'Hondt.")

    national_votes = {party: sum(row[party] for row in votes.values()) for party in parties}
    targets, _ = allocate_seats(national_votes, total)
    targets = {party: targets[party] for party in parties}
    original, original_totals = district_allocation(votes, current_caps, parties)
    size = 0
    caps, remaining, district_totals = current_caps.copy(), original, original_totals
    steps = []
    while True:
        excess = positive_excess(district_totals, targets)
        steps.append({"size": size, "excess": excess})
        if excess == 0:
            break
        size += excess
        if size > total:
            raise ValueError("Compensatory circle exceeded the fixed national seat total.")
        allocated, _ = allocate_seats(voters, total - size)
        caps = {district: allocated[district] for district in current_caps}
        remaining, district_totals = district_allocation(votes, caps, parties)

    compensatory = {party: targets[party] - district_totals[party] for party in parties}
    if any(count < 0 for count in compensatory.values()) or sum(compensatory.values()) != size:
        raise ValueError("Compensatory seats do not match the circle size.")
    if sum(caps.values()) + size != total or sum(targets.values()) != total:
        raise ValueError("District and compensatory mandates do not match the national total.")
    for district in current_caps:
        if caps[district] > current_caps[district] or any(
            remaining[district][party] > original[district][party] for party in parties
        ):
            raise ValueError("Shrinking the district house unexpectedly increased an allocation.")

    # A direct adjacent-size check certifies the claimed minimum independently
    # of how many jump iterations were needed. C=0 is already the lower bound.
    previous_excess = None
    if size:
        previous_caps, _ = allocate_seats(voters, total - size + 1)
        _, previous_totals = district_allocation(votes, previous_caps, parties)
        previous_excess = positive_excess(previous_totals, targets)
        if previous_excess == 0:
            raise ValueError("One fewer compensatory mandate already works; minimum check failed.")

    return {
        "size": size, "total": total, "parties": list(parties),
        "current_caps": current_caps.copy(), "caps": caps,
        "original": original, "remaining": remaining,
        "original_totals": original_totals, "district_totals": district_totals,
        "targets": targets, "compensatory": compensatory,
        "steps": steps, "previous_excess": previous_excess,
    }


def build_analysis(source=DEFAULT_SOURCE):
    # Validate every year before calculating any scenario or writing outputs.
    voter_elections = load_validated_elections(source)
    elections, _ = load_elections(source)
    if set(elections) != set(voter_elections):
        raise ValueError("Voter and party data do not contain the same election years.")
    results = {}
    for year in sorted(elections):
        data, electorate = elections[year], voter_elections[year]
        if data["district_caps"] != electorate["mandates"]:
            raise ValueError(f"{year}: voter and party data disagree about district mandates.")
        results[year] = analyse_election(
            data["votes"], electorate["voters"], electorate["mandates"], data["parties_list"],
        )
    return results


def seat_cell(before, after):
    change = after - before
    return f"{before}({change:+d})" if change else str(before)


def matrix_table(data):
    parties = data["parties"]
    headers = ["District", *parties, "Mandatos"]
    rows, highlighted = [], {}
    for district, before in data["original"].items():
        after = data["remaining"][district]
        row_index = len(rows)
        for column, party in enumerate(parties, 1):
            if before[party] > after[party]:
                highlighted[row_index, column] = RED_BACKGROUND if after[party] == 0 else YELLOW_BACKGROUND
        rows.append([
            district, *[seat_cell(before[p], after[p]) for p in parties],
            seat_cell(data["current_caps"][district], data["caps"][district]),
        ])
    rows.append([
        "District subtotal",
        *[seat_cell(data["original_totals"][p], data["district_totals"][p]) for p in parties],
        seat_cell(data["total"], data["total"] - data["size"]),
    ])
    rows.append([
        "Compensatory circle", *[seat_cell(0, data["compensatory"][p]) for p in parties],
        seat_cell(0, data["size"]),
    ])
    rows.append([
        "TOTAL (national target)",
        *[seat_cell(data["original_totals"][p], data["targets"][p]) for p in parties],
        seat_cell(data["total"], data["total"]),
    ])
    return headers, rows, highlighted


def district_losses(data):
    districts = data["current_caps"]
    parties = data["parties"]
    district_rows = []
    for district in districts:
        loss = districts[district] - data["caps"][district]
        if loss:
            excluded = [p for p in parties if data["original"][district][p] > 0
                        and data["remaining"][district][p] == 0]
            district_rows.append([district, f"-{loss}", ", ".join(excluded) or "-"])
    return district_rows


def report_sections(data):
    headers, rows, highlights = matrix_table(data)
    return (
        ("Mandate matrix: original(change); TOTAL includes compensation", headers, rows, highlights),
        ("Districts losing mandates", ["District", "Change", "Lost local representation"], district_losses(data), {}),
    )


def print_table(headers, rows, *, highlights=None, color=False, max_width=60):
    highlights = highlights or {}
    strings = [[str(cell) for cell in row] for row in rows]
    widths = [max(len(header), min(max_width, max([len(header), *[len(row[i]) for row in strings]])))
              for i, header in enumerate(headers)]
    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)).rstrip())
    for row_index, row in enumerate(strings):
        wrapped = [textwrap.wrap(cell, width=width, break_long_words=False,
                                 break_on_hyphens=False) or [""]
                   for cell, width in zip(row, widths)]
        for line in zip_longest(*wrapped, fillvalue=""):
            cells = []
            for column, (cell, width) in enumerate(zip(line, widths)):
                padded = cell.ljust(width)
                if color and (row_index, column) in highlights:
                    padded = f"{highlights[row_index, column]}{padded}{RESET_COLOR}"
                cells.append(padded)
            print("  ".join(cells).rstrip())
    if not strings:
        print("(none)")


def print_report(results, *, color=False):
    print("MINIMUM COMPENSATORY NATIONAL CIRCLE")
    for note in NOTES:
        print(f"- {note}")
    for year, data in results.items():
        print(f"\n{year}\n")
        print(f"Minimum compensatory circle: {data['size']} mandates")
        print(f"District mandates: {data['total'] - data['size']}; final national total: {data['total']}")
        for title, headers, rows, highlights in report_sections(data):
            print(f"\n{title}")
            print_table(headers, rows, highlights=highlights, color=color)


def write_report(results, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["MINIMUM COMPENSATORY NATIONAL CIRCLE"])
        for note in NOTES:
            writer.writerow(["Note", note])
        for year, data in results.items():
            writer.writerow([])
            writer.writerow(["Year", year])
            writer.writerow(["Minimum compensatory mandates", data["size"]])
            writer.writerow(["District mandates", data["total"] - data["size"]])
            writer.writerow(["Final national mandates", data["total"]])
            for title, headers, rows, _ in report_sections(data):
                writer.writerow([])
                writer.writerow([title])
                writer.writerow(headers)
                writer.writerows(rows)
                if not rows:
                    writer.writerow(["(none)"])


def plot_sizes(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    years = list(results)
    positions = list(range(len(years)))
    sizes = [data["size"] for data in results.values()]
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(positions, sizes, marker="o", linewidth=1.8, markersize=6, color="tab:blue")
    for position, size in zip(positions, sizes):
        ax.annotate(str(size), (position, size), xytext=(0, 10), textcoords="offset points", ha="center")
    ax.set_xticks(positions, years, fontsize=10, fontweight="bold")
    ax.set_xlabel("Election Year", fontsize=11)
    ax.set_ylabel("Minimum compensatory circle (mandates)", fontsize=11)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(0, max(1, max(sizes)) * 1.15 + 1)
    ax.set_title("Portugal: Minimum Compensatory National Circle\nExact match to national d'Hondt party totals", fontsize=12, fontweight="bold", pad=14)
    ax.grid(True, linestyle=":", alpha=0.6)
    fig.text(0.5, 0.025, "226 domestic mandates; electorate-based district d'Hondt. Overseas seats excluded.\nElection years are equally spaced.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(path, dpi=200)
    finally:
        plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--csv", "--output", dest="csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="Red for complete district-party losses, yellow for partial losses; auto colors terminal output.")
    args = parser.parse_args(argv)
    try:
        paths = [path.resolve() for path in (args.source, args.csv, args.graph)]
        if len(set(paths)) != len(paths):
            raise ValueError("Source, CSV report, and graph must use distinct paths.")
        results = build_analysis(args.source)
        plot_sizes(results, args.graph)
        write_report(results, args.csv)
    except (OSError, ValueError, csv.Error, ImportError) as exc:
        print(f"Compensatory analysis failed: {exc}", file=sys.stderr)
        return 1
    color = args.color == "always" or (
        args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    )
    print("Mandate validation passed for all source election years.\n")
    print_report(results, color=color)
    print(f"\nCSV report: {args.csv.resolve()}")
    print(f"Graph (equal election spacing): {args.graph.resolve()}")
    return 0


if __name__ == "__main__":
    # Windows redirected streams otherwise default to a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
