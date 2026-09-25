from typing import Any, Dict, List, Tuple

from baseline_engines import (
    allocate_double_proportionality,
    allocate_double_proportionality_danish,
    dhondt_apportion,
    get_national_party_caps,
)
from config import ENABLE_DANISH_DP, ENABLE_MONTE_CARLO
from custom_methods import CUSTOM_METHODS_REGISTRY, compute_quotient_milestones
from electoral_metrics import (
    analyze_global_staircase_inversions,
    calculate_mean_district_gallagher,
    calculate_weighted_mean_district_gallagher,
)
from visuals_export import (
    get_method_order_index,
    print_quotient_efficiency_table,
    print_structured_table,
)


def analyze_inversions(
    votes_map: Dict[str, Dict[str, int]], 
    allocations_map: Dict[str, Dict[str, int]], 
    parties_lst: List[str]
) -> Tuple[Dict[str, Dict[str, str]], str, int, List[str]]:
    """Evaluates intra-district inversion pairs."""
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

                if votes_map[d][pA] > votes_map[d][pB] and allocations_map[d][pA] < allocations_map[d][pB]:
                    has_minus[pA] = True
                    has_plus[pB] = True
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pA} had more votes ({votes_map[d][pA]:,}) than {pB} ({votes_map[d][pB]:,}) but received fewer seats ({allocations_map[d][pA]} vs {allocations_map[d][pB]})."
                    )
                elif votes_map[d][pB] > votes_map[d][pA] and allocations_map[d][pB] < allocations_map[d][pA]:
                    has_minus[pB] = True
                    has_plus[pA] = True
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pB} had more votes ({votes_map[d][pB]:,}) than {pA} ({votes_map[d][pA]:,}) but received fewer seats ({allocations_map[d][pB]} vs {allocations_map[d][pA]})."
                    )

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


