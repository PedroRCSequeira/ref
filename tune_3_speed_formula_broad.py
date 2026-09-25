from tuning_engine import run_tuning

if __name__ == "__main__":
    run_tuning(
        target_method_name="Non-Formula Progressive",
        tuning_parameters={
            # Anchor at 1
            "phase1_start": ("int", 1, 1),       # Fixed initial anchor at 1
            
            # VARIABLE PHASE 1 STEP:
            # Allows initial steps of 3 (Danish), 4, 5, or 6 to suppress inversions natively
            "phase1_step":  ("int", 3, 6),       
            
            # CONSTRAINED PHASE 1 COUNT:
            # Enforces at least 2 seats in Phase 1 to prevent collapsing/bypassing Phase 1
            "phase1_count": ("int", 1, 6),       
            
            # PHASE 2 ACCELERATION:
            "phase2_step":  ("int", 4, 8),       # Mid-game acceleration step
            "phase2_count": ("int", 1, 5),       # Seats spent in Phase 2
            
            # PHASE 3 TAIL DAMPENING:
            "phase3_step":  ("int", 6, 14),      # Final dampening step
        },
        tuning_goals={
            # MULTI-OBJECTIVE SEARCH:
            "weighted_gallagher": ("min", 1),
            "inversions":         ("min", 1),
            
            # Additional metrics (disabled):
            "unweighted_gallagher": ("min", 0),
            "dips":                 ("min", 0),
            "pairs":                ("min", 0),
            "magnitude":            ("min", 0),
        },
        sims_per_trial=50,             # Monte Carlo runs per trial
        max_trials=200,                # Sample up to 200 trials via TPE
        max_time_minutes=30,           # 30-minute safety limit
        cooling_pause_per_trial=0.2,   # 0.2s CPU delay
        use_grid_search=False,         # Smart Bayesian TPE sampling
        show_all_trials=False,         # Quiet console streaming
        pareto_only=True,              # Prints Pareto-optimal candidate set
        aggregation_mode="mean",       # Standard average across all dataset years
        show_per_year_breakdown=True,  # Per-dataset breakdown for top candidates
    )