import csv
import math
import os
import numpy as np
from typing import Any, Dict, List, Optional, Tuple

from config import (
    ENABLE_MONTE_CARLO,
    ENABLE_DANISH_DP,
    ENABLE_STAIRCASE_PLOTS,
    SHOW_PLOT_POPUPS,
    SHOW_QUOTIENT_STATS_CONSOLE,
    SHOW_QUOTIENT_STATS_EXCEL,
    QUOTIENT_MILESTONES,
    GREEN, RED, BLUE, YELLOW, RESET,
    BG_RED_WHITE, BG_SHADE
)
from data_parser import sanitize_filename
from custom_methods import CUSTOM_METHODS_REGISTRY

# Try importing openpyxl for Excel export with fallback handling
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def get_dynamic_method_display_order() -> List[str]:
    """Generates the master display order dynamically from baseline + custom registry."""
    order = ["Current District D'Hondt", "Zurich DP"]
    if ENABLE_DANISH_DP:
        order.append("Danish DP")
    for m in CUSTOM_METHODS_REGISTRY:
        if m["name"] not in order:
            order.append(m["name"])
    return order


def get_method_order_index(method_name: str) -> int:
    """Returns the custom 1-based order index for a method."""
    order_list = get_dynamic_method_display_order()
    try:
        return order_list.index(method_name) + 1
    except ValueError:
        return 999


def print_district_legend_console(country_name: str, d2l_map: Dict[str, str]) -> None:
    """Prints the district-to-letter legend once per country in the terminal."""
    if ENABLE_MONTE_CARLO:
        return
    print("\n" + "="*80)
    print(f" 🏷️  DISTRICT LETTER DICTIONARY LEGEND: {country_name.upper()}")
    print("="*80)
    for d_name, letter in d2l_map.items():
        print(f"   [{letter:>2}] : {d_name}")
    print("="*80 + "\n")


def plot_staircase_sequence(
    country_name: str,
    year: str, 
    method_name: str, 
    order_idx: int,
    entries: List[Tuple[int, int, str, str]], 
    dips: int, 
    pairs: int, 
    mag: int,
    x_bounds: Tuple[int, int],
    y_max: int
) -> None:
    """Saves an individual high-resolution PNG chart to 'graph_inversions_<country_name>/'."""
    if not ENABLE_STAIRCASE_PLOTS or ENABLE_MONTE_CARLO or not entries:
        return

    try:
        import matplotlib
        if not SHOW_PLOT_POPUPS:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️ matplotlib not installed. Skipping graph generation. (Install via: pip install matplotlib)")
        return

    folder_name = f"graph_inversions_{sanitize_filename(country_name).lower()}"
    os.makedirs(folder_name, exist_ok=True)

    x_vals = list(range(len(entries)))
    y_seats = [e[1] for e in entries]

    running_peak = []
    curr_peak = 0
    for s in y_seats:
        if s > curr_peak:
            curr_peak = s
        running_peak.append(curr_peak)

    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(x_vals, running_peak, color='gray', linestyle='--', alpha=0.75, linewidth=1.5, label='Running Peak (M3 Reference)')
    ax.fill_between(x_vals, y_seats, running_peak, color='red', alpha=0.18, label=f'Displacement Depth Gap (M3 = {mag})')
    ax.step(x_vals, y_seats, where='mid', color='#1f77b4', linewidth=2.0, label='Allocated Mandates')

    dip_x, dip_y = [], []
    for i in range(len(y_seats) - 1):
        if y_seats[i] > y_seats[i + 1]:
            dip_x.append(i + 1)
            dip_y.append(y_seats[i + 1])

    if dip_x:
        ax.scatter(dip_x, dip_y, color='red', zorder=5, s=35, label=f'Local Dips (M1 = {dips})')

    ax.set_xlim(x_bounds[0], x_bounds[1])
    ax.set_ylim(-0.5, y_max)

    ax.set_title(f"Electoral Staircase Profile: {method_name} ({country_name.title()} - {year})\nLocal Dips (M1): {dips}  |  Dominance Pairs (M2): {pairs}  |  Displacement Depth (M3): {mag}", fontsize=11, fontweight='bold')
    ax.set_xlabel("Ordinal Rank (Sorted by Raw Votes Ascending)", fontsize=10)
    ax.set_ylabel("Mandates Allocated", fontsize=10)
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper left', frameon=True)

    plt.tight_layout()

    filename = f"{year}_{order_idx}_{sanitize_filename(method_name)}.png"
    file_path = os.path.join(folder_name, filename)
    plt.savefig(file_path, dpi=200)

    if SHOW_PLOT_POPUPS:
        plt.show()
    else:
        plt.close(fig)


