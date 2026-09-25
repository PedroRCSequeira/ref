import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from config import QUOTIENT_MILESTONES

# ==============================================================================
# 1. METHOD TUNING CONSTANTS & DEFAULTS
# ==============================================================================
# Smallest First Method Defaults
DEFAULT_SMALLEST_FIRST_STEP = 3          # Divisor increment step (+3: 1, 4, 7, 10...)
DEFAULT_SMALLEST_FIRST_TIER1_CAP = 5     # Tier 1: Parties with <= 5 national mandates
DEFAULT_SMALLEST_FIRST_TIER2_CAP = 20    # Tier 2: Parties with 6 to 20 national mandates

# 2-Speed Danish Pool Defaults
DEFAULT_TWO_SPEED_ROUND1_DISTRICT_CAP = 4 # Max seats per party per district in Round 1

# Non-Formula Progressive Parameters (Defaults aligned with [1, 4, 5, 3, 5, 4, 24, 6])
NON_FORMULA_EXPLICIT_DIVISORS: List[int] = []  

# Dynamic gap-based configuration guarantees strictly monotonic growth regardless of count changes
NON_FORMULA_PROGRESSIVE_PHASES: List[Dict[str, Any]] = [
    {"start": 1, "step": 4, "count": 5},       # Phase 1: 1, 5, 9, 13, 17
    {"gap": 3,   "step": 5, "count": 4},       # Phase 2: Starts at 17+3=20 -> 20, 25, 30, 35
    {"gap": 24,  "step": 6, "count": None}     # Phase 3: Starts at 35+24=59 -> 59, 65, 71, 77, ...
    # These produced weighted gallagher 6.1 and inversion 0.69 for the PTdata 2015-2025
]


# ==============================================================================
# 2. HELPER & DIVISOR FUNCTIONS
# ==============================================================================

def compute_quotient_milestones(
    history_log: List[Dict[str, Any]], 
    total_mandates: int, 
    milestones: List[int] = QUOTIENT_MILESTONES
) -> Dict[int, Dict[str, Any]]:
    results = {}
    if not history_log or total_mandates <= 0:
        return results

    running_map = {}
    for entry in history_log:
        rt = entry["Running Total"]
        if rt not in running_map:
            running_map[rt] = entry["Step"]

    for pct in milestones:
        target_seats = math.ceil(total_mandates * (pct / 100.0))
        step_eval = running_map.get(target_seats)
        if step_eval is None:
            for rt in range(target_seats, total_mandates + 1):
                if rt in running_map:
                    step_eval = running_map[rt]
                    break
        if step_eval is None:
            step_eval = history_log[-1]["Step"] if history_log else total_mandates

        skipped = step_eval - target_seats
        eff = (target_seats / step_eval * 100.0) if step_eval > 0 else 100.0
        results[pct] = {
            "target_seats": target_seats,
            "quotients_eval": step_eval,
            "skipped": skipped,
            "efficiency_pct": eff
        }
    return results


def get_non_formula_progressive_divisor(n: int) -> int:
    if n <= len(NON_FORMULA_EXPLICIT_DIVISORS):
        return NON_FORMULA_EXPLICIT_DIVISORS[n - 1]

    seat_pos = n - len(NON_FORMULA_EXPLICIT_DIVISORS)

    # Dynamically resolve relative gaps to absolute start values
    resolved_phases = []
    last_divisor = 0

    for phase in NON_FORMULA_PROGRESSIVE_PHASES:
        p_step = phase["step"]
        p_count = phase["count"]

        if "start" in phase:
            p_start = phase["start"]
        else:
            p_start = last_divisor + phase["gap"]

        resolved_phases.append({"start": p_start, "step": p_step, "count": p_count})

        if p_count is not None:
            last_divisor = p_start + max(0, p_count - 1) * p_step

    curr_seat = 1
    for phase in resolved_phases:
        start, step, count = phase["start"], phase["step"], phase["count"]
        if count is None or seat_pos < curr_seat + count:
            offset = seat_pos - curr_seat
            return start + offset * step
        curr_seat += count

    return 1 + (n - 1) * 3


# ==============================================================================
# 3. ALLOCATION ENGINES
# ==============================================================================

