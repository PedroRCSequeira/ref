import csv
import glob
import hashlib
import os
import random
import time
from contextlib import nullcontext
from typing import Any, Dict, List, Tuple

# Try importing wakepy to prevent laptop/system sleep during long Monte Carlo runs
try:
    from wakepy import keep
    HAS_WAKEPY = True
except ImportError:
    HAS_WAKEPY = False

# Import configuration constants
from config import (
    ENABLE_MONTE_CARLO,
    ENABLE_DANISH_DP,
    ENABLE_STAIRCASE_PLOTS,
    SIMULATIONS,
    NATIONAL_VARIATION,
    LOCAL_VARIATION,
    RANDOM_SEED,
    QUOTIENT_MILESTONES,
    SIM_BATCH_SIZE,
    SIM_COOLING_PAUSE,
    SUPPORTED_REGIONS,
    GREEN, RED, BLUE, YELLOW, RESET
)

# Import dataset parser utilities
from data_parser import (
    generate_district_letter_mapping,
    parse_stacked_country_file
)

# Import baseline/benchmark engines (IMMUTABLE)
from baseline_engines import (
    dhondt_apportion,
    get_national_party_caps,
    allocate_double_proportionality,
    allocate_double_proportionality_danish
)

# Import custom methods & registry (MUTABLE / EXTENSIBLE)
from custom_methods import (
    CUSTOM_METHODS_REGISTRY,
    compute_quotient_milestones
)

# Import pure electoral evaluation metrics
from electoral_metrics import (
    calculate_mean_district_gallagher,
    calculate_weighted_mean_district_gallagher,
    analyze_global_staircase_inversions
)

# Import visual, plot, and console reporting functions
from visuals_export import (
    print_district_legend_console,
    get_method_order_index,
    plot_staircase_sequence,
    plot_combined_year_comparison,
    plot_method_all_years_comparison,
    plot_monte_carlo_trends,
    print_quotient_efficiency_table,
    export_quotient_analysis_excel,
    print_top_displacement_examples,
    print_structured_table,
    render_scorecard_table
)


def analyze_inversions(
    votes_map: Dict[str, Dict[str, int]], 
    allocations_map: Dict[str, Dict[str, int]], 
    parties_lst: List[str]
) -> Tuple[Dict[str, Dict[str, str]], str, int, List[str]]:
    """
    Evaluates all intra-district inversion pairs without skipping previously marked parties.
    Tracks both positive (+) and negative (-) flags per party, allowing dual '+-' markings.
    """
    marks = {d: {p: "" for p in parties_lst} for d in votes_map.keys()}
    total_inversion_pairs = 0  
    affected_districts = set()
    detailed_logs = []

    for d in votes_map.keys():
        has_plus = {p: False for p in parties_lst}
        has_minus = {p: False for p in parties_lst}
        num_parties = len(parties_lst)

        for i in range(num_parties):
            pA = parties_lst[i]
            for j in range(i + 1, num_parties):
                pB = parties_lst[j]

                # Case 1: pA had more votes than pB but received fewer seats
                if votes_map[d][pA] > votes_map[d][pB] and allocations_map[d][pA] < allocations_map[d][pB]:
                    has_minus[pA] = True  # pA lost out
                    has_plus[pB] = True   # pB benefited
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pA} had more votes ({votes_map[d][pA]:,}) than {pB} ({votes_map[d][pB]:,}) but received fewer seats ({allocations_map[d][pA]} vs {allocations_map[d][pB]})."
                    )
                # Case 2: pB had more votes than pA but received fewer seats
                elif votes_map[d][pB] > votes_map[d][pA] and allocations_map[d][pB] < allocations_map[d][pA]:
                    has_minus[pB] = True  # pB lost out
                    has_plus[pA] = True   # pA benefited
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pB} had more votes ({votes_map[d][pB]:,}) than {pA} ({votes_map[d][pA]:,}) but received fewer seats ({allocations_map[d][pB]} vs {allocations_map[d][pA]})."
                    )

        # Build final mark tags based on accumulated flags
        for p in parties_lst:
            if has_plus[p] and has_minus[p]:
                marks[d][p] = "+-"
            elif has_plus[p]:
                marks[d][p] = "+"
            elif has_minus[p]:
                marks[d][p] = "-"
            else:
                marks[d][p] = ""

    analysis_str = f"Detected {total_inversion_pairs} intra-district inversion pair(s) across {len(affected_districts)} district(s)."
    return marks, analysis_str, total_inversion_pairs, detailed_logs


