from tuning_engine import run_tuning

MIN_CAP = 1
MAX_CAP = 15

if __name__ == "__main__":
    run_tuning(
        target_method_name="2-Speed",
        tuning_parameters={
            "round1_district_cap": ("int", MIN_CAP, MAX_CAP),
        },
        tuning_goals={
            "unweighted_gallagher": ("min", 1),
            "weighted_gallagher":   ("min", 1),
            "inversions":           ("min", 1),
            "dips":                 ("min", 0),
            "pairs":                ("min", 0),
            "magnitude":            ("min", 0),
        },
        sims_per_trial=30,
        max_time_minutes=10,
        cooling_pause_per_trial=1.5,
        use_grid_search=True,   # Evaluated from MIN_CAP to MAX_CAP
        show_all_trials=True    # Displays full clean summary table
    )