def run_historical_election(
    country_name: str,
    year: str,
    dataset: Dict[str, Any],
    d2l_map: Dict[str, str],
    trackers: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Runs allocation algorithms for a single historical election year."""
    votes = dataset["votes"]
    district_caps = dataset["district_caps"]
    parties_list = dataset["parties_list"]
    total_mandates_sum = sum(district_caps.values())

    trackers["yearly_staircase_metrics"][year] = {m: {} for m in trackers["all_method_names"]}
    trackers["yearly_displacement_incidents"][year] = {m: [] for m in trackers["all_method_names"]}
    
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

    dp_results, dp_p_totals, district_weights, party_weights, dp_valid, dp_errors = allocate_double_proportionality(votes, party_caps, district_caps)
    
    if ENABLE_DANISH_DP:
        danish_dp_results, danish_dp_p_totals, danish_district_weights, danish_party_weights, danish_valid, danish_errors = allocate_double_proportionality_danish(votes, party_caps, district_caps)
    else:
        danish_dp_results, danish_dp_p_totals, danish_district_weights, danish_party_weights, danish_valid, danish_errors = {}, {}, {}, {}, True, []

    year_method_milestones: Dict[str, Dict[int, Dict[str, Any]]] = {}

    current_marks, _, current_inv, _ = analyze_inversions(votes, current_results, parties_list)
    dp_marks, _, dp_inv, _ = analyze_inversions(votes, dp_results, parties_list)

    curr_dips, curr_pairs, curr_mag, _, curr_incidents, curr_seq, curr_entries = analyze_global_staircase_inversions(votes, current_results, parties_list, d2l_map)
    trackers["yearly_staircase_metrics"][year]["Current District D'Hondt"] = {"dips": curr_dips, "pairs": curr_pairs, "mag": curr_mag, "sequence": curr_seq}
    trackers["yearly_displacement_incidents"][year]["Current District D'Hondt"].extend(curr_incidents)
    trackers["all_time_displacement_incidents"]["Current District D'Hondt"].extend(curr_incidents)
    year_methods_grid_data.append({"method_name": "Current District D'Hondt", "entries": curr_entries, "dips": curr_dips, "pairs": curr_pairs, "mag": curr_mag})

    dp_dips, dp_pairs, dp_mag, _, dp_incidents, dp_seq, dp_entries = analyze_global_staircase_inversions(votes, dp_results, parties_list, d2l_map)
    trackers["yearly_staircase_metrics"][year]["Zurich DP"] = {"dips": dp_dips, "pairs": dp_pairs, "mag": dp_mag, "sequence": dp_seq}
    trackers["yearly_displacement_incidents"][year]["Zurich DP"].extend(dp_incidents)
    trackers["all_time_displacement_incidents"]["Zurich DP"].extend(dp_incidents)
    year_methods_grid_data.append({"method_name": "Zurich DP", "entries": dp_entries, "dips": dp_dips, "pairs": dp_pairs, "mag": dp_mag})

    if ENABLE_DANISH_DP:
        danish_dp_marks, _, danish_dp_inv, _ = analyze_inversions(votes, danish_dp_results, parties_list)
        danish_dips, danish_pairs, danish_mag, _, danish_incidents, danish_seq, danish_entries = analyze_global_staircase_inversions(votes, danish_dp_results, parties_list, d2l_map)
        trackers["yearly_staircase_metrics"][year]["Danish DP"] = {"dips": danish_dips, "pairs": danish_pairs, "mag": danish_mag, "sequence": danish_seq}
        trackers["yearly_displacement_incidents"][year]["Danish DP"].extend(danish_incidents)
        trackers["all_time_displacement_incidents"]["Danish DP"].extend(danish_incidents)
        year_methods_grid_data.append({"method_name": "Danish DP", "entries": danish_entries, "dips": danish_dips, "pairs": danish_pairs, "mag": danish_mag})

        trackers["global_historical_gallagher_tracker"]["Danish DP"] += calculate_mean_district_gallagher(votes, danish_dp_results, parties_list)
        trackers["global_historical_weighted_gallagher_tracker"]["Danish DP"] += calculate_weighted_mean_district_gallagher(votes, danish_dp_results, parties_list, district_caps)
        trackers["global_inversion_tracker"]["Danish DP"] += danish_dp_inv
        trackers["global_staircase_dips_tracker"]["Danish DP"] += danish_dips
        trackers["global_staircase_pairs_tracker"]["Danish DP"] += danish_pairs
        trackers["global_staircase_magnitude_tracker"]["Danish DP"] += danish_mag
        trackers["global_coverage_tracker"]["Danish DP"] += sum(1 for d in votes.keys() for p in parties_list if danish_dp_results[d][p] > 0)

    trackers["global_historical_gallagher_tracker"]["Current District D'Hondt"] += calculate_mean_district_gallagher(votes, current_results, parties_list)
    trackers["global_historical_gallagher_tracker"]["Zurich DP"] += calculate_mean_district_gallagher(votes, dp_results, parties_list)

    trackers["global_historical_weighted_gallagher_tracker"]["Current District D'Hondt"] += calculate_weighted_mean_district_gallagher(votes, current_results, parties_list, district_caps)
    trackers["global_historical_weighted_gallagher_tracker"]["Zurich DP"] += calculate_weighted_mean_district_gallagher(votes, dp_results, parties_list, district_caps)

    trackers["global_inversion_tracker"]["Current District D'Hondt"] += current_inv
    trackers["global_inversion_tracker"]["Zurich DP"] += dp_inv

    trackers["global_staircase_dips_tracker"]["Current District D'Hondt"] += curr_dips
    trackers["global_staircase_dips_tracker"]["Zurich DP"] += dp_dips

    trackers["global_staircase_pairs_tracker"]["Current District D'Hondt"] += curr_pairs
    trackers["global_staircase_pairs_tracker"]["Zurich DP"] += dp_pairs

    trackers["global_staircase_magnitude_tracker"]["Current District D'Hondt"] += curr_mag
    trackers["global_staircase_magnitude_tracker"]["Zurich DP"] += dp_mag

    trackers["global_coverage_tracker"]["Current District D'Hondt"] += sum(1 for d in votes.keys() for p in parties_list if current_results[d][p] > 0)
    trackers["global_coverage_tracker"]["Zurich DP"] += sum(1 for d in votes.keys() for p in parties_list if dp_results[d][p] > 0)

    extra_computed_methods = []
    
    for method_cfg in CUSTOM_METHODS_REGISTRY:
        if not method_cfg.get("enabled", True): 
            continue
        if not ENABLE_MONTE_CARLO and not method_cfg.get("run_historical", True): 
            continue

        e_res, _, e_history = method_cfg["func"](votes, party_caps, district_caps, **method_cfg.get("kwargs", {}))
        
        e_milestones = compute_quotient_milestones(e_history, total_mandates_sum)
        if method_cfg.get("show_console", True):
            year_method_milestones[method_cfg["name"]] = e_milestones

        if not ENABLE_MONTE_CARLO and method_cfg.get("show_excel", True):
            for item in e_history:
                trackers["country_excel_quotient_records"].append({
                    "Year": year, "Method": method_cfg["name"], "Step": item["Step"], "District": item["District"],
                    "Party": item["Party"], "Quotient": item["Quotient"], "Divisor": item["Divisor"],
                    "Seat Attempt": item["Seat Attempt"], "Allocated": item["Allocated"], "Running Total": item["Running Total"]
                })
            trackers["country_milestone_summary_records"].append({
                "Year": year, "Method": method_cfg["name"], "Total Mandates": total_mandates_sum, "Milestones": e_milestones
            })

        e_marks, _, e_inv, _ = analyze_inversions(votes, e_res, parties_list)
        e_dips, e_pairs, e_mag, _, e_incidents, e_seq, e_entries = analyze_global_staircase_inversions(votes, e_res, parties_list, d2l_map)
        e_cov = sum(1 for d in votes.keys() for p in parties_list if e_res[d][p] > 0)
        
        m_name_str = str(method_cfg["name"])
        trackers["yearly_staircase_metrics"][year][m_name_str] = {"dips": e_dips, "pairs": e_pairs, "mag": e_mag, "sequence": e_seq}
        trackers["yearly_displacement_incidents"][year][m_name_str].extend(e_incidents)
        trackers["all_time_displacement_incidents"][m_name_str].extend(e_incidents)

        trackers["global_historical_gallagher_tracker"][m_name_str] += calculate_mean_district_gallagher(votes, e_res, parties_list)
        trackers["global_historical_weighted_gallagher_tracker"][m_name_str] += calculate_weighted_mean_district_gallagher(votes, e_res, parties_list, district_caps)
        
        trackers["global_inversion_tracker"][m_name_str] += e_inv
        trackers["global_staircase_dips_tracker"][m_name_str] += e_dips
        trackers["global_staircase_pairs_tracker"][m_name_str] += e_pairs
        trackers["global_staircase_magnitude_tracker"][m_name_str] += e_mag
        trackers["global_coverage_tracker"][m_name_str] += e_cov
        
        year_methods_grid_data.append({"method_name": m_name_str, "entries": e_entries, "dips": e_dips, "pairs": e_pairs, "mag": e_mag})
        extra_computed_methods.append({"config": method_cfg, "results": e_res, "marks": e_marks})

    year_methods_grid_data.sort(key=lambda x: get_method_order_index(x["method_name"]))

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

    return year_methods_grid_data