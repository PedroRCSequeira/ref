import time
from contextlib import nullcontext
from typing import Any, Dict, List

try:
    from wakepy import keep
    HAS_WAKEPY = True
except ImportError:
    HAS_WAKEPY = False

from audit import audit_datasets
from config import (
    ENABLE_DANISH_DP,
    ENABLE_MONTE_CARLO,
    GREEN,
    LOCAL_VARIATION,
    NATIONAL_VARIATION,
    QUOTIENT_MILESTONES,
    RANDOM_SEED,
    RESET,
    SIMULATIONS,
)
from custom_methods import CUSTOM_METHODS_REGISTRY
from data_parser import generate_district_letter_mapping
from monte_carlo import run_monte_carlo_simulation
from reporting import render_final_reports
from runner import run_historical_election
from visuals_export import export_quotient_analysis_excel, print_district_legend_console


def main() -> None:
    global_start_time = time.time()

    # Active Method Registrations
    active_custom_methods = [m for m in CUSTOM_METHODS_REGISTRY if m["enabled"]]
    all_method_names: List[str] = ["Current District D'Hondt", "Zurich DP"]
    if ENABLE_DANISH_DP:
        all_method_names.append("Danish DP")
    all_method_names.extend([m["name"] for m in active_custom_methods])

    pool_method_names = [m["name"] for m in active_custom_methods]

    # Global Performance Trackers
    trackers = {
        "all_method_names": all_method_names,
        "global_inversion_tracker": {name: 0 for name in all_method_names},
        "global_staircase_dips_tracker": {name: 0 for name in all_method_names},
        "global_staircase_pairs_tracker": {name: 0 for name in all_method_names},
        "global_staircase_magnitude_tracker": {name: 0 for name in all_method_names},
        "global_coverage_tracker": {name: 0 for name in all_method_names},
        "global_historical_gallagher_tracker": {name: 0.0 for name in all_method_names},
        "global_historical_weighted_gallagher_tracker": {name: 0.0 for name in all_method_names},
        "all_time_displacement_incidents": {name: [] for name in all_method_names},
        "yearly_displacement_incidents": {},
        "yearly_staircase_metrics": {},
        "country_excel_quotient_records": [],
        "country_milestone_summary_records": []
    }

    yearly_mc_logs: Dict[str, Any] = {}
    meta_logs = {
        "inversions": {name: [] for name in all_method_names if name != "Current District D'Hondt"},
        "dips": {name: [] for name in all_method_names},
        "pairs": {name: [] for name in all_method_names},
        "mag": {name: [] for name in all_method_names},
        "gallagher": {name: [] for name in all_method_names},
        "weighted_gallagher": {name: [] for name in all_method_names},
        "coverage": {name: [] for name in all_method_names},
        "quotient_efficiency": {
            m_name: {pct: [] for pct in QUOTIENT_MILESTONES} for m_name in pool_method_names
        }
    }

    meta_mc_total_simulations = 0
    run_metadata_log: List[str] = []
    master_csv_rows: List[List[Any]] = [
        ["==============================================================================="],
        ["                CENTRAL ELECTORAL SIMULATION RESULTS REPOSITORY"],
        ["==============================================================================="],
        ["Monte Carlo Engine Status", "ENABLED" if ENABLE_MONTE_CARLO else "DISABLED"],
        ["Danish DP Engine Status", "ENABLED" if ENABLE_DANISH_DP else "DISABLED"],
        ["Random Master Seed", str(RANDOM_SEED)],
        ["Target Iteration Runs Per Cycle", str(SIMULATIONS)],
        ["National Variation Swing Limit", f"±{NATIONAL_VARIATION}%"],
        ["Local District Variance Limit", f"±{LOCAL_VARIATION}%"],
        []
    ]

    # PHASE 1: DATA INTEGRITY AUDIT
    all_datasets, historical_election_count, global_max_possible_coverage = audit_datasets()

    # PHASE 2: CORE SIMULATION ENGINE
    sleep_preventer = keep.running() if (HAS_WAKEPY and ENABLE_MONTE_CARLO) else nullcontext()

    if HAS_WAKEPY and ENABLE_MONTE_CARLO:
        print("☕ Wakepy activated: Preventing system sleep during Monte Carlo simulation...\n")
    elif ENABLE_MONTE_CARLO:
        print("⚠️ Wakepy not installed: Running Monte Carlo without sleep inhibition. (Install with: pip install wakepy)\n")

    with sleep_preventer:
        for file_path, metadata_cache in all_datasets.items():
            country_name = metadata_cache["country_name"]
            elections_archive = metadata_cache["archive"]
            
            years_processed = sorted(elections_archive.keys())
            run_metadata_log.append(f"{country_name.upper()} ({', '.join(years_processed)})")

            trackers["country_excel_quotient_records"] = []
            trackers["country_milestone_summary_records"] = []
            country_all_years_plot_data: Dict[str, List[Dict[str, Any]]] = {}

            all_country_districts = []
            for yr, yr_data in elections_archive.items():
                for d_name in yr_data["district_caps"].keys():
                    if d_name not in all_country_districts:
                        all_country_districts.append(d_name)
            
            d2l_map, _ = generate_district_letter_mapping(all_country_districts)
            print_district_legend_console(country_name, d2l_map)

            for year, dataset in elections_archive.items():
                if ENABLE_MONTE_CARLO:
                    print(f" Processing Simulation Metrics: {country_name.upper()} ({year})... ")
                else:
                    print(f" Processing {country_name.upper()} ({year})... ")

                grid_data = run_historical_election(country_name, year, dataset, d2l_map, trackers)
                country_all_years_plot_data[year] = grid_data

                if ENABLE_MONTE_CARLO:
                    sim_count = run_monte_carlo_simulation(
                        country_name, year, dataset, d2l_map,
                        all_method_names, yearly_mc_logs, meta_logs
                    )
                    meta_mc_total_simulations += sim_count

            if not ENABLE_MONTE_CARLO and trackers["country_excel_quotient_records"]:
                export_quotient_analysis_excel(
                    country_name,
                    trackers["country_excel_quotient_records"],
                    trackers["country_milestone_summary_records"],
                    d2l_map
                )

    # PHASE 3: REPORTING & OUTPUT GENERATION
    render_final_reports(
        all_method_names, trackers, yearly_mc_logs, meta_logs,
        meta_mc_total_simulations, historical_election_count,
        global_max_possible_coverage, master_csv_rows,
        country_all_years_plot_data, country_name
    )

    elapsed_time = time.time() - global_start_time
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    time_str = f"{int(hours)}h {int(minutes)}m {seconds:.2f}s" if hours > 0 else f"{int(minutes)}m {seconds:.2f}s"

    print("\n" + "="*80)
    print(f" {GREEN}✓ MASTER DATA SUMMARY LEDGER REPORT GENERATED SUCCESSFULLY{RESET}")
    print(" All calculated matrix blocks compiled into unified archive: 'master_electoral_report.csv'")
    print(f" ⏱️  TOTAL EXECUTION TIME: {time_str}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()