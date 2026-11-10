"""Track how close small districts are to losing one d'Hondt mandate.

Run: python small_districts_loss_analysis.py
Writes one CSV containing the summary and yearly details, plus a trend graph.
Selects districts with <= 6 mandates in the latest year and no seat decreases
between any supplied elections since 2015. District order follows the source CSV.
The margin is minimum integer voter loss / original electorate * 100, matching
the earlier Beja analysis. Other electorates and the 226-seat total stay fixed.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from check_voters_mandates import DEFAULT_SOURCE, TOTAL_MANDATES, apportion_mandates, read_elections
from dist_mandatos import print_table


ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / "small_districts_loss_analysis.csv"
DEFAULT_GRAPH = ROOT / "portugal_trends" / "TREND_Small_District_Seat_Loss_Margins.png"
DETAIL_FIELDS = (
    "District", "District_label", "Current_mandates", "Year", "Mandates_before",
    "Mandates_after", "Registered_voters", "Minimum_voter_loss", "Loss_pct",
    "Electorate_at_loss", "Last_safe_electorate", "Gaining_district",
)


def select_districts(elections):
    years = sorted(year for year in elections if int(year) >= 2015)
    if "2015" not in years:
        raise ValueError("The source must include 2015 to check for seat losses since 2015.")
    latest = elections[years[-1]]["mandates"]
    if any(set(elections[year]["mandates"]) != set(latest) for year in years):
        raise ValueError("Every election must contain the same districts.")
    selected = []
    for district, current in latest.items():
        history = [elections[year]["mandates"][district] for year in years]
        if current <= 6 and all(a <= b for a, b in zip(history, history[1:])):
            selected.append(district)
    if not selected:
        raise ValueError("No districts qualify: <= 6 current mandates and no decrease since 2015.")
    return years, selected


def minimum_voter_loss(voters, district, baseline):
    """Find the first integer loss that moves the district's last seat below rank 226.

    Count higher competing quotients using integer arithmetic. Exact ties follow
    the existing allocator: smaller electorate first, then alphabetical name.
    Independently recalculate all seats at both sides of the resulting boundary.
    """
    original = voters[district]
    seats = baseline[district]

    def loses(loss):
        remaining = original - loss
        if remaining == 0:
            return True
        ahead = seats - 1  # This district's earlier seats always rank higher.
        for other, count in voters.items():
            if other == district or count == 0:
                continue
            product = count * seats
            ahead += (product - 1) // remaining
            if product % remaining == 0 and (count, other) < (remaining, district):
                ahead += 1
        return ahead >= TOTAL_MANDATES

    low, high = 1, original
    while low < high:
        middle = (low + high) // 2
        if loses(middle):
            high = middle
        else:
            low = middle + 1
    loss = low
    changed = dict(voters)
    changed[district] = original - loss
    after = apportion_mandates(changed)
    changed[district] += 1
    just_before = apportion_mandates(changed)
    if after[district] != seats - 1 or just_before[district] != seats:
        raise ValueError(f"Could not verify the one-seat-loss boundary for {district}.")
    gains = [name for name in voters if after[name] > baseline[name]]
    if len(gains) != 1 or after[gains[0]] != baseline[gains[0]] + 1:
        raise ValueError(f"Expected exactly one district to receive {district}'s lost seat.")
    return {
        "Registered_voters": original, "Minimum_voter_loss": loss,
        "Loss_pct": 100 * loss / original, "Electorate_at_loss": original - loss,
        "Last_safe_electorate": original - loss + 1, "Gaining_district": gains[0],
        "Mandates_before": seats, "Mandates_after": after[district],
    }


def build_analysis(source):
    elections = read_elections(source)
    years, districts = select_districts(elections)
    for year in years:
        if apportion_mandates(elections[year]["voters"]) != elections[year]["mandates"]:
            raise ValueError(f"{year}: stored mandates do not match voter-based d'Hondt; run check_voters_mandates.py.")
    current = elections[years[-1]]["mandates"]
    rows = []
    for district in districts:
        for year in years:
            data = elections[year]
            rows.append({
                "District": district, "District_label": f"{district} ({current[district]})",
                "Current_mandates": current[district], "Year": year,
                **minimum_voter_loss(data["voters"], district, data["mandates"]),
            })
    return years, districts, rows


def summary_table(years, districts, rows):
    lookup = {(row["District"], row["Year"]): row for row in rows}
    headers = [f"District ({years[-1]} mandates)", "After losing 1", *years]
    values = []
    for district in districts:
        latest = lookup[district, years[-1]]
        values.append([
            latest["District_label"], latest["Current_mandates"] - 1,
            *[f"{lookup[district, year]['Loss_pct']:.2f}%" for year in years],
        ])
    return headers, values


def write_report(years, districts, rows, csv_path):
    """Keep the comparison summary and exact yearly details in one CSV report."""
    lookup = {(row["District"], row["Year"]): row for row in rows}
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["SUMMARY: minimum electorate loss needed to lose one mandate (%)"])
        writer.writerow([f"District ({years[-1]} mandates)", "After_losing_one", *[f"{year}_loss_pct" for year in years]])
        for district in districts:
            latest = lookup[district, years[-1]]
            writer.writerow([
                latest["District_label"], latest["Current_mandates"] - 1,
                *[f"{lookup[district, year]['Loss_pct']:.6f}" for year in years],
            ])
        writer.writerow([])
        writer.writerow(["YEARLY DETAILS: exact voter losses, cutoffs, and receiving districts"])
        writer = csv.DictWriter(stream, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows({**row, "Loss_pct": f"{row['Loss_pct']:.6f}"} for row in rows)


def plot_margins(years, districts, rows, graph_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    lookup = {(row["District"], row["Year"]): row for row in rows}
    # Use categorical positions: the election gaps are equal, not elapsed time.
    positions = list(range(len(years)))
    markers = ("o", "s", "^", "D", "v", "P", "X", "<")
    fig, ax = plt.subplots(figsize=(12, 7))
    for index, district in enumerate(districts):
        latest = lookup[district, years[-1]]
        ax.plot(
            positions, [lookup[district, year]["Loss_pct"] for year in years],
            marker=markers[index % len(markers)], color=plt.get_cmap("tab10")(index % 10),
            linewidth=1.8, markersize=6, label=latest["District_label"],
        )
    ax.set_xticks(positions, years, fontsize=10, fontweight="bold")
    ax.set_xlabel("Election Year (equally spaced)", fontsize=11)
    ax.set_ylabel("Electorate loss needed to lose one mandate (%)", fontsize=11)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_ylim(bottom=0)
    ax.set_title(
        "Portugal: Small Districts' Margin Before Losing One Mandate\n"
        f"No seat decreases since 2015; labels show {years[-1]} mandates",
        fontsize=12, fontweight="bold", pad=14,
    )
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=True, title="District (current seats)")
    fig.text(
        0.5, 0.025,
        "Minimum integer voter loss / that year's electorate. Lower = closer to losing a seat.\n"
        "226 mandates; other electorates held fixed. Losing one seat changes n to n - 1.",
        ha="center", fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(graph_path, dpi=200)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    args = parser.parse_args(argv)
    try:
        paths = [path.resolve() for path in (args.source, args.csv, args.graph)]
        if len(set(paths)) != len(paths):
            raise ValueError("Source, CSV report, and graph must use distinct paths.")
        years, districts, rows = build_analysis(args.source)
        plot_margins(years, districts, rows, args.graph)
        write_report(years, districts, rows, args.csv)
    except (OSError, ValueError, csv.Error, ImportError) as exc:
        print(f"Threshold analysis failed: {exc}", file=sys.stderr)
        return 1
    print("MINIMUM ELECTORATE LOSS NEEDED TO LOSE ONE MANDATE")
    print("Percentages use each year's original electorate; 226 seats and other electorates stay fixed.")
    print("District labels show latest mandates. Smaller percentages mean a smaller safety margin.\n")
    print_table(*summary_table(years, districts, rows))
    print(f"\nCSV report (summary and yearly details): {args.csv.resolve()}")
    print(f"Graph: {args.graph.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