def plot_combined_year_comparison(
    country_name: str,
    year: str,
    methods_data: List[Dict[str, Any]],
    x_bounds: Tuple[int, int],
    y_max: int
) -> None:
    """Generates a grid containing side-by-side subplots for methods in an election year."""
    if not ENABLE_STAIRCASE_PLOTS or ENABLE_MONTE_CARLO or not methods_data:
        return

    try:
        import matplotlib
        if not SHOW_PLOT_POPUPS:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    folder_name = f"graph_inversions_{sanitize_filename(country_name).lower()}"
    os.makedirs(folder_name, exist_ok=True)

    num_methods = len(methods_data)
    cols = 2
    rows = math.ceil(num_methods / cols)

    fig, axes = plt.subplots(rows, cols, figsize=(16, 4.5 * rows), sharex=True, sharey=True)
    axes_flat = axes.flatten() if num_methods > 1 else [axes]

    for idx, m_info in enumerate(methods_data):
        ax = axes_flat[idx]
        method_name = m_info["method_name"]
        entries = m_info["entries"]
        dips = m_info["dips"]
        pairs = m_info["pairs"]
        mag = m_info["mag"]

        x_vals = list(range(len(entries)))
        y_seats = [e[1] for e in entries]

        running_peak = []
        curr_peak = 0
        for s in y_seats:
            if s > curr_peak:
                curr_peak = s
            running_peak.append(curr_peak)

        ax.plot(x_vals, running_peak, color='gray', linestyle='--', alpha=0.7, linewidth=1.2)
        ax.fill_between(x_vals, y_seats, running_peak, color='red', alpha=0.15)
        ax.step(x_vals, y_seats, where='mid', color='#1f77b4', linewidth=1.8)

        dip_x, dip_y = [], []
        for i in range(len(y_seats) - 1):
            if y_seats[i] > y_seats[i + 1]:
                dip_x.append(i + 1)
                dip_y.append(y_seats[i + 1])

        if dip_x:
            ax.scatter(dip_x, dip_y, color='red', zorder=5, s=25)

        ax.set_xlim(x_bounds[0], x_bounds[1])
        ax.set_ylim(-0.5, y_max)

        ax.set_title(f"{method_name}\nM1 (Dips): {dips} | M2 (Pairs): {pairs} | M3 (Depth): {mag}", fontsize=10, fontweight='bold')
        ax.grid(True, linestyle=':', alpha=0.5)

    for idx in range(num_methods, len(axes_flat)):
        fig.delaxes(axes_flat[idx])

    fig.suptitle(f"SIDE-BY-SIDE ELECTORAL STAIRCASE COMPARISON: {country_name.upper()} ({year})", fontsize=14, fontweight='bold')
    fig.text(0.5, 0.01, "Ordinal Rank (Sorted by Raw Votes Ascending)", ha='center', fontsize=11)
    fig.text(0.01, 0.5, "Mandates Allocated", va='center', rotation='vertical', fontsize=11)

    plt.tight_layout(rect=[0.02, 0.02, 0.98, 0.96])

    combined_file = os.path.join(folder_name, f"{year}_COMPARE_ALL_METHODS.png")
    plt.savefig(combined_file, dpi=200)

    if SHOW_PLOT_POPUPS:
        plt.show()
    else:
        plt.close(fig)

    print(f" {GREEN}🖼️  YEARLY COMPARISON GRID GENERATED:{RESET} '{combined_file}'")


