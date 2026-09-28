import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from config import QUOTIENT_MILESTONES

# ==============================================================================
# 1. METHOD TUNING CONSTANTS & DEFAULTS (SINGLE SOURCE OF TRUTH)
# ==============================================================================
# Smallest First Method Defaults
DEFAULT_SMALLEST_FIRST_STEP = 3          # Divisor increment step (+3: 1, 4, 7, 10...)
DEFAULT_SMALLEST_FIRST_TIER1_CAP = 5     # Tier 1: Parties with <= 5 national mandates
DEFAULT_SMALLEST_FIRST_TIER2_CAP = 20    # Tier 2: Parties with 6 to 20 national mandates

# 2-Speed Danish Pool Defaults
DEFAULT_TWO_SPEED_ROUND1_DISTRICT_CAP = 4  # Max seats per party per district in Round 1

# 2-Speed-Adjusted Pool Defaults (tiered Round-1 caps based on district size)
DEFAULT_TWO_SPEED_ADJ_SMALL_THRESHOLD = 6   # Districts with size  < this  -> "small"
DEFAULT_TWO_SPEED_ADJ_LARGE_THRESHOLD = 20  # Districts with size  < this  -> "medium"; else "large"
DEFAULT_TWO_SPEED_ADJ_SMALL_CAP = 2         # Round-1 cap for small districts
DEFAULT_TWO_SPEED_ADJ_MEDIUM_CAP = 3        # Round-1 cap for medium districts
DEFAULT_TWO_SPEED_ADJ_LARGE_CAP = 4         # Round-1 cap for large districts

# Non-Formula Progressive Defaults [1, 3, 4, 4, 7, 10]
DEFAULT_PROGRESSIVE_PHASE1_START = 1
DEFAULT_PROGRESSIVE_PHASE1_STEP = 3
DEFAULT_PROGRESSIVE_PHASE1_COUNT = 4
DEFAULT_PROGRESSIVE_PHASE2_STEP = 4
DEFAULT_PROGRESSIVE_PHASE2_COUNT = 7
DEFAULT_PROGRESSIVE_PHASE3_STEP = 10


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


def get_non_formula_progressive_divisor(
    n: int,
    phase1_start: int = DEFAULT_PROGRESSIVE_PHASE1_START,
    phase1_step: int = DEFAULT_PROGRESSIVE_PHASE1_STEP,
    phase1_count: int = DEFAULT_PROGRESSIVE_PHASE1_COUNT,
    phase2_step: int = DEFAULT_PROGRESSIVE_PHASE2_STEP,
    phase2_count: int = DEFAULT_PROGRESSIVE_PHASE2_COUNT,
    phase3_step: int = DEFAULT_PROGRESSIVE_PHASE3_STEP,
) -> int:
    """Calculates the exact divisor for seat position n in the 3-Speed Progressive Method."""
    p1_last = phase1_start + max(0, phase1_count - 1) * phase1_step
    p2_last = p1_last + phase2_count * phase2_step

    if n <= phase1_count:
        return phase1_start + (n - 1) * phase1_step
    elif n <= phase1_count + phase2_count:
        offset = n - phase1_count
        return p1_last + offset * phase2_step
    else:
        offset = n - (phase1_count + phase2_count)
        return p2_last + offset * phase3_step