def allocate_pool_method(
    votes_map: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int], 
    divisor_func: Optional[Callable[[int], int]] = None
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    if divisor_func is None:
        divisor_func = lambda n: (n * (n + 1)) // 2 

    all_quotients_pool = []
    for district, parties in votes_map.items():
        max_possible_seats = district_caps[district]
        for party, vote_count in parties.items():
            if party_caps.get(party, 0) == 0:
                continue
            for seat_idx in range(1, max_possible_seats + 1):
                divisor = divisor_func(seat_idx)
                if divisor <= 0: divisor = 1
                all_quotients_pool.append({
                    "District": district, "Party": party,
                    "Quotient": round(vote_count / divisor, 4),
                    "Divisor Used": divisor, "Seat Attempt #": seat_idx
                })
                
    all_quotients_pool.sort(key=lambda x: (x["District"], x["Party"]))
    all_quotients_pool.sort(key=lambda x: x["Quotient"], reverse=True)

    final_allocations = {d: {p: 0 for p in party_caps.keys()} for d in district_caps.keys()}
    party_won = {p: 0 for p in party_caps.keys()}
    district_won = {d: 0 for d in district_caps.keys()}
    
    total_allocated = 0
    max_needed = sum(district_caps.values())
    history_log = []
    step_idx = 0
    
    for item in all_quotients_pool:
        if total_allocated >= max_needed:
            break
        step_idx += 1
        d, p = item["District"], item["Party"]
        district_full = district_won[d] >= district_caps[d]
        party_full = party_won[p] >= party_caps[p]
        
        if district_full and party_full: status = "No - Both Caps Reached"
        elif district_full: status = "No - District Cap Reached"
        elif party_full: status = "No - National Party Cap Reached"
        else:
            status = "Yes"
            final_allocations[d][p] += 1
            party_won[p] += 1
            district_won[d] += 1
            total_allocated += 1
            
        history_log.append({
            "Step": step_idx,
            "District": d, 
            "Party": p, 
            "Quotient": item["Quotient"],
            "Divisor": item["Divisor Used"], 
            "Seat Attempt": item["Seat Attempt #"],
            "Allocated": status,
            "Running Total": total_allocated
        })
    return final_allocations, party_won, history_log


def allocate_progressive_pool_method(
    votes_map: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int], 
    phase1_start: int = 1, phase1_step: int = 4, phase1_count: int = 5,
    phase2_gap: int = 3,   phase2_step: int = 5, phase2_count: int = 4,
    phase3_gap: int = 24,  phase3_step: int = 6
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    """
    Multi-phase progressive pool engine wrapper. 
    Uses relative gaps (phase2_gap, phase3_gap) to guarantee independent,
    strictly sequential phase transitions during tuning.
    """
    # 1. Compute Phase 1 Last Divisor
    p1_last_divisor = phase1_start + max(0, phase1_count - 1) * phase1_step

    # 2. Derive Phase 2 Start from Phase 1 End + Relative Gap
    phase2_start = p1_last_divisor + phase2_gap
    p2_last_divisor = phase2_start + max(0, phase2_count - 1) * phase2_step

    # 3. Derive Phase 3 Start from Phase 2 End + Relative Gap
    phase3_start = p2_last_divisor + phase3_gap

    phases = [
        {"start": phase1_start, "step": phase1_step, "count": phase1_count},
        {"start": phase2_start, "step": phase2_step, "count": phase2_count},
        {"start": phase3_start, "step": phase3_step, "count": None}
    ]

    def dynamic_divisor_func(n: int) -> int:
        curr_seat = 1
        for phase in phases:
            start, step, count = phase["start"], phase["step"], phase["count"]
            if count is None or n < curr_seat + count:
                offset = n - curr_seat
                return start + offset * step
            curr_seat += count
        return 1 + (n - 1) * 3

    return allocate_pool_method(votes_map, party_caps, district_caps, divisor_func=dynamic_divisor_func)