def plot_method_all_years_comparison(
    country_name: str,
    method_name: str,
    year_data_list: List[Dict[str, Any]],
    x_bounds: Tuple[int, int],
    y_max: int
) -> None:
    """Generates a master grid image containing subplots for ONE method across ALL election years."""
    if not ENABLE_STAIRCASE_PLOTS or ENABLE_MONTE_CARLO or not year_data_list:
        return

    try:
        import matplotlib
        if not SHOW_PLOT_POPUPS:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    folder_name = f"graph_inversions_{sanitize_filename(country_name).lower()}"
    os.makedirs(folder_name, exist_ok=True)

    num_years = len(year_data_list)
    cols = 3 if num_years >= 5 else 2
    rows = math.ceil(num_years / cols)

    fig, axes = plt.subplots(rows, cols, figsize=(5.5 * cols, 4.0 * rows), sharex=True, sharey=True)
    axes_flat = axes.flatten() if num_years > 1 else [axes]

    for idx, y_info in enumerate(year_data_list):
        ax = axes_flat[idx]
        year_str = y_info["year"]
        entries = y_info["entries"]
        dips = y_info["dips"]
        pairs = y_info["pairs"]
        mag = y_info["mag"]

        x_vals = list(range(len(entries)))
        y_seats = [e[1] for e in entries]

        running_peak = []
        curr_peak = 0
        for s in y_seats:
            if s > curr_peak:
                curr_peak = s
            running_peak.append(curr_peak)

        ax.plot(x_vals, running_peak, color='gray', linestyle='--', alpha=0.7, linewidth=1.2)
        ax.fill_between(x_vals, y_seats, running_peak, color='red', alpha=0.15)
        ax.step(x_vals, y_seats, where='mid', color='#1f77b4', linewidth=1.8)

        dip_x, dip_y = [], []
        for i in range(len(y_seats) - 1):
            if y_seats[i] > y_seats[i + 1]:
                dip_x.append(i + 1)
                dip_y.append(y_seats[i + 1])

        if dip_x:
            ax.scatter(dip_x, dip_y, color='red', zorder=5, s=25)

        ax.set_xlim(x_bounds[0], x_bounds[1])
        ax.set_ylim(-0.5, y_max)

        ax.set_title(f"Year {year_str}\nM1 (Dips): {dips} | M2 (Pairs): {pairs} | M3 (Depth): {mag}", fontsize=10, fontweight='bold')
        ax.grid(True, linestyle=':', alpha=0.5)

    for idx in range(num_years, len(axes_flat)):
        fig.delaxes(axes_flat[idx])

    fig.suptitle(f"MULTI-YEAR ELECTORAL STAIRCASE EVOLUTION: {method_name.upper()} ({country_name.upper()})", fontsize=14, fontweight='bold')
    fig.text(0.5, 0.01, "Ordinal Rank (Sorted by Raw Votes Ascending)", ha='center', fontsize=11)
    fig.text(0.01, 0.5, "Mandates Allocated", va='center', rotation='vertical', fontsize=11)

    plt.tight_layout(rect=[0.02, 0.02, 0.98, 0.96])

    combined_file = os.path.join(folder_name, f"COMPARE_{sanitize_filename(method_name)}_ALL_YEARS.png")
    plt.savefig(combined_file, dpi=200)

    if SHOW_PLOT_POPUPS:
        plt.show()
    else:
        plt.close(fig)

    print(f" {GREEN}🖼️  MULTI-YEAR METHOD COMPARISON GRID GENERATED:{RESET} '{combined_file}'")