def _snapshot_allocations(
    final_allocations: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int]
) -> Dict[str, Dict[str, int]]:
    """Returns a deep-copy snapshot of the current (district, party) -> seat matrix."""
    return {
        d: {p: final_allocations[d][p] for p in party_caps.keys()}
        for d in district_caps.keys()
    }


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
    phase1_start: int = DEFAULT_PROGRESSIVE_PHASE1_START, 
    phase1_step: int = DEFAULT_PROGRESSIVE_PHASE1_STEP, 
    phase1_count: int = DEFAULT_PROGRESSIVE_PHASE1_COUNT,
    phase2_step: int = DEFAULT_PROGRESSIVE_PHASE2_STEP, 
    phase2_count: int = DEFAULT_PROGRESSIVE_PHASE2_COUNT,
    phase3_step: int = DEFAULT_PROGRESSIVE_PHASE3_STEP
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    """
    3-Speed Piecewise Linear Divisor Engine (Seamless Transitions):
    - Phase 1: Starts at phase1_start, advances by phase1_step for phase1_count seats.
    - Phase 2: Continues seamlessly, advancing by phase2_step for phase2_count seats.
    - Phase 3: Continues seamlessly, advancing by phase3_step indefinitely.
    """
    dynamic_divisor_func = lambda n: get_non_formula_progressive_divisor(
        n, phase1_start, phase1_step, phase1_count, phase2_step, phase2_count, phase3_step
    )

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
    divisor_func: Optional[Callable[[int], int]] = None,
    phase_tracker: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    """
    Standard 2-Speed method. Optionally populates `phase_tracker["phase1"]`
    with a per-(district, party) snapshot taken at the end of Round 1.
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

    # PHASE 1: ROUND 1 ALLOCATION
    for item in all_quotients_pool:
        if total_allocated >= max_needed:
            break

        step_idx += 1
        d, p = item["District"], item["Party"]
        district_full = district_won[d] >= district_caps[d]
        party_full = party_won[p] >= party_caps[p]
        round1_cap_reached = final_allocations[d][p] >= round1_district_cap

        if district_full and party_full:
            status = "No - Both Caps Reached"
        elif district_full:
            status = "No - District Cap Reached"
        elif party_full:
            status = "No - National Party Cap Reached"
        elif round1_cap_reached:
            status = "No - Round 1 District Cap Reached"
        else:
            status = "Yes"
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
            "Allocated": status,
            "Running Total": total_allocated
        })

    # Snapshot end of Phase 1
    if phase_tracker is not None:
        phase_tracker["phase1"] = _snapshot_allocations(final_allocations, party_caps, district_caps)

    # PHASE 2: ROUND 2 ALLOCATION
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


def allocate_two_speed_adjusted_pool_method(
    votes_map: Dict[str, Dict[str, int]], 
    party_caps: Dict[str, int], 
    district_caps: Dict[str, int], 
    divisor_func: Optional[Callable[[int], int]] = None,
    small_district_threshold: int = DEFAULT_TWO_SPEED_ADJ_SMALL_THRESHOLD,
    large_district_threshold: int = DEFAULT_TWO_SPEED_ADJ_LARGE_THRESHOLD,
    small_district_cap: int = DEFAULT_TWO_SPEED_ADJ_SMALL_CAP,
    medium_district_cap: int = DEFAULT_TWO_SPEED_ADJ_MEDIUM_CAP,
    large_district_cap: int = DEFAULT_TWO_SPEED_ADJ_LARGE_CAP,
    phase_tracker: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], List[Dict[str, Any]]]:
    """
    Like the standard 2-Speed method, but Round 1's per-party-per-district cap
    is dynamically chosen from three tiers based on the district's total size:

        size <  small_district_threshold                 -> small_district_cap
        small_district_threshold <= size < large_threshold -> medium_district_cap
        size >= large_district_threshold                 -> large_district_cap

    Optionally populates `phase_tracker["phase1"]` with a per-(district, party)
    snapshot taken at the end of Round 1.
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

    # Determine dynamic Round 1 district cap based on district size
    round1_caps: Dict[str, int] = {}
    for d, size in district_caps.items():
        if size < small_district_threshold:
            round1_caps[d] = small_district_cap
        elif size < large_district_threshold:
            round1_caps[d] = medium_district_cap
        else:
            round1_caps[d] = large_district_cap

    # PHASE 1: ROUND 1 ALLOCATION (Tiered Caps)
    for item in all_quotients_pool:
        if total_allocated >= max_needed:
            break

        step_idx += 1
        d, p = item["District"], item["Party"]
        district_full = district_won[d] >= district_caps[d]
        party_full = party_won[p] >= party_caps[p]
        round1_cap_reached = final_allocations[d][p] >= round1_caps[d]

        if district_full and party_full:
            status = "No - Both Caps Reached"
        elif district_full:
            status = "No - District Cap Reached"
        elif party_full:
            status = "No - National Party Cap Reached"
        elif round1_cap_reached:
            status = "No - Round 1 District Cap Reached"
        else:
            status = "Yes"
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
            "Allocated": status,
            "Running Total": total_allocated
        })

    # Snapshot end of Phase 1
    if phase_tracker is not None:
        phase_tracker["phase1"] = _snapshot_allocations(final_allocations, party_caps, district_caps)

    # PHASE 2: ROUND 2 ALLOCATION (Uncapped)
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
        "supports_phase_tracking": True,
        "func": allocate_two_speed_pool_method,
        "kwargs": {
            "round1_district_cap": DEFAULT_TWO_SPEED_ROUND1_DISTRICT_CAP, 
            "divisor_func": lambda n: 1 + 3 * (n - 1)
        }
    },
    {
        "name": "2-speed-adjusted",
        "enabled": True,
        "run_historical": True,
        "run_monte_carlo": True,
        "show_console": True,
        "show_excel": True,
        "supports_phase_tracking": True,
        "func": allocate_two_speed_adjusted_pool_method,
        "kwargs": {
            "divisor_func": lambda n: 1 + 3 * (n - 1),
            "small_district_threshold": DEFAULT_TWO_SPEED_ADJ_SMALL_THRESHOLD,
            "large_district_threshold": DEFAULT_TWO_SPEED_ADJ_LARGE_THRESHOLD,
            "small_district_cap":       DEFAULT_TWO_SPEED_ADJ_SMALL_CAP,
            "medium_district_cap":      DEFAULT_TWO_SPEED_ADJ_MEDIUM_CAP,
            "large_district_cap":       DEFAULT_TWO_SPEED_ADJ_LARGE_CAP,
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
            "phase1_start": DEFAULT_PROGRESSIVE_PHASE1_START,
            "phase1_step": DEFAULT_PROGRESSIVE_PHASE1_STEP,
            "phase1_count": DEFAULT_PROGRESSIVE_PHASE1_COUNT,
            "phase2_step": DEFAULT_PROGRESSIVE_PHASE2_STEP,
            "phase2_count": DEFAULT_PROGRESSIVE_PHASE2_COUNT,
            "phase3_step": DEFAULT_PROGRESSIVE_PHASE3_STEP
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