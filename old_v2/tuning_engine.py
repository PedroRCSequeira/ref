import glob
import hashlib
import os
import random
import time
from contextlib import nullcontext
from typing import Any, Dict, List, Optional, Tuple, Union
import optuna

# Try importing wakepy to prevent system sleep during long tuning runs
try:
    from wakepy import keep
    HAS_WAKEPY = True
except ImportError:
    HAS_WAKEPY = False

from config import LOCAL_VARIATION, NATIONAL_VARIATION, RANDOM_SEED
from data_parser import generate_district_letter_mapping, parse_stacked_country_file
from baseline_engines import get_national_party_caps
from custom_methods import CUSTOM_METHODS_REGISTRY
from electoral_metrics import (
    analyze_global_staircase_inversions,
    calculate_mean_district_gallagher,
    calculate_weighted_mean_district_gallagher,
)
from runner import analyze_inversions

# Suppress verbose default Optuna per-trial console output
optuna.logging.set_verbosity(optuna.logging.WARNING)


class TuningMonitorCallback:
    """Optuna callback to manage thermal cooling and log real-time progress."""

    def __init__(self, target_trials: Optional[int], timeout_seconds: Optional[int], cooling_pause: float):
        self.target_trials = target_trials
        self.timeout_seconds = timeout_seconds
        self.cooling_pause = cooling_pause
        self.start_time = time.time()
        self.next_milestone_pct = 10

    def __call__(self, study: optuna.Study, trial: optuna.trial.FrozenTrial):
        n_done = len(study.trials)
        elapsed_seconds = time.time() - self.start_time
        elapsed_minutes = elapsed_seconds / 60.0

        pareto_count = len(study.best_trials)
        is_multi = len(study.directions) > 1

        if is_multi:
            m1_direction = study.directions[0]
            if m1_direction == optuna.study.StudyDirection.MAXIMIZE:
                leader = max(study.best_trials, key=lambda t: t.values[0]) if study.best_trials else None
            else:
                leader = min(study.best_trials, key=lambda t: t.values[0]) if study.best_trials else None

            if leader:
                params_str = ", ".join(f"{k}={v}" for k, v in leader.params.items())
                best_info = f"Pareto Winners: {pareto_count} | Lead Candidate [{params_str}] (Metric #1: {leader.values[0]:.4f})"
            else:
                best_info = f"Pareto Winners: {pareto_count}"
        else:
            if study.best_value is not None:
                params_str = ", ".join(f"{k}={v}" for k, v in study.best_params.items())
                best_info = f"Best Score: {study.best_value:.4f} [{params_str}]"
            else:
                best_info = "Best Score: N/A"

        if self.target_trials and self.target_trials > 0:
            pct = (n_done / self.target_trials) * 100
            if pct >= self.next_milestone_pct:
                milestone_tag = int(self.next_milestone_pct)
                print(f"📊 {milestone_tag}% done ({n_done}/{self.target_trials} runs, {elapsed_minutes:.1f} min) | {best_info}")
                while self.next_milestone_pct <= pct:
                    self.next_milestone_pct += 10
        elif self.timeout_seconds and self.timeout_seconds > 0:
            pct = (elapsed_seconds / self.timeout_seconds) * 100
            if pct >= self.next_milestone_pct:
                milestone_tag = int(self.next_milestone_pct)
                tot_mins = self.timeout_seconds / 60.0
                print(f"⏱️ {milestone_tag}% time elapsed ({n_done} runs, {elapsed_minutes:.1f}/{tot_mins:.1f} min) | {best_info}")
                while self.next_milestone_pct <= pct:
                    self.next_milestone_pct += 10

        if self.cooling_pause > 0:
            time.sleep(self.cooling_pause)


def get_target_function(target_method_name: str):
    """Finds the function corresponding to target_method_name in the registry."""
    for method in CUSTOM_METHODS_REGISTRY:
        if method["name"].lower() == target_method_name.lower():
            return method["func"]
    registered_names = [m["name"] for m in CUSTOM_METHODS_REGISTRY]
    raise ValueError(f"Method '{target_method_name}' not found in CUSTOM_METHODS_REGISTRY. Available: {registered_names}")