def plot_monte_carlo_trends(
    country_name: str, 
    yearly_mc_logs: Dict[str, Dict[str, Dict[str, List[Any]]]]
) -> None:
    """Plots trend lines across chronological election years with 5th-95th percentile error bars."""
    if not ENABLE_MONTE_CARLO or not yearly_mc_logs:
        return

    try:
        import matplotlib
        if not SHOW_PLOT_POPUPS:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️ matplotlib not installed. Skipping Monte Carlo trend plots.")
        return

    folder_name = f"{sanitize_filename(country_name).lower()}_trends"
    os.makedirs(folder_name, exist_ok=True)

    sorted_years = sorted(yearly_mc_logs.keys())
    x_indices = list(range(len(sorted_years)))

    target_methods = [
        ("Zurich DP", -0.2, "#1f77b4", "^"),                          # Left offset, Blue triangle
        ("Current District D'Hondt", 0.0, "#d62728", "o"),             # Center offset, Red circle
        ("Exquisite Progressive Pool Method", 0.2, "#2ca02c", "s")     # Right offset, Green square
    ]

    metrics_to_plot = [
        ("inversions", "Intra-District Inversions (Accuracy)", "Inversion Count", "Intra_District_Inversions"),
        ("dips", "Global Local Dips (M1)", "Dip Count", "Global_Local_Dips"),
        ("pairs", "Global Dominance Pairs (M2)", "Pair Count", "Global_Dominance_Pairs"),
        ("mag", "Global Displacement Magnitude (M3)", "Displacement Seat Depth", "Displacement_Magnitude"),
        ("gallagher", "Unweighted District Gallagher Index", "Gallagher Score", "Unweighted_Gallagher"),
        ("weighted_gallagher", "Seat-Weighted District Gallagher Index", "Weighted Gallagher Score", "Weighted_Gallagher"),
        ("coverage", "Geographic Footprint (Active Seat Cells)", "Active Cells Count", "Geographic_Footprint")
    ]

    for metric_key, metric_title, y_label, file_suffix in metrics_to_plot:
        fig, ax = plt.subplots(figsize=(10, 6))

        for m_name, x_offset, color_code, marker_style in target_methods:
            means = []
            err_lowers = []
            err_uppers = []
            x_positions = []

            for idx, yr in enumerate(sorted_years):
                vals = yearly_mc_logs[yr][metric_key].get(m_name, [])
                if not vals:
                    continue
                sorted_vals = sorted(vals)
                mean_v = sum(sorted_vals) / len(sorted_vals)
                
                p05 = float(np.percentile(sorted_vals, 5, method="linear"))
                p95 = float(np.percentile(sorted_vals, 95, method="linear"))

                means.append(mean_v)
                # Clamp to zero: Matplotlib treats yerr as a *length*, not a signed value.
                # For skewed / discrete metrics (e.g. coverage), the 5th percentile can
                # legitimately sit above the mean, which would produce a negative length.
                err_lowers.append(max(0.0, mean_v - p05))
                err_uppers.append(max(0.0, p95 - mean_v))
                x_positions.append(idx + x_offset)

            if means:
                ax.errorbar(
                    x_positions, means, 
                    yerr=[err_lowers, err_uppers], 
                    fmt=f"{marker_style}-", 
                    color=color_code, 
                    ecolor=color_code,
                    capsize=4, 
                    capthick=1.5,
                    linewidth=1.8, 
                    label=m_name
                )

        ax.set_xticks(x_indices)
        ax.set_xticklabels(sorted_years, fontsize=10, fontweight='bold')
        ax.set_xlabel("Election Year (Chronological)", fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)
        ax.set_title(f"Monte Carlo Trend ({country_name.title()}): {metric_title}\n(Points = Mean, Bars = 5th to 95th Percentile Range)", fontsize=11, fontweight='bold')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best', frameon=True)

        plt.tight_layout()
        file_path = os.path.join(folder_name, f"TREND_{file_suffix}.png")
        plt.savefig(file_path, dpi=200)

        if SHOW_PLOT_POPUPS:
            plt.show()
        else:
            plt.close(fig)

        print(f" {GREEN}📈 MONTE CARLO TREND GRAPH GENERATED:{RESET} '{file_path}'")


