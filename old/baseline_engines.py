import math
import heapq
from typing import Dict, List, Optional, Tuple

def dhondt_apportion(weights: Dict[str, int], seats_target: int) -> Dict[str, int]:
    seats = {k: 0 for k in weights}
    active = [(k, w) for k, w in weights.items() if w > 0]
    if seats_target <= 0 or not active:
        return seats
    
    for _ in range(seats_target):
        best_party = max(active, key=lambda x: weights[x[0]] / (seats[x[0]] + 1))
        seats[best_party[0]] += 1
    return seats


def sainte_lague_apportion(weights: Dict[str, float], seats_target: int) -> Tuple[Dict[str, int], float]:
    seats = {k: 0 for k in weights}
    active = [(k, w) for k, w in weights.items() if w > 0]
    if seats_target <= 0 or not active:
        return seats, float('inf')

    heap = [(-float(w), k) for k, w in active]
    heapq.heapify(heap)

    last_quotient = None
    for _ in range(seats_target):
        if not heap:
            break
        neg_quotient, k = heapq.heappop(heap)
        last_quotient = -neg_quotient
        seats[k] += 1
        new_divisor = 2 * seats[k] + 1
        heapq.heappush(heap, (-weights[k] / new_divisor, k))

    next_quotient = -heap[0][0] if heap else 0.0
    divisor = (last_quotient + next_quotient) if (last_quotient is not None and next_quotient > 0) else (2.0 * last_quotient if last_quotient else float('inf'))

    return seats, divisor


def danish_apportion(weights: Dict[str, float], seats_target: int) -> Tuple[Dict[str, int], float]:
    seats = {k: 0 for k in weights}
    active = [(k, w) for k, w in weights.items() if w > 0]
    if seats_target <= 0 or not active:
        return seats, float('inf')

    heap = [(-float(w), k) for k, w in active]
    heapq.heapify(heap)

    last_quotient = None
    for _ in range(seats_target):
        if not heap:
            break
        neg_quotient, k = heapq.heappop(heap)
        last_quotient = -neg_quotient
        seats[k] += 1
        new_divisor = 3 * seats[k] + 1
        heapq.heappush(heap, (-weights[k] / new_divisor, k))

    next_quotient = -heap[0][0] if heap else 0.0
    divisor = (last_quotient + next_quotient) if (last_quotient is not None and next_quotient > 0) else (2.0 * last_quotient if last_quotient else float('inf'))

    return seats, divisor


