import glob
import hashlib
import random
import time
from contextlib import nullcontext
from typing import Any, Dict, List, Optional, Tuple
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

# ==============================================================================
# 🎛️ USER TUNING CONFIGURATION CONTROL PANEL
# ==============================================================================

# 1. Target Algorithm to Tune
# (MUST match an exact "name" string inside CUSTOM_METHODS_REGISTRY in custom_methods.py)
TARGET_METHOD_NAME = "Non-Formula Progressive"

# 2. Parameters to Tune: "parameter_name": ("type", min_val, max_val)
# (Keys MUST match the exact function parameter / kwargs names accepted by the method in custom_methods.py)
# Supported types: "int" or "float"
TUNING_PARAMETERS: Dict[str, Tuple[str, Any, Any]] = {
    # Phase 1 Parameters (Initial fast seat acquisition)
    "phase1_start": ("int", 1, 5),
    "phase1_step":  ("int", 1, 5),
    "phase1_count": ("int", 1, 5),
    
    # Phase 2 Parameters (Mid-tier brake phases)
    "phase2_start": ("int", 6, 15),
    "phase2_step":  ("int", 4, 10),
    "phase2_count": ("int", 4, 10),
    
    # Phase 3 Parameters (Late-game heavy dampening)
    "phase3_start": ("int", 30, 70),
    "phase3_step":  ("int", 8, 20),
}

# 3. Optimization Goals Toggle (True/1 = Enabled, False/0 = Disabled)
# (Keys MUST match one of the supported metric names listed below)
# All enabled goals will be MINIMIZED simultaneously in multi-objective mode.
TUNING_GOALS = {
    "unweighted_gallagher": True,
    "weighted_gallagher":   True,
    "inversions":           True,
    "dips":                 False,
    "pairs":                False,
    "magnitude":            False,
}

# 4. Engine Execution Limits
SIMS_PER_TRIAL = 200                 # Monte Carlo runs per election year per trial
MAX_TRIALS: Optional[int] = None     # None = Time-bounded run (unlimited trial count)
MAX_TIME_MINUTES: Optional[int] = 30 # Time limit in minutes (e.g., 30, 60), or None for trial-bounded
COOLING_PAUSE_PER_TRIAL = 1.5        # Pause duration (seconds) between trials for CPU cooling

# ==============================================================================
# 🛠️ DYNAMIC TUNING ENGINE (DO NOT EDIT BELOW THIS LINE)
# ==============================================================================

ENABLED_GOAL_KEYS = [g for g, enabled in TUNING_GOALS.items() if enabled]
if not ENABLED_GOAL_KEYS:
    raise ValueError("At least one optimization goal in TUNING_GOALS must be set to True/1.")


class TuningMonitorCallback:
    """Optuna callback to manage thermal cooling and log real-time parameter leaders."""

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

        if study.is_multi_objective():
            pareto_count = len(study.best_trials)
            leader = min(study.best_trials, key=lambda t: t.values[0]) if study.best_trials else None
            if leader:
                params_str = ", ".join(f"{k}={v}" for k, v in leader.params.items())
                best_info = f"Pareto Frontiers: {pareto_count} | Lead Candidate [{params_str}] (Metric #1: {leader.values[0]:.4f})"
            else:
                best_info = f"Pareto Frontiers: {pareto_count}"
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


def get_target_function():
    """Finds the function corresponding to TARGET_METHOD_NAME in the registry."""
    for method in CUSTOM_METHODS_REGISTRY:
        if method["name"].lower() == TARGET_METHOD_NAME.lower():
            return method["func"]
    registered_names = [m["name"] for m in CUSTOM_METHODS_REGISTRY]
    raise ValueError(f"Method '{TARGET_METHOD_NAME}' not found in CUSTOM_METHODS_REGISTRY. Available: {registered_names}")