def print_quotient_efficiency_table(
    title: str, 
    method_milestones: Dict[str, Dict[int, Dict[str, Any]]], 
    total_mandates: int
) -> None:
    if not SHOW_QUOTIENT_STATS_CONSOLE or ENABLE_MONTE_CARLO:
        return

    print("\n" + "="*110)
    print(f" 📈 {title} — QUOTIENT EVALUATION MILESTONES (Total Mandates: {total_mandates})")
    print("="*110)
    
    header_str = f"{'Pool Method':<35} | " + " | ".join(f"{str(p)+'%':>6}" for p in QUOTIENT_MILESTONES) + " | Total Skipped"
    print(header_str)
    print("-" * len(header_str))

    for idx, (method_name, m_dict) in enumerate(method_milestones.items()):
        row_bg = BG_SHADE if idx % 2 != 0 else ""
        row_str = f"{row_bg}{method_name:<35}\033[0m | "
        cols = []
        for p in QUOTIENT_MILESTONES:
            q_eval = m_dict.get(p, {}).get("quotients_eval", 0)
            cols.append(f"{q_eval:>6}")
        row_str += " | ".join(cols)
        
        final_skipped = m_dict.get(100, {}).get("skipped", 0)
        row_str += f" | {final_skipped:>13,}"
        print(row_str)

    print("-" * len(header_str))
    print()