def get_national_party_caps(country_name: str, national_votes: Dict[str, int], total_mandates: int, national_mandates_override: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    if national_mandates_override is not None:
        return national_mandates_override

    c_lower = country_name.lower()
    if c_lower == "zurich":
        caps, _ = sainte_lague_apportion({k: float(v) for k, v in national_votes.items()}, total_mandates)
        return caps
    elif c_lower == "portugal":
        return dhondt_apportion(national_votes, total_mandates)
    else:
        raise NotImplementedError(f"No national mandate rule defined for region '{country_name}'.")


def _divisor_interval_sainte_lague(votes_vector: Dict[str, int], other_divs: Dict[str, float], seats_vector: Dict[str, int]) -> Tuple[float, float]:
    lo, hi = 0.0, float('inf')
    for k, v in votes_vector.items():
        d = other_divs.get(k, 1.0)
        if d == float('inf') or d <= 0 or v == 0:
            continue
        a = seats_vector[k]
        low_k = v / (d * (2 * a + 1))
        if low_k > lo: lo = low_k
        if a > 0:
            high_k = v / (d * (2 * a - 1))
            if high_k < hi: hi = high_k
    return lo, hi


def _divisor_interval_danish(votes_vector: Dict[str, int], other_divs: Dict[str, float], seats_vector: Dict[str, int]) -> Tuple[float, float]:
    lo, hi = 0.0, float('inf')
    for k, v in votes_vector.items():
        d = other_divs.get(k, 1.0)
        if d == float('inf') or d <= 0 or v == 0:
            continue
        a = seats_vector[k]
        low_k = v / (d * (3 * a + 1))
        if low_k > lo: lo = low_k
        if a > 0:
            high_k = v / (d * (3 * a - 2))
            if high_k < hi: hi = high_k
    return lo, hi


def _centered_divisor(lo: float, hi: float, fallback: float) -> float:
    if hi == float('inf') or lo <= 0 or lo >= hi:
        return fallback
    return math.sqrt(lo * hi)


def _refit_divisors(seats: Dict[str, Dict[str, int]], votes_map: Dict[str, Dict[str, int]], party_caps: Dict[str, int], district_caps: Dict[str, int], method_type: str = "zurich") -> Tuple[Dict[str, float], Dict[str, float]]:
    districts = list(district_caps.keys())
    parties = list(party_caps.keys())
    row_div = {d: 1.0 for d in districts}
    col_div = {p: (float('inf') if party_caps[p] == 0 else 1.0) for p in parties}
    interval_func = _divisor_interval_danish if method_type.lower() == "danish" else _divisor_interval_sainte_lague

    for _ in range(50):
        for d in districts:
            lo, hi = interval_func(votes_map[d], col_div, seats[d])
            row_div[d] = _centered_divisor(lo, hi, fallback=row_div[d])

        for p in parties:
            if party_caps[p] == 0: continue
            col_votes = {d: votes_map[d][p] for d in districts}
            col_seats = {d: seats[d][p] for d in districts}
            lo, hi = interval_func(col_votes, row_div, col_seats)
            col_div[p] = _centered_divisor(lo, hi, fallback=col_div[p])

    return row_div, col_div


def _seat_transfer_repair(seats: Dict[str, Dict[str, int]], votes_map: Dict[str, Dict[str, int]], party_caps: Dict[str, int], district_caps: Dict[str, int], method_type: str = "zurich", max_attempts: int = 500) -> bool:
    districts = list(district_caps.keys())
    parties = list(party_caps.keys())

    def row_surplus(d): return sum(seats[d][p] for p in parties) - district_caps[d]
    def col_surplus(p): return sum(seats[d][p] for d in districts) - party_caps[p]
    is_danish = (method_type.lower() == "danish")

    for _ in range(max_attempts):
        over_rows = [d for d in districts if row_surplus(d) > 0]
        under_rows = [d for d in districts if row_surplus(d) < 0]
        over_cols = [p for p in parties if col_surplus(p) > 0]
        under_cols = [p for p in parties if col_surplus(p) < 0]

        if not over_rows and not under_rows and not over_cols and not under_cols:
            return True

        moved = False
        for d_over in over_rows:
            for d_under in under_rows:
                candidates = []
                for p in parties:
                    if seats[d_over][p] <= 0: continue
                    v_over, v_under = votes_map[d_over][p], votes_map[d_under][p]
                    a_over_after, a_under_after = seats[d_over][p] - 1, seats[d_under][p] + 1
                    
                    if is_danish:
                        q_over_after = v_over / (3 * a_over_after + 1) if v_over > 0 else 0.0
                        q_under_after = v_under / (3 * a_under_after - 2) if (v_under > 0 and a_under_after > 0) else float('inf')
                    else:
                        q_over_after = v_over / (2 * a_over_after + 1) if v_over > 0 else 0.0
                        q_under_after = v_under / (2 * a_under_after - 1) if (v_under > 0 and a_under_after > 0) else float('inf')

                    candidates.append((abs(q_over_after - q_under_after), p))
                if candidates:
                    candidates.sort()
                    _, p = candidates[0]
                    seats[d_over][p] -= 1
                    seats[d_under][p] += 1
                    moved = True
                    break
            if moved: break

        if not moved:
            for p_over in over_cols:
                for p_under in under_cols:
                    candidates = []
                    for d in districts:
                        if seats[d][p_over] <= 0: continue
                        v_over, v_under = votes_map[d][p_over], votes_map[d][p_under]
                        a_over_after, a_under_after = seats[d][p_over] - 1, seats[d][p_under] + 1
                        
                        if is_danish:
                            q_over_after = v_over / (3 * a_over_after + 1) if v_over > 0 else 0.0
                            q_under_after = v_under / (3 * a_under_after - 2) if (v_under > 0 and a_under_after > 0) else float('inf')
                        else:
                            q_over_after = v_over / (2 * a_over_after + 1) if v_over > 0 else 0.0
                            q_under_after = v_under / (2 * a_under_after - 1) if (v_under > 0 and a_under_after > 0) else float('inf')

                        candidates.append((abs(q_over_after - q_under_after), d))
                    if candidates:
                        candidates.sort()
                        _, d = candidates[0]
                        seats[d][p_over] -= 1
                        seats[d][p_under] += 1
                        moved = True
                        break
                if moved: break

        if not moved:
            return False

    return False


def verify_biproportional_integrity(seats: Dict[str, Dict[str, int]], votes_map: Dict[str, Dict[str, int]], party_caps: Dict[str, int], district_caps: Dict[str, int], row_div: Dict[str, float], col_div: Dict[str, float], method_type: str = "zurich") -> Tuple[bool, List[str]]:
    errors = []
    EPS = 1e-9  
    
    for d in district_caps.keys():
        for p in party_caps.keys():
            v = votes_map[d][p]
            r = row_div[d]
            c = col_div[p]
            
            if r <= 0 or c <= 0:
                errors.append(f"Invalid non-positive multiplier at District '{d}' ({r}) or Party '{p}' ({c})")
                continue
                
            q = 0.0 if (c == float('inf') or r == float('inf')) else (v / (r * c)) + EPS
            reconstructed_seats = math.floor((q + 2.0) / 3.0) if (method_type.lower() == "danish" and q >= 1.0) else (math.floor((q + 1.0) / 2.0) if q >= 1.0 else 0)
                
            actual_seats = seats[d][p]
            if reconstructed_seats != actual_seats:
                errors.append(f"Reconstruction mismatch at District '{d}', Party '{p}': allocated {actual_seats} seat(s), but multipliers yield {reconstructed_seats} seat(s) (quotient: {q:.4f})")

    for d, expected_cap in district_caps.items():
        actual_sum = sum(seats[d][p] for p in party_caps.keys())
        if actual_sum != expected_cap:
            errors.append(f"District '{d}' seats sum to {actual_sum}, expected {expected_cap} (Delta: {actual_sum - expected_cap:+d})")

    for p, expected_cap in party_caps.items():
        actual_sum = sum(seats[d][p] for d in district_caps.keys())
        if actual_sum != expected_cap:
            errors.append(f"Party '{p}' seats sum to {actual_sum}, expected {expected_cap} (Delta: {actual_sum - expected_cap:+d})")

    return len(errors) == 0, errors


def allocate_double_proportionality(votes_map: Dict[str, Dict[str, int]], party_caps: Dict[str, int], district_caps: Dict[str, int], max_cycles: int = 1000) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], Dict[str, float], Dict[str, float], bool, List[str]]:
    districts = list(district_caps.keys())
    parties = list(party_caps.keys())
    row_div = {d: 1.0 for d in districts}
    col_div = {p: (float('inf') if party_caps[p] == 0 else 1.0) for p in parties}
    seats = {d: {p: 0 for p in parties} for d in districts}
    history = {}
    stall_streak = 0

    for cycle in range(max_cycles):
        for d in districts:
            weights = {p: (votes_map[d][p] / col_div[p] if col_div[p] < float('inf') else 0.0) for p in parties}
            row_seats, _ = sainte_lague_apportion(weights, district_caps[d])
            for p in parties: seats[d][p] = row_seats.get(p, 0)
            lo, hi = _divisor_interval_sainte_lague(votes_map[d], col_div, seats[d])
            row_div[d] = _centered_divisor(lo, hi, fallback=row_div[d])

        if all(sum(seats[d][p] for d in districts) == party_caps[p] for p in parties): break

        for p in parties:
            if party_caps[p] == 0:
                col_div[p] = float('inf')
                for d in districts: seats[d][p] = 0
                continue
            weights = {d: votes_map[d][p] / row_div[d] for d in districts if row_div[d] > 0}
            col_seats, _ = sainte_lague_apportion(weights, party_caps[p])
            for d in districts: seats[d][p] = col_seats.get(d, 0)
            lo, hi = _divisor_interval_sainte_lague({d: votes_map[d][p] for d in districts}, row_div, {d: seats[d][p] for d in districts})
            col_div[p] = _centered_divisor(lo, hi, fallback=col_div[p])

        if all(sum(seats[d][p] for p in parties) == district_caps[d] for d in districts): break

        state_key = tuple(tuple(seats[d][p] for p in parties) for d in districts)
        if state_key in history:
            stall_streak += 1
            factor = 1.0 + (0.0005 * stall_streak)
            if stall_streak % 2 == 0:
                for pp in parties:
                    if col_div[pp] < float('inf'): col_div[pp] *= factor
            else:
                for dd in districts:
                    if row_div[dd] > 0: row_div[dd] *= factor
            if stall_streak > 40: break
            continue
        stall_streak = 0
        history[state_key] = cycle

    is_valid, errors = verify_biproportional_integrity(seats, votes_map, party_caps, district_caps, row_div, col_div, method_type="zurich")
    if not is_valid and _seat_transfer_repair(seats, votes_map, party_caps, district_caps, method_type="zurich"):
        row_div, col_div = _refit_divisors(seats, votes_map, party_caps, district_caps, method_type="zurich")
        is_valid, errors = verify_biproportional_integrity(seats, votes_map, party_caps, district_caps, row_div, col_div, method_type="zurich")

    return seats, {p: sum(seats[d][p] for d in districts) for p in parties}, row_div, col_div, is_valid, errors


