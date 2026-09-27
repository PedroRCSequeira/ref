import os
from typing import Any, Dict, List

# ==============================================================================
# MASTER GLOBAL RUN CONFIGURATION LAYER
# ==============================================================================
ENABLE_MONTE_CARLO = True     # True for Monte Carlo simulations, False for raw historical reports
ENABLE_DANISH_DP = True       # Global Toggle: True to enable Danish DP calculations & tables
ENABLE_STAIRCASE_PLOTS = 0     # 1 to generate and save staircase charts to disk; 0 to disable
SHOW_PLOT_POPUPS = 0           # 0 = Save images silently to folder; 1 = Open popups sequentially

SIMULATIONS = 500              # Total valid variant runs executed per historical election cycle
NATIONAL_VARIATION = 8.0       # Maximum uniform national party swing boundary (± percentage points)
LOCAL_VARIATION = 2.0          # Maximum independent regional district variance shift factor (± percentage)
RANDOM_SEED = 12345            # Base master algorithm initializer seed value

# --- QUOTIENT EFFICIENCY & DIAGNOSTIC TOGGLES ---
SHOW_QUOTIENT_STATS_CONSOLE = 1  # 1 to display quotient milestone efficiency tables in console; 0 to hide
SHOW_QUOTIENT_STATS_EXCEL = 1    # 1 to include quotient efficiency summary sheets in Excel export; 0 to hide
QUOTIENT_MILESTONES = [50, 60, 70, 80, 90, 100] # Decile percentages for mandate completion

# --- THERMAL MANAGEMENT ---
SIM_BATCH_SIZE = 25             # Run simulations in batches of x
SIM_COOLING_PAUSE = 2.0          # Pause for 2 seconds between batches to keep CPU cool

SUPPORTED_REGIONS = {"portugal", "zurich"}

# Formatting Color Codes
GREEN, RED, BLUE, YELLOW, RESET = "\033[92m", "\033[91m", "\033[94m", "\033[93m", "\033[0m"
BG_RED_WHITE = "\033[41m\033[97m"
BG_SHADE = "\033[47m"