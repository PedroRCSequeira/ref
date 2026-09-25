import hashlib
import random
import time
from typing import Any, Dict, List

from baseline_engines import (
    allocate_double_proportionality,
    allocate_double_proportionality_danish,
    dhondt_apportion,
    get_national_party_caps,
)
from config import (
    ENABLE_DANISH_DP,
    LOCAL_VARIATION,
    NATIONAL_VARIATION,
    QUOTIENT_MILESTONES,
    RANDOM_SEED,
    SIM_BATCH_SIZE,
    SIM_COOLING_PAUSE,
    SIMULATIONS,
)
from custom_methods import CUSTOM_METHODS_REGISTRY, compute_quotient_milestones
from electoral_metrics import (
    analyze_global_staircase_inversions,
    calculate_mean_district_gallagher,
    calculate_weighted_mean_district_gallagher,
)
from runner import analyze_inversions


def run_monte_carlo_simulation(
    country_name: str,
    year: str,
    dataset: Dict[str, Any],
    d2l_map: Dict[str, str],
    all_method_names: List[str],
    yearly_mc_logs: Dict[str, Any],
    meta_logs: Dict[str, Any]
) -> int:
    """Runs stochastic Monte Carlo iteration loop for a given election year."""
    votes = dataset["votes"]
    district_caps = dataset["district_caps"]
    parties_list = dataset["parties_list"]
    total_mandates_sum = sum(district_caps.values())

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
        meta_logs["inversions"]["Zurich DP"].append(mc_dp_inv)

        if ENABLE_DANISH_DP:
            _, _, mc_danish_inv, _ = analyze_inversions(sim_votes, sim_danish_res, parties_list)
            yearly_mc_logs[year]["inversions"]["Danish DP"].append(mc_danish_inv)
            meta_logs["inversions"]["Danish DP"].append(mc_danish_inv)

        # --- GLOBAL Staircase Metrics ---
        mc_curr_dips, mc_curr_pairs, mc_curr_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_curr_res, parties_list, d2l_map)
        yearly_mc_logs[year]["dips"]["Current District D'Hondt"].append(mc_curr_dips)
        yearly_mc_logs[year]["pairs"]["Current District D'Hondt"].append(mc_curr_pairs)
        yearly_mc_logs[year]["mag"]["Current District D'Hondt"].append(mc_curr_mag)
        meta_logs["dips"]["Current District D'Hondt"].append(mc_curr_dips)
        meta_logs["pairs"]["Current District D'Hondt"].append(mc_curr_pairs)
        meta_logs["mag"]["Current District D'Hondt"].append(mc_curr_mag)

        mc_dp_dips, mc_dp_pairs, mc_dp_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_dp_res, parties_list, d2l_map)
        yearly_mc_logs[year]["dips"]["Zurich DP"].append(mc_dp_dips)
        yearly_mc_logs[year]["pairs"]["Zurich DP"].append(mc_dp_pairs)
        yearly_mc_logs[year]["mag"]["Zurich DP"].append(mc_dp_mag)
        meta_logs["dips"]["Zurich DP"].append(mc_dp_dips)
        meta_logs["pairs"]["Zurich DP"].append(mc_dp_pairs)
        meta_logs["mag"]["Zurich DP"].append(mc_dp_mag)

        if ENABLE_DANISH_DP:
            mc_danish_dips, mc_danish_pairs, mc_danish_mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, sim_danish_res, parties_list, d2l_map)
            yearly_mc_logs[year]["dips"]["Danish DP"].append(mc_danish_dips)
            yearly_mc_logs[year]["pairs"]["Danish DP"].append(mc_danish_pairs)
            yearly_mc_logs[year]["mag"]["Danish DP"].append(mc_danish_mag)
            meta_logs["dips"]["Danish DP"].append(mc_danish_dips)
            meta_logs["pairs"]["Danish DP"].append(mc_danish_pairs)
            meta_logs["mag"]["Danish DP"].append(mc_danish_mag)

        # --- Proportionality & Coverage ---
        g_curr = calculate_mean_district_gallagher(sim_votes, sim_curr_res, parties_list)
        g_dp = calculate_mean_district_gallagher(sim_votes, sim_dp_res, parties_list)

        wg_curr = calculate_weighted_mean_district_gallagher(sim_votes, sim_curr_res, parties_list, district_caps)
        wg_dp = calculate_weighted_mean_district_gallagher(sim_votes, sim_dp_res, parties_list, district_caps)

        yearly_mc_logs[year]["gallagher"]["Current District D'Hondt"].append(g_curr)
        yearly_mc_logs[year]["gallagher"]["Zurich DP"].append(g_dp)

        yearly_mc_logs[year]["weighted_gallagher"]["Current District D'Hondt"].append(wg_curr)
        yearly_mc_logs[year]["weighted_gallagher"]["Zurich DP"].append(wg_dp)

        meta_logs["gallagher"]["Current District D'Hondt"].append(g_curr)
        meta_logs["gallagher"]["Zurich DP"].append(g_dp)

        meta_logs["weighted_gallagher"]["Current District D'Hondt"].append(wg_curr)
        meta_logs["weighted_gallagher"]["Zurich DP"].append(wg_dp)

        if ENABLE_DANISH_DP:
            g_danish = calculate_mean_district_gallagher(sim_votes, sim_danish_res, parties_list)
            wg_danish = calculate_weighted_mean_district_gallagher(sim_votes, sim_danish_res, parties_list, district_caps)
            yearly_mc_logs[year]["gallagher"]["Danish DP"].append(g_danish)
            yearly_mc_logs[year]["weighted_gallagher"]["Danish DP"].append(wg_danish)
            meta_logs["gallagher"]["Danish DP"].append(g_danish)
            meta_logs["weighted_gallagher"]["Danish DP"].append(wg_danish)

        cov_curr = sum(1 for d in sim_votes.keys() for p in parties_list if sim_curr_res[d][p] > 0)
        cov_dp = sum(1 for d in sim_votes.keys() for p in parties_list if sim_dp_res[d][p] > 0)

        yearly_mc_logs[year]["coverage"]["Current District D'Hondt"].append(cov_curr)
        yearly_mc_logs[year]["coverage"]["Zurich DP"].append(cov_dp)

        meta_logs["coverage"]["Current District D'Hondt"].append(cov_curr)
        meta_logs["coverage"]["Zurich DP"].append(cov_dp)

        if ENABLE_DANISH_DP:
            cov_danish = sum(1 for d in sim_votes.keys() for p in parties_list if sim_danish_res[d][p] > 0)
            yearly_mc_logs[year]["coverage"]["Danish DP"].append(cov_danish)
            meta_logs["coverage"]["Danish DP"].append(cov_danish)

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
                meta_logs["quotient_efficiency"][m_name_str][pct].append(
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

            meta_logs["inversions"][m_name_str].append(mc_e_inv)
            meta_logs["dips"][m_name_str].append(mc_e_dips)
            meta_logs["pairs"][m_name_str].append(mc_e_pairs)
            meta_logs["mag"][m_name_str].append(mc_e_mag)
            meta_logs["gallagher"][m_name_str].append(g_e)
            meta_logs["weighted_gallagher"][m_name_str].append(wg_e)
            meta_logs["coverage"][m_name_str].append(cov_e)

        valid_sim_count += 1

        if valid_sim_count % SIM_BATCH_SIZE == 0:
            batch_count += 1
            time.sleep(SIM_COOLING_PAUSE)

    return valid_sim_count