def allocate_double_proportionality_danish(votes_map: Dict[str, Dict[str, int]], party_caps: Dict[str, int], district_caps: Dict[str, int], max_cycles: int = 1000) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], Dict[str, float], Dict[str, float], bool, List[str]]:
    districts = list(district_caps.keys())
    parties = list(party_caps.keys())
    row_div = {d: 1.0 for d in districts}
    col_div = {p: (float('inf') if party_caps[p] == 0 else 1.0) for p in parties}
    seats = {d: {p: 0 for p in parties} for d in districts}
    history = {}
    stall_streak = 0

    for cycle in range(max_cycles):
        for d in districts:
            weights = {p: (votes_map[d][p] / col_div[p] if col_div[p] < float('inf') else 0.0) for p in parties}
            row_seats, _ = danish_apportion(weights, district_caps[d])
            for p in parties: seats[d][p] = row_seats.get(p, 0)
            lo, hi = _divisor_interval_danish(votes_map[d], col_div, seats[d])
            row_div[d] = _centered_divisor(lo, hi, fallback=row_div[d])

        if all(sum(seats[d][p] for d in districts) == party_caps[p] for p in parties): break

        for p in parties:
            if party_caps[p] == 0:
                col_div[p] = float('inf')
                for d in districts: seats[d][p] = 0
                continue
            weights = {d: votes_map[d][p] / row_div[d] for d in districts if row_div[d] > 0}
            col_seats, _ = danish_apportion(weights, party_caps[p])
            for d in districts: seats[d][p] = col_seats.get(d, 0)
            lo, hi = _divisor_interval_danish({d: votes_map[d][p] for d in districts}, row_div, {d: seats[d][p] for d in districts})
            col_div[p] = _centered_divisor(lo, hi, fallback=col_div[p])

        if all(sum(seats[d][p] for p in parties) == district_caps[d] for d in districts): break

        state_key = tuple(tuple(seats[d][p] for p in parties) for d in districts)
        if state_key in history:
            stall_streak += 1
            factor = 1.0 + (0.0005 * stall_streak)
            if stall_streak % 2 == 0:
                for pp in parties:
                    if col_div[pp] < float('inf'): col_div[pp] *= factor
            else:
                for dd in districts:
                    if row_div[dd] > 0: row_div[dd] *= factor
            if stall_streak > 40: break
            continue
        stall_streak = 0
        history[state_key] = cycle

    is_valid, errors = verify_biproportional_integrity(seats, votes_map, party_caps, district_caps, row_div, col_div, method_type="danish")
    if not is_valid and _seat_transfer_repair(seats, votes_map, party_caps, district_caps, method_type="danish"):
        row_div, col_div = _refit_divisors(seats, votes_map, party_caps, district_caps, method_type="danish")
        is_valid, errors = verify_biproportional_integrity(seats, votes_map, party_caps, district_caps, row_div, col_div, method_type="danish")

    return seats, {p: sum(seats[d][p] for d in districts) for p in parties}, row_div, col_div, is_valid, errors