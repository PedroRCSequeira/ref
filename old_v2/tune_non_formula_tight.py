from tuning_engine import run_tuning

if __name__ == "__main__":
    run_tuning(
        target_method_name="Non-Formula Progressive",
        tuning_parameters={
            "phase1_start": ("int", 1, 1),     # Locked to 1
            "phase1_step":  ("int", 3, 3),     # Locked to 3 (Danish default start step)
            "phase1_count": ("int", 3, 7),     # Explores 3 to 7 initial seats
            "phase2_gap":   ("int", 3, 6),     # Relative gap to start Phase 2
            "phase2_step":  ("int", 4, 6),     # Divisor step for Phase 2
            "phase2_count": ("int", 2, 7),     # Explores 2 to 7 intermediate seats
            "phase3_gap":   ("int", 7, 25),    # High-resolution window for Phase 3 jump
            "phase3_step":  ("int", 7, 10),    # Divisor step for tail phase
        },
        tuning_goals={
            "unweighted_gallagher": ("min", 0),
            "weighted_gallagher":   ("min", 1),
            "inversions":           ("min", 1),
            "dips":                 ("min", 0),
            "pairs":                ("min", 0),
            "magnitude":            ("min", 0),
        },

        sims_per_trial=50,            # 50 Monte Carlo simulations per trial to reduce noise
        max_time_minutes=60,          # Hard safety limit (stops execution at 60 minutes)
        cooling_pause_per_trial=0.5,  # Delay in seconds between trials to manage CPU load
        
        # ----------------------------------------------------------------------
        # SEARCH STRATEGY & DISPLAY SWITCHES
        # ----------------------------------------------------------------------
        
        # use_grid_search:
        #   False = Smart/Adaptive Search (intelligently samples the 27,360 space)
        #   True  = Exhaustive Grid Search (evaluates combinations sequentially 1-by-1)
        use_grid_search=False,

        # show_all_trials:
        #   False = Quiet Mode (only logs new breakthrough Pareto winners in console)
        #   True  = Verbose Mode (prints a log line for every single evaluated trial)
        show_all_trials=False,

        # pareto_only:
        #   True  = Filters final summaries/reports to non-dominated optimal setups
        #   False = Keeps all evaluated trials in final output tables
        pareto_only=True,
    )