def main() -> None:
    global_start_time = time.time()  

    input_files = sorted(glob.glob("data_*.csv"))
    if not input_files:
        print(f"{RED}Error: No country datasets found matching pattern 'data_*.csv'.{RESET}")
        return

    active_custom_methods = [m for m in CUSTOM_METHODS_REGISTRY if m["enabled"]]

    all_method_names: List[str] = [
        "Current District D'Hondt", 
        "Zurich DP"
    ]
    if ENABLE_DANISH_DP:
        all_method_names.append("Danish DP")
    all_method_names.extend([m["name"] for m in active_custom_methods])

    global_inversion_tracker: Dict[str, int] = {name: 0 for name in all_method_names}
    global_staircase_dips_tracker: Dict[str, int] = {name: 0 for name in all_method_names}
    global_staircase_pairs_tracker: Dict[str, int] = {name: 0 for name in all_method_names}
    global_staircase_magnitude_tracker: Dict[str, int] = {name: 0 for name in all_method_names}

    all_time_displacement_incidents: Dict[str, List[Dict[str, Any]]] = {name: [] for name in all_method_names}
    yearly_displacement_incidents: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    yearly_staircase_metrics: Dict[str, Dict[str, Dict[str, Any]]] = {}

    global_coverage_tracker: Dict[str, int] = {name: 0 for name in all_method_names}
    global_historical_gallagher_tracker: Dict[str, float] = {name: 0.0 for name in all_method_names}
    global_historical_weighted_gallagher_tracker: Dict[str, float] = {name: 0.0 for name in all_method_names}

    global_max_possible_coverage = 0
    historical_election_count = 0

    yearly_mc_logs: Dict[str, Dict[str, Dict[str, List[Any]]]] = {}
    
    meta_mc_inversions_log: Dict[str, List[int]] = {name: [] for name in all_method_names if name != "Current District D'Hondt"}
    meta_mc_staircase_dips_log: Dict[str, List[int]] = {name: [] for name in all_method_names}
    meta_mc_staircase_pairs_log: Dict[str, List[int]] = {name: [] for name in all_method_names}
    meta_mc_staircase_magnitude_log: Dict[str, List[int]] = {name: [] for name in all_method_names}

    meta_mc_gallagher_log: Dict[str, List[float]] = {name: [] for name in all_method_names}
    meta_mc_weighted_gallagher_log: Dict[str, List[float]] = {name: [] for name in all_method_names}
    meta_mc_coverage_log: Dict[str, List[int]] = {name: [] for name in all_method_names}

    pool_method_names = [m["name"] for m in active_custom_methods]
    meta_mc_quotient_efficiency_log: Dict[str, Dict[int, List[int]]] = {
        m_name: {pct: [] for pct in QUOTIENT_MILESTONES} for m_name in pool_method_names
    }

    meta_mc_total_simulations = 0
    run_metadata_log: List[str] = []
    master_csv_rows: List[List[Any]] = []
    
    master_csv_rows.append(["==============================================================================="])
    master_csv_rows.append(["                CENTRAL ELECTORAL SIMULATION RESULTS REPOSITORY"])
    master_csv_rows.append(["==============================================================================="])
    master_csv_rows.append(["Monte Carlo Engine Status", "ENABLED" if ENABLE_MONTE_CARLO else "DISABLED"])
    master_csv_rows.append(["Danish DP Engine Status", "ENABLED" if ENABLE_DANISH_DP else "DISABLED"])
    master_csv_rows.append(["Random Master Seed", str(RANDOM_SEED)])
    master_csv_rows.append(["Target Iteration Runs Per Cycle", str(SIMULATIONS)])
    master_csv_rows.append(["National Variation Swing Limit", f"±{NATIONAL_VARIATION}%"])
    master_csv_rows.append(["Local District Variance Limit", f"±{LOCAL_VARIATION}%"])
    master_csv_rows.append([])

    # ------------------------------------------------------------------------------
    # PHASE 1: UPFRONT GLOBAL DATA INTEGRITY AUDITS
    # ------------------------------------------------------------------------------
    all_datasets = {}
    validation_errors = []

    print("🔍 Launching Upfront Dataset Integrity Audits...")

    for file_path in input_files:
        filename = os.path.basename(file_path)
        country_name = filename.replace("data_", "").replace(".csv", "").strip().title()
        
        if country_name.lower() not in SUPPORTED_REGIONS:
            print("\n" + "!" * 80)
            print(f"❌ {RED}PROTECTION STOP: UNSUPPORTED REGION DETECTED ('{country_name}'){RESET}")
            print("!" * 80 + "\n")
            raise ValueError(f"Aborted: Region '{country_name}' is missing configured system rules.")

        elections_archive = parse_stacked_country_file(file_path)
        all_datasets[file_path] = {
            "country_name": country_name,
            "filename": filename,
            "archive": elections_archive
        }
        
        for year, dataset in elections_archive.items():
            historical_election_count += 1
            votes = dataset["votes"]
            district_caps = dataset["district_caps"]
            total_votes_cast = dataset["total_votes_cast"]
            parties_list = dataset["parties_list"]
            has_total_column = dataset["has_total_column"]
            num_districts = len(votes)
            
            global_max_possible_coverage += (num_districts * len(parties_list))
            
            if has_total_column:
                for d in votes.keys():
                    sum_listed_parties = sum(votes[d].values())
                    if total_votes_cast[d] < sum_listed_parties:
                        validation_errors.append(
                            f"[{country_name.upper()} - {year}] District '{d}' total raw votes count ({total_votes_cast[d]:,}) is smaller than listed party subset sum ({sum_listed_parties:,})."
                        )
            
            total_mandates_sum = sum(district_caps.values())
            if country_name.lower() == "portugal" and total_mandates_sum != 226:
                validation_errors.append(
                    f"[{country_name.upper()} - {year}] Portugal context failure: Total structural seats equals {total_mandates_sum} instead of 226 bounds."
                )
                
            national_party_votes = {p: sum(votes[d][p] for d in votes.keys()) for p in parties_list}
            party_caps = get_national_party_caps(
                country_name, national_party_votes, total_mandates_sum, dataset.get("national_mandates")
            )
                
            if sum(party_caps.values()) != total_mandates_sum:
                validation_errors.append(
                    f"[{country_name.upper()} - {year}] National targets matching error: National party mandates sum to {sum(party_caps.values())} while structure bounds freeze at {total_mandates_sum}."
                )

    if validation_errors:
        print(f"\n{RED}❌ DATA VALIDATION FAILED — {len(validation_errors)} critical database issue(s) identified:{RESET}")
        for err in validation_errors:
            print(f"   - {err}")
        raise ValueError("Electoral pipeline execution aborted.")

    print(f"{GREEN}✅ All datasets passed upfront integrity passes. Proceeding to compilation pipeline.{RESET}\n")

    # ------------------------------------------------------------------------------
    # PHASE 2: CLEAN DATA ANALYSIS & PROBABILISTIC EXECUTION ENGINE (WITH WAKEPY)
    # ------------------------------------------------------------------------------
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

            country_excel_quotient_records: List[Dict[str, Any]] = []
            country_milestone_summary_records: List[Dict[str, Any]] = []

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

                votes = dataset["votes"]
                district_caps = dataset["district_caps"]
                parties_list = dataset["parties_list"]
                total_mandates_sum = sum(district_caps.values())

                yearly_staircase_metrics[year] = {m: {} for m in all_method_names}
                yearly_displacement_incidents[year] = {m: [] for m in all_method_names}
                
                year_methods_grid_data: List[Dict[str, Any]] = []

                current_results: Dict[str, Dict[str, int]] = {d_key: {} for d_key in votes.keys()}
                current_party_totals = {p: 0 for p in parties_list}
                for d in votes.keys():
                    allocated_district_seats = dhondt_apportion(votes[d], district_caps[d])
                    for p in parties_list:
                        current_results[d][p] = allocated_district_seats.get(p, 0)
                        current_party_totals[p] += allocated_district_seats.get(p, 0)

                national_party_votes = {p: sum(votes[d][p] for d in votes.keys()) for p in parties_list}
                party_caps = get_national_party_caps(
                    country_name, national_party_votes, total_mandates_sum, dataset.get("national_mandates")
                )

                # Core Allocations
                dp_results, dp_p_totals, district_weights, party_weights, dp_valid, dp_errors = allocate_double_proportionality(votes, party_caps, district_caps)
                
                if ENABLE_DANISH_DP:
                    danish_dp_results, danish_dp_p_totals, danish_district_weights, danish_party_weights, danish_valid, danish_errors = allocate_double_proportionality_danish(votes, party_caps, district_caps)
                else:
                    danish_dp_results, danish_dp_p_totals, danish_district_weights, danish_party_weights, danish_valid, danish_errors = {}, {}, {}, {}, True, []

                year_method_milestones: Dict[str, Dict[int, Dict[str, Any]]] = {}

                current_marks, _, current_inv, _ = analyze_inversions(votes, current_results, parties_list)
                dp_marks, _, dp_inv, _ = analyze_inversions(votes, dp_results, parties_list)

                # GLOBAL Staircase Engine Calculations
                curr_dips, curr_pairs, curr_mag, _, curr_incidents, curr_seq, curr_entries = analyze_global_staircase_inversions(votes, current_results, parties_list, d2l_map)
                yearly_staircase_metrics[year]["Current District D'Hondt"] = {"dips": curr_dips, "pairs": curr_pairs, "mag": curr_mag, "sequence": curr_seq}
                yearly_displacement_incidents[year]["Current District D'Hondt"].extend(curr_incidents)
                all_time_displacement_incidents["Current District D'Hondt"].extend(curr_incidents)
                year_methods_grid_data.append({"method_name": "Current District D'Hondt", "entries": curr_entries, "dips": curr_dips, "pairs": curr_pairs, "mag": curr_mag})

                dp_dips, dp_pairs, dp_mag, _, dp_incidents, dp_seq, dp_entries = analyze_global_staircase_inversions(votes, dp_results, parties_list, d2l_map)
                yearly_staircase_metrics[year]["Zurich DP"] = {"dips": dp_dips, "pairs": dp_pairs, "mag": dp_mag, "sequence": dp_seq}
                yearly_displacement_incidents[year]["Zurich DP"].extend(dp_incidents)
                all_time_displacement_incidents["Zurich DP"].extend(dp_incidents)
                year_methods_grid_data.append({"method_name": "Zurich DP", "entries": dp_entries, "dips": dp_dips, "pairs": dp_pairs, "mag": dp_mag})

                if ENABLE_DANISH_DP:
                    danish_dp_marks, _, danish_dp_inv, _ = analyze_inversions(votes, danish_dp_results, parties_list)
                    danish_dips, danish_pairs, danish_mag, _, danish_incidents, danish_seq, danish_entries = analyze_global_staircase_inversions(votes, danish_dp_results, parties_list, d2l_map)
                    yearly_staircase_metrics[year]["Danish DP"] = {"dips": danish_dips, "pairs": danish_pairs, "mag": danish_mag, "sequence": danish_seq}
                    yearly_displacement_incidents[year]["Danish DP"].extend(danish_incidents)
                    all_time_displacement_incidents["Danish DP"].extend(danish_incidents)
                    year_methods_grid_data.append({"method_name": "Danish DP", "entries": danish_entries, "dips": danish_dips, "pairs": danish_pairs, "mag": danish_mag})

                    global_historical_gallagher_tracker["Danish DP"] += calculate_mean_district_gallagher(votes, danish_dp_results, parties_list)
                    global_historical_weighted_gallagher_tracker["Danish DP"] += calculate_weighted_mean_district_gallagher(votes, danish_dp_results, parties_list, district_caps)
                    global_inversion_tracker["Danish DP"] += danish_dp_inv
                    global_staircase_dips_tracker["Danish DP"] += danish_dips
                    global_staircase_pairs_tracker["Danish DP"] += danish_pairs
                    global_staircase_magnitude_tracker["Danish DP"] += danish_mag
                    global_coverage_tracker["Danish DP"] += sum(1 for d in votes.keys() for p in parties_list if danish_dp_results[d][p] > 0)

                global_historical_gallagher_tracker["Current District D'Hondt"] += calculate_mean_district_gallagher(votes, current_results, parties_list)
                global_historical_gallagher_tracker["Zurich DP"] += calculate_mean_district_gallagher(votes, dp_results, parties_list)

                global_historical_weighted_gallagher_tracker["Current District D'Hondt"] += calculate_weighted_mean_district_gallagher(votes, current_results, parties_list, district_caps)
                global_historical_weighted_gallagher_tracker["Zurich DP"] += calculate_weighted_mean_district_gallagher(votes, dp_results, parties_list, district_caps)

                global_inversion_tracker["Current District D'Hondt"] += current_inv
                global_inversion_tracker["Zurich DP"] += dp_inv

                global_staircase_dips_tracker["Current District D'Hondt"] += curr_dips
                global_staircase_dips_tracker["Zurich DP"] += dp_dips

                global_staircase_pairs_tracker["Current District D'Hondt"] += curr_pairs
                global_staircase_pairs_tracker["Zurich DP"] += dp_pairs

                global_staircase_magnitude_tracker["Current District D'Hondt"] += curr_mag
                global_staircase_magnitude_tracker["Zurich DP"] += dp_mag

                global_coverage_tracker["Current District D'Hondt"] += sum(1 for d in votes.keys() for p in parties_list if current_results[d][p] > 0)
                global_coverage_tracker["Zurich DP"] += sum(1 for d in votes.keys() for p in parties_list if dp_results[d][p] > 0)

                extra_computed_methods = []
                
                # --- DYNAMIC CUSTOM METHOD LOOP ---
                for method_cfg in CUSTOM_METHODS_REGISTRY:
                    if not method_cfg.get("enabled", True): 
                        continue
                    if not ENABLE_MONTE_CARLO and not method_cfg.get("run_historical", True): 
                        continue

                    # Single dynamic call for ANY custom algorithm!
                    e_res, _, e_history = method_cfg["func"](votes, party_caps, district_caps, **method_cfg.get("kwargs", {}))
                    
                    e_milestones = compute_quotient_milestones(e_history, total_mandates_sum)
                    if method_cfg.get("show_console", True):
                        year_method_milestones[method_cfg["name"]] = e_milestones

                    if not ENABLE_MONTE_CARLO and method_cfg.get("show_excel", True):
                        for item in e_history:
                            country_excel_quotient_records.append({
                                "Year": year, "Method": method_cfg["name"], "Step": item["Step"], "District": item["District"],
                                "Party": item["Party"], "Quotient": item["Quotient"], "Divisor": item["Divisor"],
                                "Seat Attempt": item["Seat Attempt"], "Allocated": item["Allocated"], "Running Total": item["Running Total"]
                            })
                        country_milestone_summary_records.append({
                            "Year": year, "Method": method_cfg["name"], "Total Mandates": total_mandates_sum, "Milestones": e_milestones
                        })

                    e_marks, _, e_inv, _ = analyze_inversions(votes, e_res, parties_list)
                    e_dips, e_pairs, e_mag, _, e_incidents, e_seq, e_entries = analyze_global_staircase_inversions(votes, e_res, parties_list, d2l_map)
                    e_cov = sum(1 for d in votes.keys() for p in parties_list if e_res[d][p] > 0)
                    
                    m_name_str = str(method_cfg["name"])
                    yearly_staircase_metrics[year][m_name_str] = {"dips": e_dips, "pairs": e_pairs, "mag": e_mag, "sequence": e_seq}
                    yearly_displacement_incidents[year][m_name_str].extend(e_incidents)
                    all_time_displacement_incidents[m_name_str].extend(e_incidents)

                    global_historical_gallagher_tracker[m_name_str] += calculate_mean_district_gallagher(votes, e_res, parties_list)
                    global_historical_weighted_gallagher_tracker[m_name_str] += calculate_weighted_mean_district_gallagher(votes, e_res, parties_list, district_caps)
                    
                    global_inversion_tracker[m_name_str] += e_inv
                    global_staircase_dips_tracker[m_name_str] += e_dips
                    global_staircase_pairs_tracker[m_name_str] += e_pairs
                    global_staircase_magnitude_tracker[m_name_str] += e_mag
                    global_coverage_tracker[m_name_str] += e_cov
                    
                    year_methods_grid_data.append({"method_name": m_name_str, "entries": e_entries, "dips": e_dips, "pairs": e_pairs, "mag": e_mag})
                    extra_computed_methods.append({"config": method_cfg, "results": e_res, "marks": e_marks})

                year_methods_grid_data.sort(key=lambda x: get_method_order_index(x["method_name"]))
                country_all_years_plot_data[year] = year_methods_grid_data

                if not ENABLE_MONTE_CARLO:
                    party_vote_totals = {p: sum(votes[d][p] for d in votes.keys()) for p in parties_list}
                    
                    print_structured_table(f"({year}) 1. RAW BASE ELECTORAL VOTE DATA", votes, party_caps, party_vote_totals, district_caps, mode="votes")
                    print_structured_table(f"({year}) 2. CURRENT DISTRICT ELECTORAL SYSTEM (DISTRICT D'HONDT)", current_results, party_caps, current_party_totals, district_caps, mode="seats", marks=current_marks)
                    print_structured_table(f"({year}) 3. ZÜRICH DOUBLE PROPORTIONALITY GRID DISTRIBUTION", dp_results, party_caps, dp_p_totals, district_caps, mode="seats", marks=dp_marks, weights_r=district_weights, weights_c=party_weights, is_valid=dp_valid, errors=dp_errors)
                    
                    if ENABLE_DANISH_DP:
                        print_structured_table(f"({year}) 4. DANISH DOUBLE PROPORTIONALITY GRID DISTRIBUTION", danish_dp_results, party_caps, danish_dp_p_totals, district_caps, mode="seats", marks=danish_dp_marks, weights_r=danish_district_weights, weights_c=danish_party_weights, is_valid=danish_valid, errors=danish_errors)
                        diff_matrix = {d: {p: danish_dp_results[d][p] - dp_results[d][p] for p in parties_list} for d in votes.keys()}
                        diff_party_totals = {p: danish_dp_p_totals[p] - dp_p_totals[p] for p in parties_list}
                        zero_district_caps = {d: 0 for d in votes.keys()}
                        print_structured_table(f"({year}) 4b. COMPARISON DELTA SHEET: [DANISH DP] MINUS [ZURICH DP]", diff_matrix, party_caps, diff_party_totals, zero_district_caps, mode="diff", custom_row_totals=zero_district_caps)

                    for extra in extra_computed_methods:
                        if extra["config"].get("show_console", True):
                            extra_totals = {p: sum(extra["results"][d][p] for d in votes.keys()) for p in parties_list}
                            print_structured_table(f"({year}) METHOD: {extra['config']['name']}", extra["results"], party_caps, extra_totals, district_caps, mode="seats", marks=extra["marks"])

                    print_quotient_efficiency_table(f"QUOTIENT EFFICIENCY RADAR: {country_name.upper()} ({year})", year_method_milestones, total_mandates_sum)

                # --------------------------------------------------------------------------
                # MONTE CARLO LOOP
                # --------------------------------------------------------------------------
                if ENABLE_MONTE_CARLO:
                    seed_str = f"{country_name}_{year}_{RANDOM_SEED}"
                    hash_int = int(hashlib.sha256(seed_str.encode('utf-8')).hexdigest(), 16) % (2**32)
                    rng = random.Random(hash_int)

                    yearly_mc_logs[year] = {
                        "inversions": {m: [] for m in all_method_names if m != "Current District D'Hondt"},
                        "dips": {m: [] for m in all_method_names},
                        "pairs": {m: [] for m in all_method_names},
                        "mag": {m: [] for m in all_method_names},
                        "gallagher": {m: [] for m in all_method_names},
                        "weighted_gallagher": {m: [] for m in all_method_names},
                        "coverage": {m: [] for m in all_method_names}
                    }

                    valid_sim_count = 0
                    batch_count = 0

                    while valid_sim_count < SIMULATIONS:
                        sim_votes = {d: {} for d in votes.keys()}
                        national_swings = {p: rng.uniform(-NATIONAL_VARIATION / 100.0, NATIONAL_VARIATION / 100.0) for p in parties_list}

                        for d in votes.keys():
                            for p in parties_list:
                                base_v = votes[d][p]
                                local_var = rng.uniform(-LOCAL_VARIATION / 100.0, LOCAL_VARIATION / 100.0)
                                combined_factor = 1.0 + national_swings[p] + local_var
                                sim_votes[d][p] = max(0, int(round(base_v * combined_factor)))

                        if any(sum(sim_votes[d].values()) == 0 for d in sim_votes.keys()):
                            continue

                        sim_national_party_votes = {p: sum(sim_votes[d][p] for d in sim_votes.keys()) for p in parties_list}
                        sim_party_caps = get_national_party_caps(
                            country_name, sim_national_party_votes, total_mandates_sum, dataset.get("national_mandates")
                        )

                        if sum(sim_party_caps.values()) != total_mandates_sum:
                            continue

                        sim_curr_res = {d: {} for d in sim_votes.keys()}
                        for d in sim_votes.keys():
                            alloc = dhondt_apportion(sim_votes[d], district_caps[d])
                            for p in parties_list: sim_curr_res[d][p] = alloc.get(p, 0)

                        sim_dp_res, _, _, _, sim_dp_valid, _ = allocate_double_proportionality(sim_votes, sim_party_caps, district_caps)
                        if not sim_dp_valid:
                            continue

                        if ENABLE_DANISH_DP:
                            sim_danish_res, _, _, _, sim_danish_valid, _ = allocate_double_proportionality_danish(sim_votes, sim_party_caps, district_caps)
                            if not sim_danish_valid:
                                continue
                        else:
                            sim_danish_res = {}

                        # --- Intra-District Inversions ---
                        _, _, mc_dp_inv, _ = analyze_inversions(sim_votes, sim_dp_res, parties_list)
                        yearly_mc_logs[year]["inversions"]["Zurich DP"].append(mc_dp_inv)
                        meta_mc_inversions_log["Zurich DP"].append(mc_dp_inv)

                        if ENABLE_DANISH_DP:
                            _, _, mc_danish_inv, _ = analyze_inversions(sim_votes, sim_danish_res, parties_list)
                            yearly_mc_logs[year]["inversions"]["Danish DP"].append(mc_danish_inv)
                            meta_mc_inversions_log["Danish DP"].append(mc_danish_inv)

                        # --- GLOBAL Staircase Metrics ---
                        mc_curr_dips, mc_curr_pairs, mc_curr_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_curr_res, parties_list, d2l_map)
                        yearly_mc_logs[year]["dips"]["Current District D'Hondt"].append(mc_curr_dips)
                        yearly_mc_logs[year]["pairs"]["Current District D'Hondt"].append(mc_curr_pairs)
                        yearly_mc_logs[year]["mag"]["Current District D'Hondt"].append(mc_curr_mag)
                        meta_mc_staircase_dips_log["Current District D'Hondt"].append(mc_curr_dips)
                        meta_mc_staircase_pairs_log["Current District D'Hondt"].append(mc_curr_pairs)
                        meta_mc_staircase_magnitude_log["Current District D'Hondt"].append(mc_curr_mag)

                        mc_dp_dips, mc_dp_pairs, mc_dp_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_dp_res, parties_list, d2l_map)
                        yearly_mc_logs[year]["dips"]["Zurich DP"].append(mc_dp_dips)
                        yearly_mc_logs[year]["pairs"]["Zurich DP"].append(mc_dp_pairs)
                        yearly_mc_logs[year]["mag"]["Zurich DP"].append(mc_dp_mag)
                        meta_mc_staircase_dips_log["Zurich DP"].append(mc_dp_dips)
                        meta_mc_staircase_pairs_log["Zurich DP"].append(mc_dp_pairs)
                        meta_mc_staircase_magnitude_log["Zurich DP"].append(mc_dp_mag)

                        if ENABLE_DANISH_DP:
                            mc_danish_dips, mc_danish_pairs, mc_danish_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_danish_res, parties_list, d2l_map)
                            yearly_mc_logs[year]["dips"]["Danish DP"].append(mc_danish_dips)
                            yearly_mc_logs[year]["pairs"]["Danish DP"].append(mc_danish_pairs)
                            yearly_mc_logs[year]["mag"]["Danish DP"].append(mc_danish_mag)
                            meta_mc_staircase_dips_log["Danish DP"].append(mc_danish_dips)
                            meta_mc_staircase_pairs_log["Danish DP"].append(mc_danish_pairs)
                            meta_mc_staircase_magnitude_log["Danish DP"].append(mc_danish_mag)

                        # --- Proportionality & Coverage ---
                        g_curr = calculate_mean_district_gallagher(sim_votes, sim_curr_res, parties_list)
                        g_dp = calculate_mean_district_gallagher(sim_votes, sim_dp_res, parties_list)

                        wg_curr = calculate_weighted_mean_district_gallagher(sim_votes, sim_curr_res, parties_list, district_caps)
                        wg_dp = calculate_weighted_mean_district_gallagher(sim_votes, sim_dp_res, parties_list, district_caps)

                        yearly_mc_logs[year]["gallagher"]["Current District D'Hondt"].append(g_curr)
                        yearly_mc_logs[year]["gallagher"]["Zurich DP"].append(g_dp)

                        yearly_mc_logs[year]["weighted_gallagher"]["Current District D'Hondt"].append(wg_curr)
                        yearly_mc_logs[year]["weighted_gallagher"]["Zurich DP"].append(wg_dp)

                        meta_mc_gallagher_log["Current District D'Hondt"].append(g_curr)
                        meta_mc_gallagher_log["Zurich DP"].append(g_dp)

                        meta_mc_weighted_gallagher_log["Current District D'Hondt"].append(wg_curr)
                        meta_mc_weighted_gallagher_log["Zurich DP"].append(wg_dp)

                        if ENABLE_DANISH_DP:
                            g_danish = calculate_mean_district_gallagher(sim_votes, sim_danish_res, parties_list)
                            wg_danish = calculate_weighted_mean_district_gallagher(sim_votes, sim_danish_res, parties_list, district_caps)
                            yearly_mc_logs[year]["gallagher"]["Danish DP"].append(g_danish)
                            yearly_mc_logs[year]["weighted_gallagher"]["Danish DP"].append(wg_danish)
                            meta_mc_gallagher_log["Danish DP"].append(g_danish)
                            meta_mc_weighted_gallagher_log["Danish DP"].append(wg_danish)

                        cov_curr = sum(1 for d in sim_votes.keys() for p in parties_list if sim_curr_res[d][p] > 0)
                        cov_dp = sum(1 for d in sim_votes.keys() for p in parties_list if sim_dp_res[d][p] > 0)

                        yearly_mc_logs[year]["coverage"]["Current District D'Hondt"].append(cov_curr)
                        yearly_mc_logs[year]["coverage"]["Zurich DP"].append(cov_dp)

                        meta_mc_coverage_log["Current District D'Hondt"].append(cov_curr)
                        meta_mc_coverage_log["Zurich DP"].append(cov_dp)

                        if ENABLE_DANISH_DP:
                            cov_danish = sum(1 for d in sim_votes.keys() for p in parties_list if sim_danish_res[d][p] > 0)
                            yearly_mc_logs[year]["coverage"]["Danish DP"].append(cov_danish)
                            meta_mc_coverage_log["Danish DP"].append(cov_danish)

                        # --- DYNAMIC CUSTOM METHOD MONTE CARLO LOOP ---
                        for method_cfg in CUSTOM_METHODS_REGISTRY:
                            if not method_cfg.get("enabled", True): 
                                continue
                            if not method_cfg.get("run_monte_carlo", True): 
                                continue
                            
                            m_name_str = str(method_cfg["name"])
                            sim_e_res, _, sim_e_hist = method_cfg["func"](sim_votes, sim_party_caps, district_caps, **method_cfg.get("kwargs", {}))

                            sim_e_milestones = compute_quotient_milestones(sim_e_hist, total_mandates_sum)
                            for pct in QUOTIENT_MILESTONES:
                                meta_mc_quotient_efficiency_log[m_name_str][pct].append(
                                    sim_e_milestones.get(pct, {}).get("quotients_eval", 0)
                                )

                            _, _, mc_e_inv, _ = analyze_inversions(sim_votes, sim_e_res, parties_list)
                            mc_e_dips, mc_e_pairs, mc_e_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_e_res, parties_list, d2l_map)
                            g_e = calculate_mean_district_gallagher(sim_votes, sim_e_res, parties_list)
                            wg_e = calculate_weighted_mean_district_gallagher(sim_votes, sim_e_res, parties_list, district_caps)
                            cov_e = sum(1 for d in sim_votes.keys() for p in parties_list if sim_e_res[d][p] > 0)

                            if m_name_str not in yearly_mc_logs[year]["inversions"]:
                                yearly_mc_logs[year]["inversions"][m_name_str] = []
                                yearly_mc_logs[year]["dips"][m_name_str] = []
                                yearly_mc_logs[year]["pairs"][m_name_str] = []
                                yearly_mc_logs[year]["mag"][m_name_str] = []
                                yearly_mc_logs[year]["gallagher"][m_name_str] = []
                                yearly_mc_logs[year]["weighted_gallagher"][m_name_str] = []
                                yearly_mc_logs[year]["coverage"][m_name_str] = []

                            yearly_mc_logs[year]["inversions"][m_name_str].append(mc_e_inv)
                            yearly_mc_logs[year]["dips"][m_name_str].append(mc_e_dips)
                            yearly_mc_logs[year]["pairs"][m_name_str].append(mc_e_pairs)
                            yearly_mc_logs[year]["mag"][m_name_str].append(mc_e_mag)
                            yearly_mc_logs[year]["gallagher"][m_name_str].append(g_e)
                            yearly_mc_logs[year]["weighted_gallagher"][m_name_str].append(wg_e)
                            yearly_mc_logs[year]["coverage"][m_name_str].append(cov_e)

                            meta_mc_inversions_log[m_name_str].append(mc_e_inv)
                            meta_mc_staircase_dips_log[m_name_str].append(mc_e_dips)
                            meta_mc_staircase_pairs_log[m_name_str].append(mc_e_pairs)
                            meta_mc_staircase_magnitude_log[m_name_str].append(mc_e_mag)
                            meta_mc_gallagher_log[m_name_str].append(g_e)
                            meta_mc_weighted_gallagher_log[m_name_str].append(wg_e)
                            meta_mc_coverage_log[m_name_str].append(cov_e)

                        valid_sim_count += 1
                        meta_mc_total_simulations += 1

                        if valid_sim_count % SIM_BATCH_SIZE == 0:
                            batch_count += 1
                            time.sleep(SIM_COOLING_PAUSE)

            if not ENABLE_MONTE_CARLO and country_excel_quotient_records:
                export_quotient_analysis_excel(country_name, country_excel_quotient_records, country_milestone_summary_records, d2l_map)

            # --------------------------------------------------------------------------
            # UNIFIED REGIONAL PLOT GENERATION PIPELINE (HISTORICAL + MONTE CARLO TRENDS)
            # --------------------------------------------------------------------------
            if ENABLE_MONTE_CARLO and yearly_mc_logs:
                plot_monte_carlo_trends(country_name, yearly_mc_logs)

            if not ENABLE_MONTE_CARLO and ENABLE_STAIRCASE_PLOTS and country_all_years_plot_data:
                # 0. Compute Global Regional Scale across ALL years and ALL methods for this country
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

                # STEP 1: Yearly Composite Comparison Grids ({year}_COMPARE_ALL_METHODS.png)
                for yr in sorted(country_all_years_plot_data.keys()):
                    grid_methods = [m for m in country_all_years_plot_data[yr] if m["method_name"] != "Quadratic Pool Method"]
                    plot_combined_year_comparison(country_name, yr, grid_methods, country_bounds, country_y_max)

                # STEP 2: Multi-Year Method Comparison Grids (COMPARE_{method}_ALL_YEARS.png)
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

                # STEP 3: Individual Method Graphs ({year}_{order_idx}_{method}.png)
                for yr in sorted(country_all_years_plot_data.keys()):
                    for m_info in country_all_years_plot_data[yr]:
                        order_idx = get_method_order_index(m_info["method_name"])
                        plot_staircase_sequence(
                            country_name,
                            yr,
                            m_info["method_name"],
                            order_idx,
                            m_info["entries"],
                            m_info["dips"],
                            m_info["pairs"],
                            m_info["mag"],
                            x_bounds=country_bounds,
                            y_max=country_y_max
                        )

    # ==============================================================================
    # 6) GLOBAL COMPREHENSIVE SUMMARIES
    # ==============================================================================
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

        render_scorecard_table("1. OVERALL SYSTEM ACCURACY (FEWEST INTRA-DISTRICT INVERSIONS)", meta_mc_inversions_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("2. OVERALL STAIRCASE METHOD 1 (FEWEST GLOBAL LOCAL DIPS)", meta_mc_staircase_dips_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("3. OVERALL STAIRCASE METHOD 2 (FEWEST GLOBAL DOMINANCE PAIRS)", meta_mc_staircase_pairs_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("4. OVERALL STAIRCASE METHOD 3 (LOWEST GLOBAL DISPLACEMENT MAGNITUDE)", meta_mc_staircase_magnitude_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("5. OVERALL LOCAL PROPORTIONALITY (UNWEIGHTED DISTRICT GALLAGHER)", meta_mc_gallagher_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("6. OVERALL SEAT-WEIGHTED PROPORTIONALITY (LOWEST WEIGHTED GALLAGHER)", meta_mc_weighted_gallagher_log, meta_mc_total_simulations, precision_val=2, higher_is_better=False, csv_accumulator=master_csv_rows)
        render_scorecard_table("7. OVERALL GEOGRAPHIC FOOTPRINT SPREAD (HIGHEST ACTIVE CELLS)", meta_mc_coverage_log, meta_mc_total_simulations, precision_val=0, higher_is_better=True, csv_accumulator=master_csv_rows)

    else:
        print("\n" + "🏛️ " * 40)
        print(" METRIC RADAR CODES: HISTORICAL BASELINE RECORDS (RAW RUNS ONLY)")
        print("🏛️ " * 40)

        print("\n================================================================================")
        print(" 📅 YEAR-BY-YEAR GLOBAL STAIRCASE METRIC BREAKDOWN & TAGGED SEQUENCES")
        print("================================================================================")
        
        for year in sorted(yearly_staircase_metrics.keys()):
            print(f"\n" + "-"*90)
            print(f" 🗓️  ELECTION YEAR {year} DIAGNOSTIC RADAR")
            print("-" * 90)
            print(f"{'Electoral Allocation System':<38} | {'Global Dips':<12} | {'Dominance Pairs':<15} | {'Displacement Depth':<18}")
            print("-" * 90)
            
            for m_name in all_method_names:
                m_data = yearly_staircase_metrics[year].get(m_name, {})
                dips = m_data.get("dips", 0)
                pairs = m_data.get("pairs", 0)
                mag = m_data.get("mag", 0)
                print(f"{m_name:<38} | {dips:>12,} | {pairs:>15,} | {mag:>18,}")
            
            print(f"\n   --- Tagged Mandate Sequences (Least Votes to Most Votes: DistrictKeyMandates) ---")
            for m_name in all_method_names:
                seq = yearly_staircase_metrics[year].get(m_name, {}).get("sequence", "")
                print(f"   📌 Method: {m_name}")
                print(f"      {seq}")

            print(f"\n   --- Top 5 Displacement Depth Penalties for Year {year} ---")
            for m_name in all_method_names:
                m_incidents = yearly_displacement_incidents[year].get(m_name, [])
                print_top_displacement_examples(m_incidents, f"Method: {m_name} ({year})", top_n=5)

        master_csv_rows.append(["==============================================================================="])
        master_csv_rows.append(["🏛️  HISTORICAL ARCHIVE PERFORMANCE HIGHLIGHT SUMMARY (RAW ENGINE ALLOCATIONS)"])
        master_csv_rows.append(["==============================================================================="])

        accuracy_rankings = sorted(all_method_names, key=lambda core_name: global_inversion_tracker[core_name])
        print("\n================================================================================")
        print(" 秤  HISTORICAL ARCHIVE RANKINGS BY ACCURACY (FEWEST INTRA-DISTRICT INVERSIONS)")
        print("================================================================================")
        for idx, name in enumerate(accuracy_rankings, 1):
            inv_count = global_inversion_tracker[name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(accuracy_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {inv_count:,} total intra-district inversion anomalies")

        dips_rankings = sorted(all_method_names, key=lambda core_name: global_staircase_dips_tracker[core_name])
        print("\n================================================================================")
        print(" 🪜 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 1 (FEWEST GLOBAL LOCAL DIPS)")
        print("================================================================================")
        for idx, name in enumerate(dips_rankings, 1):
            dips_count = global_staircase_dips_tracker[name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(dips_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {dips_count:,} total step dips in sorted array")

        pairs_rankings = sorted(all_method_names, key=lambda core_name: global_staircase_pairs_tracker[core_name])
        print("\n================================================================================")
        print(" 📈 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 2 (FEWEST GLOBAL DOMINANCE PAIRS)")
        print("================================================================================")
        for idx, name in enumerate(pairs_rankings, 1):
            pairs_count = global_staircase_pairs_tracker[name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(pairs_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {pairs_count:,} total dominance pairs")

        mag_rankings = sorted(all_method_names, key=lambda core_name: global_staircase_magnitude_tracker[core_name])
        print("\n================================================================================")
        print(" 💥 HISTORICAL ARCHIVE RANKINGS BY STAIRCASE METHOD 3 (LOWEST GLOBAL DISPLACEMENT MAGNITUDE)")
        print("================================================================================")
        for idx, name in enumerate(mag_rankings, 1):
            mag_val = global_staircase_magnitude_tracker[name]
            color_modifier = GREEN if idx == 1 else (RED if idx == len(mag_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {mag_val:,} total seats displacement depth penalty")

        print("\n================================================================================")
        print(" 🏆 ALL-TIME AGGREGATE TOP 5 DISPLACEMENT DEPTH PENALTIES BY METHOD")
        print("================================================================================")
        for m_name in all_method_names:
            print_top_displacement_examples(all_time_displacement_incidents[m_name], f"All-Time Method: {m_name}", top_n=5)

        gallagher_rankings = sorted(all_method_names, key=lambda core_name: global_historical_gallagher_tracker[core_name])
        print("\n================================================================================")
        print(" 📊 HISTORICAL ARCHIVE RANKINGS BY LOCAL PROPORTIONALITY (UNWEIGHTED DISTRICT GALLAGHER)")
        print("================================================================================")
        for idx, name in enumerate(gallagher_rankings, 1):
            avg_g = global_historical_gallagher_tracker[name] / max(1, historical_election_count)
            color_modifier = GREEN if idx == 1 else (RED if idx == len(gallagher_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {avg_g:.2f} average historical district Gallagher score")

        weighted_gallagher_rankings = sorted(all_method_names, key=lambda core_name: global_historical_weighted_gallagher_tracker[core_name])
        print("\n================================================================================")
        print(" 📊 HISTORICAL ARCHIVE RANKINGS BY SEAT-WEIGHTED PROPORTIONALITY (LOWEST WEIGHTED GALLAGHER)")
        print("================================================================================")
        for idx, name in enumerate(weighted_gallagher_rankings, 1):
            avg_wg = global_historical_weighted_gallagher_tracker[name] / max(1, historical_election_count)
            color_modifier = GREEN if idx == 1 else (RED if idx == len(weighted_gallagher_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {avg_wg:.2f} average historical seat-weighted district Gallagher score")

        footprint_rankings = sorted(all_method_names, key=lambda core_name: global_coverage_tracker[core_name], reverse=True)
        print("\n================================================================================")
        print(" 🗺️  HISTORICAL ARCHIVE RANKINGS BY GEOGRAPHIC FOOTPRINT (MAX SPREAD DIVERSITY)")
        print("================================================================================")
        for idx, name in enumerate(footprint_rankings, 1):
            cov_count = global_coverage_tracker[name]
            cov_pct = (cov_count / global_max_possible_coverage) * 100
            color_modifier = BLUE if idx == 1 else (YELLOW if idx == len(footprint_rankings) else RESET)
            print(f"  {idx:<2}. {color_modifier}{name:<40}{RESET} : {cov_count:,} / {global_max_possible_coverage:,} active distribution cells ({cov_pct:.2f}%)")

    master_report_path = "master_electoral_report.csv"
    with open(master_report_path, "w", newline="", encoding="utf-8-sig") as master_f:
        report_writer = csv.writer(master_f)
        report_writer.writerows(master_csv_rows)

    elapsed_time = time.time() - global_start_time
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    time_str = f"{int(hours)}h {int(minutes)}m {seconds:.2f}s" if hours > 0 else f"{int(minutes)}m {seconds:.2f}s"

    print("\n" + "="*80)
    print(f" {GREEN}✓ MASTER DATA SUMMARY LEDGER REPORT GENERATED SUCCESSFULLY{RESET}")
    print(f" All calculated matrix blocks compiled into unified archive: '{master_report_path}'")
    print(f" ⏱️  TOTAL EXECUTION TIME: {time_str}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()