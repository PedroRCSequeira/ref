from tuning_engine import run_tuning

if __name__ == "__main__":
    run_tuning(
        target_method_name="Non-Formula Progressive",
        tuning_parameters={
            "phase1_start": ("int", 1, 2),
            "phase1_step":  ("int", 3, 5),
            "phase1_count": ("int", 4, 6),
            "phase2_gap":   ("int", 2, 4),
            "phase2_step":  ("int", 4, 6),
            "phase2_count": ("int", 3, 5),
            "phase3_gap":   ("int", 18, 30),
            "phase3_step":  ("int", 4, 8),
        },
        tuning_goals={
            "unweighted_gallagher": ("min", 0),
            "weighted_gallagher":   ("min", 1),
            "inversions":           ("min", 1),
            "dips":                 ("min", 0),
            "pairs":                ("min", 0),
            "magnitude":            ("min", 0),
        },
        sims_per_trial=10,
        max_time_minutes=30,
        cooling_pause_per_trial=0.5,
        use_grid_search=False,
        show_all_trials=False,
        pareto_only=True,  # Silence trial logs and output only Pareto bests
    )