def allocate_smallest_first_pool_method(
    votes_map: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int], 
    step: int = DEFAULT_SMALLEST_FIRST_STEP,
    tier1_cap: int = DEFAULT_SMALLEST_FIRST_TIER1_CAP,
    tier2_cap: int = DEFAULT_SMALLEST_FIRST_TIER2_CAP
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    divisor_func = lambda n: 1 + step * (n - 1)

    tier1_parties = [p for p, cap in party_caps.items() if cap <= tier1_cap]
    tier2_parties = [p for p, cap in party_caps.items() if tier1_cap < cap <= tier2_cap]
    tier3_parties = [p for p, cap in party_caps.items() if cap > tier2_cap]

    tiers = [tier1_parties, tier2_parties, tier3_parties]

    final_allocations = {d: {p: 0 for p in party_caps.keys()} for d in district_caps.keys()}
    party_won = {p: 0 for p in party_caps.keys()}
    district_won = {d: 0 for d in district_caps.keys()}

    total_allocated = 0
    max_needed = sum(district_caps.values())
    history_log = []
    step_idx = 0

    for party_group in tiers:
        if not party_group:
            continue

        tier_quotients = []
        for district, parties in votes_map.items():
            max_possible_seats = district_caps[district]
            for party in party_group:
                vote_count = parties.get(party, 0)
                if party_caps.get(party, 0) == 0:
                    continue
                for seat_idx in range(1, max_possible_seats + 1):
                    divisor = divisor_func(seat_idx)
                    if divisor <= 0: divisor = 1
                    tier_quotients.append({
                        "District": district, "Party": party,
                        "Quotient": round(vote_count / divisor, 4),
                        "Divisor Used": divisor, "Seat Attempt #": seat_idx
                    })

        tier_quotients.sort(key=lambda x: (x["District"], x["Party"]))
        tier_quotients.sort(key=lambda x: x["Quotient"], reverse=True)

        for item in tier_quotients:
            if total_allocated >= max_needed:
                break
            step_idx += 1
            d, p = item["District"], item["Party"]
            district_full = district_won[d] >= district_caps[d]
            party_full = party_won[p] >= party_caps[p]

            if district_full and party_full: status = "No - Both Caps Reached"
            elif district_full: status = "No - District Cap Reached"
            elif party_full: status = "No - National Party Cap Reached"
            else:
                status = "Yes"
                final_allocations[d][p] += 1
                party_won[p] += 1
                district_won[d] += 1
                total_allocated += 1

            history_log.append({
                "Step": step_idx,
                "District": d, 
                "Party": p, 
                "Quotient": item["Quotient"],
                "Divisor": item["Divisor Used"], 
                "Seat Attempt": item["Seat Attempt #"],
                "Allocated": status,
                "Running Total": total_allocated
            })

    return final_allocations, party_won, history_log


