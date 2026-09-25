import csv
from typing import Any, Dict, List

from config import BLUE, ENABLE_MONTE_CARLO, ENABLE_STAIRCASE_PLOTS, GREEN, RED, RESET, YELLOW
from visuals_export import (
    get_method_order_index,
    plot_combined_year_comparison,
    plot_method_all_years_comparison,
    plot_monte_carlo_trends,
    plot_staircase_sequence,
    print_top_displacement_examples,
    render_scorecard_table,
)


def render_final_reports(
    all_method_names: List[str],
    trackers: Dict[str, Any],
    yearly_mc_logs: Dict[str, Any],
    meta_logs: Dict[str, Any],
    meta_mc_total_simulations: int,
    historical_election_count: int,
    global_max_possible_coverage: int,
    master_csv_rows: List[List[Any]],
    country_all_years_plot_data: Dict[str, Any],
    country_name: str
) -> None:
    """Generates charts, prints final scorecards, rankings, and writes the output CSV."""
    
    # Regional Plot Generation
    if ENABLE_MONTE_CARLO and yearly_mc_logs:
        plot_monte_carlo_trends(country_name, yearly_mc_logs)

    if not ENABLE_MONTE_CARLO and ENABLE_STAIRCASE_PLOTS and country_all_years_plot_data:
        all_first_seat_indices = []
        global_max_x_len = 0
        global_max_y_seats = 0

        for yr, yr_methods in country_all_years_plot_data.items():
            for m_info in yr_methods:
                entries = m_info["entries"]
                if entries:
                    global_max_x_len = max(global_max_x_len, len(entries))
                    global_max_y_seats = max(global_max_y_seats, max(e[1] for e in entries))
                    first_idx = next((i for i, e in enumerate(entries) if e[1] > 0), 0)
                    all_first_seat_indices.append(first_idx)

        country_earliest_idx = min(all_first_seat_indices) if all_first_seat_indices else 0
        country_x_start = max(0, country_earliest_idx - 10)
        country_x_end = global_max_x_len - 1 if global_max_x_len > 0 else 100
        country_y_max = global_max_y_seats + 1
        country_bounds = (country_x_start, country_x_end)

        for yr in sorted(country_all_years_plot_data.keys()):
            grid_methods = [m for m in country_all_years_plot_data[yr] if m["method_name"] != "Quadratic Pool Method"]
            plot_combined_year_comparison(country_name, yr, grid_methods, country_bounds, country_y_max)

        all_country_methods = []
        for yr, yr_methods in country_all_years_plot_data.items():
            for m_info in yr_methods:
                if m_info["method_name"] not in all_country_methods:
                    all_country_methods.append(m_info["method_name"])
        all_country_methods.sort(key=lambda m: get_method_order_index(m))

        for m_name in all_country_methods:
            method_years_data = []
            for yr in sorted(country_all_years_plot_data.keys()):
                for m_info in country_all_years_plot_data[yr]:
                    if m_info["method_name"] == m_name:
                        method_years_data.append({
                            "year": yr,
                            "entries": m_info["entries"],
                            "dips": m_info["dips"],
                            "pairs": m_info["pairs"],
                            "mag": m_info["mag"]
                        })
            plot_method_all_years_comparison(country_name, m_name, method_years_data, country_bounds, country_y_max)

        for yr in sorted(country_all_years_plot_data.keys()):
            for m_info in country_all_years_plot_data[yr]:
                order_idx = get_method_order_index(m_info["method_name"])
                plot_staircase_sequence(
                    country_name, yr, m_info["method_name"], order_idx,
                    m_info["entries"], m_info["dips"], m_info["pairs"], m_info["mag"],
                    x_bounds=country_bounds, y_max=country_y_max
                )

    # Summaries Output
    print("\n" + "#"*80)
    print(" METRIC LEADERSHIP RADAR: GLOBAL META COMPARISON DASHBOARD")
    print("#"*80)

    if ENABLE_MONTE_CARLO:
        print("\n================================================================================")
        print(" 📅 YEAR-BY-YEAR MONTE CARLO STOCHASTIC SCORECARDS")
        print("================================================================================")
        
        for year in sorted(yearly_mc_logs.keys()):
            y_logs = yearly_mc_logs[year]
            y_sim_count = len(y_logs["dips"]["Zurich DP"])
            
            print(f"\n" + "🎲 " * 40)
            print(f" 🗓️ ELECTION YEAR {year} — MONTE CARLO SCORECARDS ({y_sim_count:,} SIMULATION ITERATIONS)")
            print("🎲 " * 40)

            render_scorecard_table(f"1. [{year}] SYSTEM ACCURACY (FEWEST INTRA-DISTRICT INVERSIONS)", y_logs["inversions"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"2. [{year}] STAIRCASE METHOD 1 (FEWEST GLOBAL LOCAL DIPS)", y_logs["dips"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"3. [{year}] STAIRCASE METHOD 2 (FEWEST GLOBAL DOMINANCE PAIRS)", y_logs["pairs"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"4. [{year}] STAIRCASE METHOD 3 (LOWEST GLOBAL DISPLACEMENT MAGNITUDE)", y_logs["mag"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"5. [{year}] LOCAL PROPORTIONALITY (UNWEIGHTED DISTRICT GALLAGHER)", y_logs["gallagher"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"6. [{year}] SEAT-WEIGHTED PROPORTIONALITY (LOWEST WEIGHTED GALLAGHER)", y_logs["weighted_gallagher"], y_sim_count, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
            render_scorecard_table(f"7. [{year}] GEOGRAPHIC FOOTPRINT SPREAD (HIGHEST ACTIVE CELLS)", y_logs["coverage"], y_sim_count, precision_val=0, higher_is_better=True, csv_accumulator=master_csv_rows)

        print("\n" + "🏆 " * 40)
        print(f" 🌟 OVERALL META MONTE CARLO STOCHASTIC SCORECARDS ({meta_mc_total_simulations:,} TOTAL SIMULATION ITERATIONS)")
        print("🏆 " * 40)

        master_csv_rows.append(["==============================================================================="])
        master_csv_rows.append([f"🎲 OVERALL META MONTE CARLO STOCHASTIC SCORECARDS ({meta_mc_total_simulations:,} SIMULATION ITERATIONS)"])
        master_csv_rows.append(["==============================================================================="])

        render_scorecard_table("1. OVERALL SYSTEM ACCURACY (FEWEST INTRA-DISTRICT INVERSIONS)", meta_logs["inversions"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("2. OVERALL STAIRCASE METHOD 1 (FEWEST GLOBAL LOCAL DIPS)", meta_logs["dips"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("3. OVERALL STAIRCASE METHOD 2 (FEWEST GLOBAL DOMINANCE PAIRS)", meta_logs["pairs"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("4. OVERALL STAIRCASE METHOD 3 (LOWEST GLOBAL DISPLACEMENT MAGNITUDE)", meta_logs["mag"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("5. OVERALL LOCAL PROPORTIONALITY (UNWEIGHTED DISTRICT GALLAGHER)", meta_logs["gallagher"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("6. OVERALL SEAT-WEIGHTED PROPORTIONALITY (LOWEST WEIGHTED GALLAGHER)", meta_logs["weighted_gallagher"], meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("7. OVERALL GEOGRAPHIC FOOTPRINT SPREAD (HIGHEST ACTIVE CELLS)", meta_logs["coverage"], meta_mc_total_simulations, precision_val=0, higher_is_better=True, csv_accumulator=master_csv_rows)

    else:
        print("\n" + "🏛️ " * 40)
        print(" METRIC RADAR CODES: HISTORICAL BASELINE RECORDS (RAW RUNS ONLY)")
        print("🏛️ " * 40)

        print("\n================================================================================")
        print(" 📅 YEAR-BY-YEAR GLOBAL STAIRCASE METRIC BREAKDOWN & TAGGED SEQUENCES")
        print("================================================================================")
        
        for year in sorted(trackers["yearly_staircase_metrics"].keys()):
            print(f"\n" + "-"*90)
            print(f" 🗓️  ELECTION YEAR {year} DIAGNOSTIC RADAR")
            print("-" * 90)
            print(f"{'Electoral Allocation System':<38} | {'Global Dips':<12} | {'Dominance Pairs':<15} | {'Displacement Depth':<18}")
            print("-" * 90)
            
            for m_name in all_method_names:
                m_data = trackers["yearly_staircase_metrics"][year].get(m_name, {})
                dips = m_data.get("dips", 0)
                pairs = m_data.get("pairs", 0)
                mag = m_data.get("mag", 0)
                print(f"{m_name:<38} | {dips:>12,} | {pairs:>15,} | {mag:>18,}")
            
            print(f"\n   --- Tagged Mandate Sequences (Least Votes to Most Votes: DistrictKeyMandates) ---")
            for m_name in all_method_names:
                seq = trackers["yearly_staircase_metrics"][year].get(m_name, {}).get("sequence", "")
                print(f"   📌 Method: {m_name}")
                print(f"      {seq}")

            print(f"\n   --- Top 5 Displacement Depth Penalties for Year {year} ---")
            for m_name in all_method_names:
                m_incidents = trackers["yearly_displacement_incidents"][year].get(m_name, [])
                print_top_displacement_examples(m_incidents, f"Method: {m_name} ({year})", top_n=5)

        master_csv_rows.append(["==============================================================================="])
        master_csv_rows.append(["🏛️  HISTORICAL ARCHIVE PERFORMANCE HIGHLIGHT SUMMARY (RAW ENGINE ALLOCATIONS)"])
        master_csv_rows.append(["==============================================================================="])

        accuracy_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_inversion_tracker"][core_name])
        print("\n================================================================================")
        print(" 秤  HISTORICAL ARCHIVE RANKINGS BY ACCURACY (FEWEST INTRA-DISTRICT INVERSIONS)")
        print("================================================================================")
        for idx, name in enumerate(accuracy_rankings, 1):
            inv_count = trackers["global_inversion_tracker"][name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(accuracy_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {inv_count:,} total intra-district inversion anomalies")

        dips_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_staircase_dips_tracker"][core_name])
        print("\n================================================================================")
        print(" 🪜 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 1 (FEWEST GLOBAL LOCAL DIPS)")
        print("================================================================================")
        for idx, name in enumerate(dips_rankings, 1):
            dips_count = trackers["global_staircase_dips_tracker"][name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(dips_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {dips_count:,} total step dips in sorted array")

        pairs_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_staircase_pairs_tracker"][core_name])
        print("\n================================================================================")
        print(" 📈 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 2 (FEWEST GLOBAL DOMINANCE PAIRS)")
        print("================================================================================")
        for idx, name in enumerate(pairs_rankings, 1):
            pairs_count = trackers["global_staircase_pairs_tracker"][name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(pairs_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {pairs_count:,} total dominance pairs")

        mag_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_staircase_magnitude_tracker"][core_name])
        print("\n================================================================================")
        print(" 💥 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 3 (LOWEST GLOBAL DISPLACEMENT MAGNITUDE)")
        print("================================================================================")
        for idx, name in enumerate(mag_rankings, 1):
            mag_val = trackers["global_staircase_magnitude_tracker"][name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(mag_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {mag_val:,} total seats displacement depth penalty")

        print("\n================================================================================")
        print(" 🏆 ALL-TIME AGGREGATE TOP 5 DISPLACEMENT DEPTH PENALTIES BY METHOD")
        print("================================================================================")
        for m_name in all_method_names:
            print_top_displacement_examples(trackers["all_time_displacement_incidents"][m_name], f"All-Time Method: {m_name}", top_n=5)

        gallagher_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_historical_gallagher_tracker"][core_name])
        print("\n================================================================================")
        print(" 📊 HISTORICAL ARCHIVE RANKINGS BY LOCAL PROPORTIONALITY (UNWEIGHTED DISTRICT GALLAGHER)")
        print("================================================================================")
        for idx, name in enumerate(gallagher_rankings, 1):
            avg_g = trackers["global_historical_gallagher_tracker"][name] / max(1, historical_election_count)
            color_modifier = GREEN if idx == 1 else (RED if idx == len(gallagher_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {avg_g:.2f} average historical district Gallagher score")

        weighted_gallagher_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_historical_weighted_gallagher_tracker"][core_name])
        print("\n================================================================================")
        print(" 📊 HISTORICAL ARCHIVE RANKINGS BY SEAT-WEIGHTED PROPORTIONALITY (LOWEST WEIGHTED GALLAGHER)")
        print("================================================================================")
        for idx, name in enumerate(weighted_gallagher_rankings, 1):
            avg_wg = trackers["global_historical_weighted_gallagher_tracker"][name] / max(1, historical_election_count)
            color_modifier = GREEN if idx == 1 else (RED if idx == len(weighted_gallagher_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {avg_wg:.2f} average historical seat-weighted district Gallagher score")

        footprint_rankings = sorted(all_method_names, key=lambda core_name: trackers["global_coverage_tracker"][core_name], reverse=True)
        print("\n================================================================================")
        print(" 🗺️  HISTORICAL ARCHIVE RANKINGS BY GEOGRAPHIC FOOTPRINT (MAX SPREAD DIVERSITY)")
        print("================================================================================")
        for idx, name in enumerate(footprint_rankings, 1):
            cov_count = trackers["global_coverage_tracker"][name]
            cov_pct = (cov_count / global_max_possible_coverage) * 100
            color_modifier = BLUE if idx == 1 else (YELLOW if idx == len(footprint_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {cov_count:,} / {global_max_possible_coverage:,} active distribution cells ({cov_pct:.2f}%)")

    master_report_path = "master_electoral_report.csv"
    with open(master_report_path, "w", newline="", encoding="utf-8-sig") as master_f:
        report_writer = csv.writer(master_f)
        report_writer.writerows(master_csv_rows)