def objective(trial):
    # 1. Dynamically suggest candidate parameter values from TUNING_PARAMETERS config
    suggested_kwargs = {}
    for param_name, (param_type, min_v, max_v) in TUNING_PARAMETERS.items():
        if param_type == "int":
            suggested_kwargs[param_name] = trial.suggest_int(param_name, min_v, max_v)
        elif param_type == "float":
            suggested_kwargs[param_name] = trial.suggest_float(param_name, min_v, max_v)
        else:
            raise ValueError(f"Unsupported parameter type '{param_type}' for {param_name}. Use 'int' or 'float'.")

    target_func = get_target_function()

    data_files = sorted(glob.glob("data_*.csv"))
    if not data_files:
        raise FileNotFoundError("No 'data_*.csv' files found in workspace.")

    accumulators = {goal: 0.0 for goal in ENABLED_GOAL_KEYS}
    eval_count = 0

    for file_path in data_files:
        country_name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace("data_", "").replace(".csv", "").strip().title()
        archive = parse_stacked_country_file(file_path)

        # Generate district mapping if staircase metrics are toggled on
        if any(g in ENABLED_GOAL_KEYS for g in ["dips", "pairs", "magnitude"]):
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
            while valid_sims < SIMS_PER_TRIAL:
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

                # 2. Execute target method dynamically passing suggested kwargs
                allocations, _, _ = target_func(sim_votes, sim_party_caps, district_caps, **suggested_kwargs)

                # 3. Calculate only the metrics toggled ON in TUNING_GOALS
                if TUNING_GOALS["unweighted_gallagher"]:
                    accumulators["unweighted_gallagher"] += calculate_mean_district_gallagher(sim_votes, allocations, parties)

                if TUNING_GOALS["weighted_gallagher"]:
                    accumulators["weighted_gallagher"] += calculate_weighted_mean_district_gallagher(sim_votes, allocations, parties, district_caps)

                if TUNING_GOALS["inversions"]:
                    _, _, inv_count, _ = analyze_inversions(sim_votes, allocations, parties)
                    accumulators["inversions"] += inv_count

                if any(TUNING_GOALS[g] for g in ["dips", "pairs", "magnitude"]):
                    dips, pairs, mag, _, _, _, _ = analyze_global_staircase_inversions(sim_votes, allocations, parties, d2l_map)
                    if TUNING_GOALS["dips"]: accumulators["dips"] += dips
                    if TUNING_GOALS["pairs"]: accumulators["pairs"] += pairs
                    if TUNING_GOALS["magnitude"]: accumulators["magnitude"] += mag

                eval_count += 1
                valid_sims += 1

    # Return averaged enabled metrics tuple back to Optuna
    return tuple(accumulators[goal] / max(1, eval_count) for goal in ENABLED_GOAL_KEYS)


if __name__ == "__main__":
    print("=" * 80)
    print(f"🎯 DYNAMIC TUNING ENGINE — TARGET: [{TARGET_METHOD_NAME.upper()}]")
    print("=" * 80)
    print(f" • Tuning Parameters ({len(TUNING_PARAMETERS)} total): {list(TUNING_PARAMETERS.keys())}")
    print(f" • Enabled Goals:           {ENABLED_GOAL_KEYS}")
    print(f" • Monte Carlo Sims/Trial:  {SIMS_PER_TRIAL}")
    print(f" • Max Time Limit:          {MAX_TIME_MINUTES} minutes" if MAX_TIME_MINUTES else " • Max Time Limit:          Disabled")
    print(f" • Thermal Cooling Pause:   {COOLING_PAUSE_PER_TRIAL}s")
    print(f" • System Sleep Prevention: {'ENABLED (wakepy)' if HAS_WAKEPY else 'DISABLED'}")
    print("=" * 80 + "\n")

    timeout_sec = (MAX_TIME_MINUTES * 60) if MAX_TIME_MINUTES else None
    monitor = TuningMonitorCallback(target_trials=MAX_TRIALS, timeout_seconds=timeout_sec, cooling_pause=COOLING_PAUSE_PER_TRIAL)
    sleep_preventer = keep.running() if HAS_WAKEPY else nullcontext()

    with sleep_preventer:
        study = optuna.create_study(directions=["minimize"] * len(ENABLED_GOAL_KEYS))
        study.optimize(objective, n_trials=MAX_TRIALS, timeout=timeout_sec, callbacks=[monitor])

    print("\n" + "=" * 80)
    print("🏆 PARAMETER OPTIMIZATION COMPLETE (RESULTS SUMMARY)")
    print("=" * 80)

    # Format Output Header Dynamically to support 8 parameters cleanly
    param_headers = " | ".join(f"{p:<13}" for p in TUNING_PARAMETERS.keys())
    goal_headers = " | ".join(f"{g:<18}" for g in ENABLED_GOAL_KEYS)
    print(f"{'Trial #':<8} | {param_headers} | {goal_headers}")
    print("-" * (12 + 16 * len(TUNING_PARAMETERS) + 21 * len(ENABLED_GOAL_KEYS)))

    for trial in sorted(study.best_trials, key=lambda t: t.values[0]):
        p_vals = " | ".join(f"{str(trial.params.get(p, 'N/A')):<13}" for p in TUNING_PARAMETERS.keys())
        g_vals = " | ".join(f"{val:<18.4f}" for val in trial.values)
        print(f"{trial.number:<8} | {p_vals} | {g_vals}")
    print("=" * 80 + "\n")