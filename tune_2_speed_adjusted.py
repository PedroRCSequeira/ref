from tuning_engine import run_tuning

# ------------------------------------------------------------------------------
# Tuning ranges for the 2-speed-adjusted method
# ------------------------------------------------------------------------------
# Cap ranges  (as requested: 1-3 / 2-4 / 4-5)
MIN_SMALL_CAP  = 1
MAX_SMALL_CAP  = 3

MIN_MEDIUM_CAP = 2
MAX_MEDIUM_CAP = 4

MIN_LARGE_CAP  = 4
MAX_LARGE_CAP  = 5

# Size-threshold ranges
MIN_SMALL_THRESHOLD = 4      # 1st threshold tunes between 7 and 20
MAX_SMALL_THRESHOLD = 10

MIN_LARGE_THRESHOLD = 11     # 2nd threshold: 21 up to 25
MAX_LARGE_THRESHOLD = 20


if __name__ == "__main__":
    run_tuning(
        target_method_name="2-speed-adjusted",
        tuning_parameters={
            # tier caps
            "small_district_cap":       ("int", MIN_SMALL_CAP,  MAX_SMALL_CAP),
            "medium_district_cap":      ("int", MIN_MEDIUM_CAP, MAX_MEDIUM_CAP),
            "large_district_cap":       ("int", MIN_LARGE_CAP,  MAX_LARGE_CAP),
            # tier thresholds
            "small_district_threshold": ("int", MIN_SMALL_THRESHOLD, MAX_SMALL_THRESHOLD),
            "large_district_threshold": ("int", MIN_LARGE_THRESHOLD, MAX_LARGE_THRESHOLD),
        },
        tuning_goals={
            "unweighted_gallagher": ("min", 0),
            "weighted_gallagher":   ("min", 1),
            "inversions":           ("min", 1),
            "dips":                 ("min", 0),
            "pairs":                ("min", 0),
            "magnitude":            ("min", 0),
        },
        sims_per_trial=30,
        max_time_minutes=150,
        cooling_pause_per_trial=1.5,
        use_grid_search=False,   # 5-D grid is huge; use stochastic search instead
        show_all_trials=False
    )