def run_tuning(
    target_method_name: str,
    tuning_parameters: Dict[str, Tuple[str, Any, Any]],
    tuning_goals: Dict[str, Union[Tuple[str, int], bool, str]],
    sims_per_trial: int = 200,
    max_trials: Optional[int] = None,
    max_time_minutes: Optional[int] = 30,
    cooling_pause_per_trial: float = 1.5,
    use_grid_search: bool = False,
    show_all_trials: bool = False,
    pareto_only: bool = False,
):
    # Calculate total discrete parameter space combinations
    total_possible_combos = 1
    for param_name, (param_type, min_v, max_v) in tuning_parameters.items():
        if param_type == "int":
            total_possible_combos *= (int(max_v) - int(min_v) + 1)

    # Parse goals and their directions ("min" / "max")
    enabled_goals_info: List[Tuple[str, str]] = []
    for goal, setting in tuning_goals.items():
        if isinstance(setting, (tuple, list)) and len(setting) == 2:
            direction_raw, is_enabled = setting
            if bool(is_enabled):
                d_clean = "maximize" if str(direction_raw).lower() in ["max", "maximize"] else "minimize"
                enabled_goals_info.append((goal, d_clean))
        elif setting is True or (isinstance(setting, str) and setting.lower() in ["min", "minimize"]):
            enabled_goals_info.append((goal, "minimize"))
        elif isinstance(setting, str) and setting.lower() in ["max", "maximize"]:
            enabled_goals_info.append((goal, "maximize"))

    if not enabled_goals_info:
        raise ValueError("At least one optimization goal in tuning_goals must be enabled.")

    enabled_goal_keys = [g for g, _ in enabled_goals_info]
    directions_list = [d for _, d in enabled_goals_info]
    target_func = get_target_function(target_method_name)

    # Configure Sampler Strategy
    if use_grid_search:
        search_space = {}
        for param_name, (param_type, min_v, max_v) in tuning_parameters.items():
            if param_type == "int":
                search_space[param_name] = list(range(int(min_v), int(max_v) + 1))
            else:
                raise ValueError(f"Grid Search requires integer parameters. Got '{param_type}' for {param_name}.")
        sampler = optuna.samplers.GridSampler(search_space)
        actual_max_trials = max_trials if max_trials is not None else total_possible_combos
        engine_mode = f"GRID SEARCH ({total_possible_combos:,} total combinations)"
    else:
        sampler = optuna.samplers.TPESampler() if len(enabled_goal_keys) == 1 else None
        actual_max_trials = max_trials
        engine_mode = f"SMART BAYESIAN SAMPLING ({total_possible_combos:,} total space)"

    def objective(trial):
        suggested_kwargs = {}
        for param_name, (param_type, min_v, max_v) in tuning_parameters.items():
            if param_type == "int":
                suggested_kwargs[param_name] = trial.suggest_int(param_name, min_v, max_v)
            elif param_type == "float":
                suggested_kwargs[param_name] = trial.suggest_float(param_name, min_v, max_v)

        # ----------------------------------------------------------------------
        # DUPLICATE SKIPPING & AUTOMATIC EARLY STOPPING LOGIC
        # ----------------------------------------------------------------------
        completed_trials = [t for t in trial.study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        past_param_sets = {tuple(sorted(t.params.items())) for t in completed_trials}
        current_param_tuple = tuple(sorted(suggested_kwargs.items()))

        # If 100% of combinations are already tested, stop the study immediately
        if len(past_param_sets) >= total_possible_combos:
            trial.study.stop()
            raise optuna.exceptions.TrialPruned("Search space 100% exhausted.")

        # Skip duplicate suggestions instantly (0ms cost)
        if current_param_tuple in past_param_sets:
            raise optuna.exceptions.TrialPruned("Duplicate combination skipped.")

        # If this run completes the final missing combination, stop right after
        if len(past_param_sets) + 1 >= total_possible_combos:
            trial.study.stop()
        # ----------------------------------------------------------------------

        data_files = sorted(glob.glob("data_*.csv"))
        if not data_files:
            raise FileNotFoundError("No 'data_*.csv' files found in workspace.")

        accumulators = {goal: 0.0 for goal in enabled_goal_keys}
        eval_count = 0

        for file_path in data_files:
            country_name = os.path.basename(file_path).replace("data_", "").replace(".csv", "").strip().title()
            archive = parse_stacked_country_file(file_path)

            if any(g in enabled_goal_keys for g in ["dips", "pairs", "magnitude"]):
                all_districts = list(next(iter(archive.values()))["district_caps"].keys())
                d2l_map, _ = generate_district_letter_mapping(all_districts)
            else:
                d2l_map = {}

            for year, dataset in archive.items():
                votes = dataset["votes"]
                district_caps = dataset["district_caps"]
                parties = dataset["parties_list"]
                total_mandates = sum(district_caps.values())

                seed_str = f"{country_name}_{year}_{RANDOM_SEED}"
                hash_int = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest(), 16) % (2**32)
                rng = random.Random(hash_int)

                valid_sims = 0
                while valid_sims < sims_per_trial:
                    sim_votes = {d: {} for d in votes.keys()}
                    national_swings = {p: rng.uniform(-NATIONAL_VARIATION / 100.0, NATIONAL_VARIATION / 100.0) for p in parties}

                    for d in votes.keys():
                        for p in parties:
                            base_v = votes[d][p]
                            local_var = rng.uniform(-LOCAL_VARIATION / 100.0, LOCAL_VARIATION / 100.0)
                            combined_factor = 1.0 + national_swings[p] + local_var
                            sim_votes[d][p] = max(0, int(round(base_v * combined_factor)))

                    if any(sum(sim_votes[d].values()) == 0 for d in sim_votes.keys()):
                        continue

                    sim_nat_votes = {p: sum(sim_votes[d][p] for d in sim_votes.keys()) for p in parties}
                    sim_party_caps = get_national_party_caps(country_name, sim_nat_votes, total_mandates, dataset.get("national_mandates"))

                    if sum(sim_party_caps.values()) != total_mandates:
                        continue

                    allocations, _, _ = target_func(sim_votes, sim_party_caps, district_caps, **suggested_kwargs)

                    if "unweighted_gallagher" in enabled_goal_keys:
                        accumulators["unweighted_gallagher"] += calculate_mean_district_gallagher(sim_votes, allocations, parties)

                    if "weighted_gallagher" in enabled_goal_keys:
                        accumulators["weighted_gallagher"] += calculate_weighted_mean_district_gallagher(sim_votes, allocations, parties, district_caps)

                    if "inversions" in enabled_goal_keys:
                        _, _, inv_count, _ = analyze_inversions(sim_votes, allocations, parties)
                        accumulators["inversions"] += inv_count

                    if any(g in enabled_goal_keys for g in ["dips", "pairs", "magnitude"]):
                        dips, pairs, mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, allocations, parties, d2l_map)
                        if "dips" in enabled_goal_keys: accumulators["dips"] += dips
                        if "pairs" in enabled_goal_keys: accumulators["pairs"] += pairs
                        if "magnitude" in enabled_goal_keys: accumulators["magnitude"] += mag

                    eval_count += 1
                    valid_sims += 1

        return tuple(accumulators[goal] / max(1, eval_count) for goal in enabled_goal_keys)

    goals_display = [f"{g} ({d[:3]})" for g, d in enabled_goals_info]

    print("=" * 80)
    print(f"🎯 TUNING ENGINE — TARGET: [{target_method_name.upper()}]")
    print("=" * 80)
    print(f" • Search Strategy:         {engine_mode}")
    print(f" • Tuning Parameters:       {list(tuning_parameters.keys())}")
    print(f" • Enabled Goals:           {goals_display}")
    print(f" • Monte Carlo Sims/Trial:  {sims_per_trial}")
    print(f" • Max Time Limit:          {max_time_minutes} minutes" if max_time_minutes else " • Max Time Limit:          Disabled")
    print(f" • Thermal Cooling Pause:   {cooling_pause_per_trial}s")
    print(f" • System Sleep Prevention: {'ENABLED (wakepy)' if HAS_WAKEPY else 'DISABLED'}")
    print(f" • Pareto-Only Output:      {'ENABLED' if pareto_only else 'DISABLED'}")
    print("=" * 80 + "\n")

    timeout_sec = (max_time_minutes * 60) if max_time_minutes else None
    monitor = TuningMonitorCallback(target_trials=actual_max_trials, timeout_seconds=timeout_sec, cooling_pause=cooling_pause_per_trial)
    sleep_preventer = keep.running() if HAS_WAKEPY else nullcontext()

    with sleep_preventer:
        study = optuna.create_study(sampler=sampler, directions=directions_list)
        study.optimize(objective, n_trials=actual_max_trials, timeout=timeout_sec, callbacks=[monitor])

    # Run Diagnostics
    completed_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    unique_param_sets = len({tuple(sorted(t.params.items())) for t in completed_trials})
    pruned_trials = len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED])
    elapsed_sec = time.time() - monitor.start_time

    if unique_param_sets >= total_possible_combos:
        stop_reason = "✅ Exhausted 100% of parameter space (Stopped Early)"
    elif timeout_sec and elapsed_sec >= (timeout_sec - 2):
        stop_reason = f"⏱️ Hit Time Limit ({max_time_minutes} minutes reached)"
    else:
        stop_reason = "Completed"

    print("\n" + "=" * 80)
    print("📊 RUN DIAGNOSTICS & COVERAGE REPORT")
    print("=" * 80)
    print(f" • Termination Reason:     {stop_reason}")
    print(f" • Unique Combos Evaluated: {unique_param_sets:,} / {total_possible_combos:,} ({(unique_param_sets/total_possible_combos)*100:.2f}% coverage)")
    print(f" • Duplicate Skips (0ms):   {pruned_trials}")
    print("=" * 80)

    # ANSI Escape Codes for Terminal Highlighting
    C_RESET       = "\033[0m"
    BG_PARETO     = "\033[42m\033[1;30m"      # Vibrant Green Background + Bold Black Text
    BG_BEST       = "\033[48;5;208m\033[1;30m" # Vibrant Orange Background + Bold Black Text
    BG_ZEBRA_EVEN = "\033[48;5;234m"          # Subtle Dark Gray Row Background
    BG_ZEBRA_ODD  = "\033[48;5;237m"          # Slightly Lighter Gray Row Background

    print("\n" + "=" * 80)
    print("🏆 OPTIMIZATION COMPLETE (" + ("PARETO-ONLY " if pareto_only else "") + "RESULTS SUMMARY)")
    print("=" * 80)
    print("Legend:")
    print(f" • {BG_PARETO} Green Background {C_RESET}   = Parameter combination is Pareto-Optimal (not dominated by any other value)")
    print(f" • {BG_BEST} Orange Background {C_RESET} = Absolute best score achieved across all tested combinations (100%)")
    print("=" * 80 + "\n")

    p_headers_raw = [f"{p:<19}" for p in tuning_parameters.keys()]
    g_headers_raw = [f"{g:<25}" for g in enabled_goal_keys]

    header_str = " | ".join(p_headers_raw) + " | " + " | ".join(g_headers_raw)
    divider_str = "-" * len(header_str)

    print(header_str)
    print(divider_str)

    pareto_trial_numbers = {t.number for t in study.best_trials}
    trials_to_show = study.best_trials if pareto_only else (study.trials if show_all_trials else study.best_trials)
    valid_trials = [t for t in trials_to_show if t.values is not None]

    best_per_metric = {}
    for i, (goal, direction) in enumerate(enabled_goals_info):
        vals = [t.values[i] for t in study.trials if t.values is not None]
        best_per_metric[goal] = max(vals) if direction == "maximize" else min(vals)

    first_param_name = list(tuning_parameters.keys())[0]
    sorted_trials = sorted(valid_trials, key=lambda t: t.params.get(first_param_name, 0))

    for row_idx, trial in enumerate(sorted_trials):
        is_pareto = trial.number in pareto_trial_numbers
        row_bg = BG_ZEBRA_ODD if (row_idx % 2 == 1) else BG_ZEBRA_EVEN

        p_cells = []
        for p in tuning_parameters.keys():
            raw_p = f"{str(trial.params.get(p, 'N/A')):<19}"
            if is_pareto:
                p_cells.append(f"{BG_PARETO}{raw_p}{C_RESET}")
            else:
                p_cells.append(f"{row_bg}{raw_p}{C_RESET}")
        p_vals = " | ".join(p_cells)

        g_cells = []
        for i, (goal, _) in enumerate(enabled_goals_info):
            val = trial.values[i]
            best_val = best_per_metric[goal]

            if abs(best_val) > 1e-9:
                pct = int(round((val / best_val) * 100))
            else:
                pct = 100

            combined_str = f"{val:.4f} ({pct}%)"
            raw_g = f"{combined_str:<25}"
            
            if abs(val - best_val) < 1e-6:
                g_cells.append(f"{BG_BEST}{raw_g}{C_RESET}")
            else:
                g_cells.append(f"{row_bg}{raw_g}{C_RESET}")
            
        g_vals = " | ".join(g_cells)

        print(f"{p_vals} | {g_vals}")

    print(divider_str + "\n")