def allocate_two_speed_pool_method(
    votes_map: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int], 
    round1_district_cap: int = DEFAULT_TWO_SPEED_ROUND1_DISTRICT_CAP,
    divisor_func: Optional[Callable[[int], int]] = None
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    """
    2-Speed Pool Allocation Engine:
    
    Round 1: Standard global pool allocation using Danish divisors (1, 4, 7, 10...),
    constrained to a maximum of `round1_district_cap` seats per party in any single district.
    
    Round 2: Uncapped global pool allocation using all remaining unallocated quotients 
    to assign any remaining mandates.
    """
    if divisor_func is None:
        divisor_func = lambda n: 1 + 3 * (n - 1)  # Danish default: 1, 4, 7, 10...

    all_quotients_pool = []
    for district, parties in votes_map.items():
        max_possible_seats = district_caps[district]
        for party, vote_count in parties.items():
            if party_caps.get(party, 0) == 0:
                continue
            for seat_idx in range(1, max_possible_seats + 1):
                divisor = divisor_func(seat_idx)
                if divisor <= 0: divisor = 1
                all_quotients_pool.append({
                    "District": district, "Party": party,
                    "Quotient": round(vote_count / divisor, 4),
                    "Divisor Used": divisor, "Seat Attempt #": seat_idx,
                    "_used": False
                })

    all_quotients_pool.sort(key=lambda x: (x["District"], x["Party"]))
    all_quotients_pool.sort(key=lambda x: x["Quotient"], reverse=True)

    final_allocations = {d: {p: 0 for p in party_caps.keys()} for d in district_caps.keys()}
    party_won = {p: 0 for p in party_caps.keys()}
    district_won = {d: 0 for d in district_caps.keys()}

    total_allocated = 0
    max_needed = sum(district_caps.values())
    history_log = []
    step_idx = 0

    # PHASE 1: ROUND 1 ALLOCATION (Capped per-district party limit)
    for item in all_quotients_pool:
        if total_allocated >= max_needed:
            break

        d, p = item["District"], item["Party"]
        district_full = district_won[d] >= district_caps[d]
        party_full = party_won[p] >= party_caps[p]
        round1_cap_reached = final_allocations[d][p] >= round1_district_cap

        if district_full or party_full or round1_cap_reached:
            continue

        step_idx += 1
        item["_used"] = True
        final_allocations[d][p] += 1
        party_won[p] += 1
        district_won[d] += 1
        total_allocated += 1

        history_log.append({
            "Step": step_idx,
            "District": d, 
            "Party": p, 
            "Quotient": item["Quotient"],
            "Divisor": item["Divisor Used"], 
            "Seat Attempt": item["Seat Attempt #"],
            "Allocated": "Yes",
            "Running Total": total_allocated
        })

    # PHASE 2: ROUND 2 ALLOCATION (Uncapped global pool for remaining seats)
    if total_allocated < max_needed:
        remaining_pool = [q for q in all_quotients_pool if not q["_used"]]
        remaining_pool.sort(key=lambda x: (x["District"], x["Party"]))
        remaining_pool.sort(key=lambda x: x["Quotient"], reverse=True)

        for item in remaining_pool:
            if total_allocated >= max_needed:
                break

            step_idx += 1
            item["_used"] = True
            d, p = item["District"], item["Party"]
            district_full = district_won[d] >= district_caps[d]
            party_full = party_won[p] >= party_caps[p]

            if district_full and party_full: status = "No - Both Caps Reached"
            elif district_full: status = "No - District Cap Reached"
            elif party_full: status = "No - National Party Cap Reached"
            else:
                status = "Yes"
                final_allocations[d][p] += 1
                party_won[p] += 1
                district_won[d] += 1
                total_allocated += 1

            history_log.append({
                "Step": step_idx,
                "District": d, 
                "Party": p, 
                "Quotient": item["Quotient"],
                "Divisor": item["Divisor Used"], 
                "Seat Attempt": item["Seat Attempt #"],
                "Allocated": status,
                "Running Total": total_allocated
            })

    return final_allocations, party_won, history_log


# ==============================================================================
# 4. MASTER CUSTOM METHODS REGISTRY (SINGLE SOURCE OF TRUTH)
# ==============================================================================

CUSTOM_METHODS_REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "Smallest First",
        "enabled": False,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_smallest_first_pool_method,
        "kwargs": {
            "step": DEFAULT_SMALLEST_FIRST_STEP, 
            "tier1_cap": DEFAULT_SMALLEST_FIRST_TIER1_CAP, 
            "tier2_cap": DEFAULT_SMALLEST_FIRST_TIER2_CAP
        }
    },
    {
        "name": "2-Speed",
        "enabled": True,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_two_speed_pool_method,
        "kwargs": {
            "round1_district_cap": DEFAULT_TWO_SPEED_ROUND1_DISTRICT_CAP, 
            "divisor_func": lambda n: 1 + 3 * (n - 1)
        }
    },
    {
        "name": "Non-Formula Progressive",
        "enabled": True,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_progressive_pool_method,
        "kwargs": {
            "phase1_start": 1, "phase1_step": 4, "phase1_count": 5,
            "phase2_gap": 3,   "phase2_step": 5, "phase2_count": 4,
            "phase3_gap": 24,  "phase3_step": 6
        }
    },
    {
        "name": "Exquisite Progressive Pool Method",
        "enabled": True,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_pool_method,
        "kwargs": {"divisor_func": lambda n: (n**2 + 3*n - 2) // 2}
    },
    {
        "name": "Quadratic Pool Method",
        "enabled": True,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_pool_method,
        "kwargs": {"divisor_func": lambda n: n ** 2}
    },
    {
        "name": "Triangular Pool",
        "enabled": False,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "func": allocate_pool_method,
        "kwargs": {"divisor_func": lambda n: (n * (n + 1)) // 2}
    }
]