def export_quotient_analysis_excel(
    country_name: str, 
    quotient_records: List[Dict[str, Any]], 
    milestone_summary_records: Optional[List[Dict[str, Any]]] = None,
    d2l_map: Optional[Dict[str, str]] = None
) -> None:
    if not quotient_records:
        return

    excel_filename = f"{country_name}_quotient_analysis.xlsx"
    csv_filename = f"{country_name}_quotient_analysis.csv"

    if HAS_OPENPYXL:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_title = Font(name="Calibri", size=14, bold=True, color="1F4E78")
        fill_header = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        fill_allocated = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
        fill_skipped = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        border_thin = Border(
            left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
        )
        align_center = Alignment(horizontal='center', vertical='center')
        align_right = Alignment(horizontal='right', vertical='center')
        align_left = Alignment(horizontal='left', vertical='center')

        # SHEET 0: District Letter Mapping Legend
        if d2l_map:
            ws_leg = wb.create_sheet(title="District Key Legend")
            ws_leg.views.sheetView[0].showGridLines = True
            ws_leg.cell(row=1, column=1, value=f"{country_name.upper()} — DISTRICT LETTER DICTIONARY LEGEND").font = font_title
            
            leg_headers = ["Letter Key", "District Name"]
            for col_num, h_text in enumerate(leg_headers, 1):
                cell = ws_leg.cell(row=3, column=col_num, value=h_text)
                cell.font = font_header
                cell.fill = fill_header
                cell.alignment = align_center

            for r_idx, (d_name, letter) in enumerate(d2l_map.items(), start=4):
                c1 = ws_leg.cell(row=r_idx, column=1, value=letter)
                c2 = ws_leg.cell(row=r_idx, column=2, value=d_name)
                c1.alignment = align_center
                c2.alignment = align_left
                c1.border = border_thin
                c2.border = border_thin

        # SHEET 1: Quotient Efficiency Milestones Summary
        if SHOW_QUOTIENT_STATS_EXCEL and milestone_summary_records:
            ws_eff = wb.create_sheet(title="Efficiency Milestones")
            ws_eff.views.sheetView[0].showGridLines = True

            ws_eff.cell(row=1, column=1, value=f"{country_name.upper()} — POOL ALLOCATION QUOTIENT EFFICIENCY SUMMARY").font = font_title

            eff_headers = ["Year", "Pool Method", "Total Mandates"] + [f"{p}% Seats" for p in QUOTIENT_MILESTONES] + ["Total Skipped", "Final Efficiency %"]
            for col_num, h_text in enumerate(eff_headers, 1):
                cell = ws_eff.cell(row=3, column=col_num, value=h_text)
                cell.font = font_header
                cell.fill = fill_header
                cell.alignment = align_center

            for row_idx, rec in enumerate(milestone_summary_records, start=4):
                m_dict = rec["Milestones"]
                total_m = rec["Total Mandates"]
                final_skipped = m_dict.get(100, {}).get("skipped", 0)
                final_eff = m_dict.get(100, {}).get("efficiency_pct", 100.0)

                row_vals = [rec["Year"], rec["Method"], total_m]
                for p in QUOTIENT_MILESTONES:
                    row_vals.append(m_dict.get(p, {}).get("quotients_eval", 0))
                row_vals.extend([final_skipped, f"{final_eff:.1f}%"])

                for col_idx, val in enumerate(row_vals, start=1):
                    cell = ws_eff.cell(row=row_idx, column=col_idx, value=val)
                    cell.border = border_thin
                    if col_idx in (1, 2):
                        cell.alignment = align_left
                    elif col_idx == len(row_vals):
                        cell.alignment = align_right
                    else:
                        cell.alignment = align_center

        # SHEET 2: Master All Quotients Log
        ws_master = wb.create_sheet(title="Master All Quotients")
        ws_master.views.sheetView[0].showGridLines = True

        ws_master.cell(row=1, column=1, value=f"{country_name.upper()} ELECTORAL POOL ALLOCATION — MASTER QUOTIENT ANALYSIS LOG").font = font_title
        
        master_headers = ["Year", "Pool Method", "Rank/Step", "District", "Party", "Quotient", "Divisor Used", "Seat Attempt #", "Allocated?", "Running Total"]
        for col_num, h_text in enumerate(master_headers, 1):
            cell = ws_master.cell(row=3, column=col_num, value=h_text)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        for row_idx, rec in enumerate(quotient_records, start=4):
            is_yes = rec["Allocated"] == "Yes"
            current_fill = fill_allocated if is_yes else fill_skipped

            row_data = [
                (rec["Year"], align_center, "@"),
                (rec["Method"], align_left, "@"),
                (rec["Step"], align_center, "0"),
                (rec["District"], align_left, "@"),
                (rec["Party"], align_left, "@"),
                (rec["Quotient"], align_right, "0.0000"),
                (rec["Divisor"], align_right, "0"),
                (rec["Seat Attempt"], align_center, "0"),
                (rec["Allocated"], align_center, "@"),
                (rec["Running Total"], align_center, "0")
            ]

            for col_idx, (val, align, num_fmt) in enumerate(row_data, start=1):
                cell = ws_master.cell(row=row_idx, column=col_idx, value=val)
                cell.fill = current_fill
                cell.alignment = align
                cell.border = border_thin
                cell.number_format = num_fmt

        for ws_sheet in wb.worksheets:
            for col in ws_sheet.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.row == 1: continue
                    val_str = str(cell.value or "")
                    if len(val_str) > max_len: max_len = len(val_str)
                ws_sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(excel_filename)
        print(f" {GREEN}✓ EXCEL QUOTIENT ANALYSIS GENERATED:{RESET} '{excel_filename}' ({len(quotient_records):,} steps logged)")

    else:
        with open(csv_filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Year", "Pool Method", "Rank/Step", "District", "Party", "Quotient", "Divisor Used", "Seat Attempt #", "Allocated?", "Running Total"])
            for rec in quotient_records:
                writer.writerow([
                    rec["Year"], rec["Method"], rec["Step"], rec["District"], rec["Party"],
                    f"{rec['Quotient']:.4f}", rec["Divisor"], rec["Seat Attempt"], rec["Allocated"], rec["Running Total"]
                ])
        print(f" {GREEN}✓ CSV QUOTIENT ANALYSIS GENERATED:{RESET} '{csv_filename}' ({len(quotient_records):,} steps logged)")


def print_top_displacement_examples(incidents: List[Dict[str, Any]], title: str, top_n: int = 5) -> None:
    if not incidents:
        print(f"   {title}: 0 displacement depth gap incidents detected.")
        return
    
    sorted_inc = sorted(incidents, key=lambda x: (x.get("gap", x.get("displacement_depth", 0)), x.get("victim_votes", 0)), reverse=True)
    unique_inc = []
    seen = set()
    for inc in sorted_inc:
        key = (inc.get("peak_party"), inc.get("peak_district"), inc.get("victim_party"), inc.get("victim_district"), inc.get("gap", inc.get("displacement_depth", 0)))
        if key not in seen:
            seen.add(key)
            unique_inc.append(inc)

    print(f"\n   📌 {title} (Top {min(top_n, len(unique_inc))} Displacement Depth Penalties):")
    for idx, inc in enumerate(unique_inc[:top_n], 1):
        if "peak_party" in inc:
            print(
                f"      {idx}. Party '{inc['peak_party']}' in '{inc['peak_district']}' got {inc['peak_seats']} seat(s) with {inc['peak_votes']:,} votes, "
                f"while '{inc['victim_party']}' in '{inc['victim_district']}' got only {inc['victim_seats']} seat(s) despite having {inc['victim_votes']:,} votes "
                f"→ [Displacement Gap: {inc['gap']} seat(s)]"
            )
        else:
            print(
                f"      {idx}. District '{inc.get('district')}' | Victim: '{inc.get('victim_party')}' | "
                f"Beneficiary: '{inc.get('beneficiary_party')}' → -{inc.get('displacement_depth')} seats"
            )


def print_structured_table(
    title: str, 
    matrix: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    party_totals: Dict[str, int], 
    district_caps: Dict[str, int], 
    mode: str = "seats", 
    marks: Optional[Dict[str, Dict[str, str]]] = None, 
    weights_r: Optional[Dict[str, float]] = None, 
    weights_c: Optional[Dict[str, float]] = None, 
    custom_row_totals: Optional[Dict[str, int]] = None,
    is_valid: bool = True,
    errors: Optional[List[str]] = None
) -> None:
    if ENABLE_MONTE_CARLO:
        return
        
    print("\n" + "="*80)
    if not is_valid and errors:
        print(f"{BG_RED_WHITE} ❌ {title} — INTEGRITY FAILURE ({len(errors)} ERRORS DETECTED) {RESET}")
        print("="*80)
        print(f"{RED} ⚠️ WARNING DETAILS:{RESET}")
        for err in errors:
            print(f"{RED}   - {err}{RESET}")
        print("-" * 80)
    else:
        print(f" {title} ")
        print("="*80)
    
    print(f"{'District':<20}", end="")
    for party in party_caps.keys():
        print(f"{party:>10}", end="")
    print(f"{'Total':>10} {'(Weight)':>14}" if weights_r else f"{'Total':>10}")
    print("-" * (20 + 10 * len(party_caps) + (25 if weights_r else 10)))

    for idx, (district, allocations) in enumerate(matrix.items()):
        row_bg = BG_SHADE if idx % 2 != 0 else ""
        print(f"{row_bg}{district:<20}", end="")
        for party in party_caps.keys():
            val = allocations[party]
            
            if mode == "votes":
                print(f"{val:>10,}" if val > 0 else f"{'-':>10}", end="")
            elif mode == "diff":
                val_str = f"+{val}" if val > 0 else (f"{val}" if val < 0 else "-")
                print(f"{val_str:>10}", end="")
            else:
                mark = marks.get(district, {}).get(party, "") if marks else ""
                val_str = f"{val}{mark}" if (val > 0 or mark) else "-"
                
                if mark == "+":
                    print(f"\033[42m\033[30m{val_str:>10}\033[0m{row_bg}", end="")
                elif mark == "-":
                    print(f"\033[41m\033[97m{val_str:>10}\033[0m{row_bg}", end="")
                else:
                    print(f"{val_str:>10}", end="")
        
        r_total = custom_row_totals[district] if custom_row_totals is not None else district_caps[district]
        if weights_r:
            print(f"{r_total:>10} ({weights_r[district]:.4f})\033[0m")
        else:
            print(f"{r_total:>10}\033[0m")
            
    print("-" * (20 + 10 * len(party_caps) + (25 if weights_r else 10)))
    
    bottom_label = "Total Raw Votes" if mode == "votes" else ("Net Allocation Change" if mode == "diff" else "Mandatos Total")
    print(f"{bottom_label:<20}", end="")
    
    for party in party_caps.keys():
        val = party_totals[party]
        if mode == "votes":
            print(f"{val:>10,}", end="")
        elif mode == "diff":
            val_str = f"+{val}" if val > 0 else (f"{val}" if val < 0 else "-")
            print(f"{val_str:>10}", end="")
        else:
            print(f"{val:>10}", end="")
            
    print(f"{sum(party_totals.values()):>10,}" if mode == "votes" else f"{sum(party_totals.values()):>10}")
    
    if weights_c:
        print(f"{'(Party Weight)':<20}", end="")
        for party in party_caps.keys():
            w_val = weights_c[party]
            w_str = "inf" if w_val == float('inf') else f"{w_val:.4f}"
            print(f"({w_str:>8})", end="")
        print()
    print()


def render_scorecard_table(title_label: str, metric_repository: Dict[str, List[Any]], simulations_count: int, precision_val: int = 2, higher_is_better: bool = False, csv_accumulator: Optional[List[List[Any]]] = None) -> None:
    if not metric_repository or simulations_count <= 0:
        return

    win_counts = {name: 0 for name in metric_repository.keys()}
    for iter_idx in range(simulations_count):
        if higher_is_better:
            best_metric_found = max(metric_repository[name][iter_idx] for name in metric_repository.keys())
        else:
            best_metric_found = min(metric_repository[name][iter_idx] for name in metric_repository.keys())
            
        for name in metric_repository.keys():
            if metric_repository[name][iter_idx] == best_metric_found:
                win_counts[name] += 1

    win_header_label = "Wins (Highest)" if higher_is_better else "Wins (Fewest)"
    
    print(f"\n{title_label}")
    print("-" * 135)
    print(f"{'Electoral Allocation System':<38} | {win_header_label:<14} | {'Average (Mean)':<14} | {'Median (50th)':<13} | {'Minimum':<7} | {'Maximum':<7} | {'Typical Range (5th-95th)':<24}")
    print("-" * 135)
    
    if csv_accumulator is not None:
        csv_accumulator.append([])
        csv_accumulator.append([title_label])
        csv_accumulator.append(["Electoral Allocation System", win_header_label, "Average (Mean)", "Median (50th)", "Minimum", "Maximum", "Typical Range (5th-95th)"])

    for idx, name in enumerate(metric_repository.keys()):
        row_bg = BG_SHADE if idx % 2 != 0 else ""
        raw_scores = metric_repository[name]
        sorted_scores = sorted(raw_scores)
        
        win_pct = (win_counts[name] / simulations_count) * 100 if simulations_count > 0 else 0.0
        mean_val = sum(raw_scores) / len(raw_scores) if raw_scores else 0.0
        median_val = sorted_scores[int(len(sorted_scores) * 0.5)] if sorted_scores else 0.0
        min_val = sorted_scores[0] if sorted_scores else 0.0
        max_val = sorted_scores[-1] if sorted_scores else 0.0
        p05 = sorted_scores[int(len(sorted_scores) * 0.05)] if sorted_scores else 0.0
        p95 = sorted_scores[min(len(sorted_scores) - 1, int(len(sorted_scores) * 0.95))] if sorted_scores else 0.0
        
        if precision_val == 2:
            range_str = f"{p05:.2f} - {p95:.2f}"
            print(f"{row_bg}{name:<38} | {win_pct:>12.1f}% | {mean_val:>14.2f} | {median_val:>13.2f} | {min_val:>7.2f} | {max_val:>7.2f} | {range_str:>24}\033[0m")
            if csv_accumulator is not None:
                csv_accumulator.append([name, f"{win_pct:.1f}%", f"{mean_val:.2f}", f"{median_val:.2f}", f"{min_val:.2f}", f"{max_val:.2f}", range_str])
        else:
            range_str = f"{int(p05)} - {int(p95)}"
            print(f"{row_bg}{name:<38} | {win_pct:>12.1f}% | {mean_val:>14.2f} | {int(median_val):>13} | {int(min_val):>7} | {int(max_val):>7} | {range_str:>24}\033[0m")
            if csv_accumulator is not None:
                csv_accumulator.append([name, f"{win_pct:.1f}%", f"{mean_val:.2f}", str(int(median_val)), str(int(min_val)), str(int(max_val)), range_str])
            
    print("-" * 135 + "\n")