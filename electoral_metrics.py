import math
from typing import Any, Dict, List, Tuple

def calculate_mean_district_gallagher(votes_map: Dict[str, Dict[str, int]], allocations_map: Dict[str, Dict[str, int]], parties_lst: List[str]) -> float:
    district_scores = []
    for d_name in votes_map.keys():
        dist_votes_sum = sum(votes_map[d_name][p_name] for p_name in parties_lst)
        dist_seats_sum = sum(allocations_map[d_name][p_name] for p_name in parties_lst)
        
        if dist_votes_sum == 0 or dist_seats_sum == 0:
            district_scores.append(0.0)
            continue
            
        sq_diff_sum = 0.0
        for p_name in parties_lst:
            v_pct = (votes_map[d_name][p_name] / dist_votes_sum) * 100.0
            s_pct = (allocations_map[d_name][p_name] / dist_seats_sum) * 100.0
            sq_diff_sum += (v_pct - s_pct) ** 2
            
        g_district = math.sqrt(0.5 * sq_diff_sum)
        district_scores.append(g_district)
        
    return sum(district_scores) / len(district_scores) if district_scores else 0.0


def calculate_weighted_mean_district_gallagher(votes_map: Dict[str, Dict[str, int]], allocations_map: Dict[str, Dict[str, int]], parties_lst: List[str], district_caps: Dict[str, int]) -> float:
    total_weighted_score = 0.0
    total_seats = 0
    for d_name in votes_map.keys():
        magnitude = district_caps.get(d_name, 0)
        dist_votes_sum = sum(votes_map[d_name][p_name] for p_name in parties_lst)
        dist_seats_sum = sum(allocations_map[d_name][p_name] for p_name in parties_lst)
        
        if dist_votes_sum == 0 or dist_seats_sum == 0:
            g_district = 0.0
        else:
            sq_diff_sum = 0.0
            for p_name in parties_lst:
                v_pct = (votes_map[d_name][p_name] / dist_votes_sum) * 100.0
                s_pct = (allocations_map[d_name][p_name] / dist_seats_sum) * 100.0
                sq_diff_sum += (v_pct - s_pct) ** 2
            g_district = math.sqrt(0.5 * sq_diff_sum)
            
        total_weighted_score += g_district * magnitude
        total_seats += magnitude
        
    return total_weighted_score / total_seats if total_seats > 0 else 0.0


def analyze_inversions(votes_map: Dict[str, Dict[str, int]], allocations_map: Dict[str, Dict[str, int]], parties_lst: List[str]) -> Tuple[Dict[str, Dict[str, str]], str, int, List[str]]:
    marks = {d: {p: "" for p in parties_lst} for d in votes_map.keys()}
    total_inversion_pairs = 0  
    affected_districts = set()
    detailed_logs = []

    for d in votes_map.keys():
        has_plus = {p: False for p in parties_lst}
        has_minus = {p: False for p in parties_lst}
        num_parties = len(parties_lst)

        for i in range(num_parties):
            pA = parties_lst[i]
            for j in range(i + 1, num_parties):
                pB = parties_lst[j]

                if votes_map[d][pA] > votes_map[d][pB] and allocations_map[d][pA] < allocations_map[d][pB]:
                    has_minus[pA] = True
                    has_plus[pB] = True
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pA} had more votes ({votes_map[d][pA]:,}) than {pB} ({votes_map[d][pB]:,}) but received fewer seats ({allocations_map[d][pA]} vs {allocations_map[d][pB]})."
                    )
                elif votes_map[d][pB] > votes_map[d][pA] and allocations_map[d][pB] < allocations_map[d][pA]:
                    has_minus[pB] = True
                    has_plus[pA] = True
                    total_inversion_pairs += 1
                    affected_districts.add(d)
                    detailed_logs.append(
                        f"    - Intra-District '{d}': {pB} had more votes ({votes_map[d][pB]:,}) than {pA} ({votes_map[d][pA]:,}) but received fewer seats ({allocations_map[d][pB]} vs {allocations_map[d][pA]})."
                    )

        for p in parties_lst:
            if has_plus[p] and has_minus[p]:
                marks[d][p] = "+-"
            elif has_plus[p]:
                marks[d][p] = "+"
            elif has_minus[p]:
                marks[d][p] = "-"
            else:
                marks[d][p] = ""

    analysis_str = f"Detected {total_inversion_pairs} intra-district inversion pair(s) across {len(affected_districts)} district(s)."
    return marks, analysis_str, total_inversion_pairs, detailed_logs


def analyze_global_staircase_inversions(
    votes_map: Dict[str, Dict[str, int]], 
    allocations_map: Dict[str, Dict[str, int]], 
    parties_lst: List[str],
    d2l_map: Dict[str, str]
) -> Tuple[int, int, int, List[str], List[Dict[str, Any]], str, List[Tuple[int, int, str, str]]]:
    entries = []
    for d, p_dict in votes_map.items():
        for p in parties_lst:
            v = p_dict[p]
            m = allocations_map[d][p]
            if v > 0 or m > 0:
                entries.append((v, m, d, p))

    entries.sort(key=lambda x: (x[0], x[1]))

    n = len(entries)
    local_dips = 0
    total_dominance_pairs = 0
    displacement_magnitude = 0
    detailed_logs = []
    displacement_incidents = []

    for i in range(n - 1):
        v1, m1, d1, p1 = entries[i]
        v2, m2, d2, p2 = entries[i + 1]
        if m1 > m2:
            local_dips += 1
            if len(detailed_logs) < 10:
                detailed_logs.append(
                    f"    - Global Dip Step #{i+1}->#{i+2}: '{p1}' in '{d1}' ({v1:,} votes, {m1} seats) > '{p2}' in '{d2}' ({v2:,} votes, {m2} seats)"
                )

    for i in range(n):
        v1, m1, d1, p1 = entries[i]
        for j in range(i + 1, n):
            v2, m2, d2, p2 = entries[j]
            if m1 > m2:
                total_dominance_pairs += 1

    running_max_seats = 0
    running_peak_entry = None
    for v, m, d, p in entries:
        if m > running_max_seats:
            running_max_seats = m
            running_peak_entry = (v, m, d, p)
        elif m < running_max_seats and running_peak_entry:
            gap = running_max_seats - m
            displacement_magnitude += gap
            displacement_incidents.append({
                "gap": gap,
                "victim_party": p,
                "victim_district": d,
                "victim_votes": v,
                "victim_seats": m,
                "peak_party": running_peak_entry[3],
                "peak_district": running_peak_entry[2],
                "peak_votes": running_peak_entry[0],
                "peak_seats": running_peak_entry[1]
            })

    mandate_sequence_str = "-".join(f"{d2l_map[e[2]]}{e[1]}" for e in entries)
    return local_dips, total_dominance_pairs, displacement_magnitude, detailed_logs, displacement_incidents, mandate_sequence_str, entries