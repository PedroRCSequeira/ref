import csv
import re
from typing import Any, Dict, List, Tuple

def parse_int_safe(val: Any) -> int:
    """Safely converts string/number representations into integers."""
    if val is None:
        return 0
    s_val = str(val).strip().replace('\xa0', '').replace('"', '').replace("'", "").replace(' ', '')
    if not s_val:
        return 0
        
    if re.match(r'^\d{1,3}(,\d{3})+$', s_val):
        s_val = s_val.replace(',', '')
    else:
        s_val = s_val.replace(',', '.')
        
    try:
        return int(float(s_val))
    except (ValueError, TypeError):
        return 0


def generate_district_letter_mapping(districts: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Generates a deterministic mapping from district names to letters (A, B, C, ..., Z, AA, AB...).
    Returns (district_to_letter, letter_to_district).
    """
    def index_to_letter(n: int) -> str:
        string = ""
        while n >= 0:
            string = chr(n % 26 + 65) + string
            n = n // 26 - 1
        return string

    d2l = {}
    l2d = {}
    for idx, d_name in enumerate(districts):
        letter = index_to_letter(idx)
        d2l[d_name] = letter
        l2d[letter] = d_name
    return d2l, l2d


def sanitize_filename(name: str) -> str:
    """Replaces unsafe characters in method/country names for file saving."""
    return re.sub(r'[^\w\-_\. ]', '', name).strip().replace(' ', '_')


def parse_stacked_country_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Parses vertical sequential multi-election datasets from CSV files."""
    historical_elections = {}
    filename = file_path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    
    target_mandate_override_keywords = {
        "total seats", "total_seats", "gesamttotal", "totais mandatos", 
        "totais_mandatos", "total mandates", "total_mandates", "mandatos totais", 
        "mandatos_totais", "national_mandates", "national_party_caps", "override_mandates"
    }

    summary_district_keywords = {
        "total votes", "totais_votos", "totais votos", "sum votes", "gesamttotal_votos"
    }

    with open(file_path, "r", encoding="utf-8-sig") as f:   # FIX: utf-8-sig
        lines = f.readlines()
        
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line.startswith(','):
            idx += 1
            continue
            
        year_match = re.match(r'^(\d{4})', line)
        if year_match:
            year_str = year_match.group(1)
            idx += 1
            
            while idx < len(lines) and (not lines[idx].strip() or lines[idx].strip().startswith(',')):
                idx += 1
            if idx >= len(lines): break
            
            reader = csv.reader([lines[idx].strip()])
            header_parts = [h.strip() for h in next(reader)]
            
            district_col_idx = 0
            mandatos_idx = None
            totais_idx = None
            
            mandate_keywords = ["mandatos", "mandates", "seats", "mandatos_totais", "mandate", "sitze", "zuteilung", "anzahl_mandate", "mandat", "seat", "sitze_total"]
            total_keywords = ["totais", "total", "total_votes", "totais_votos", "sum", "stimmen_total", "votos_totais"]
            
            for i, h in enumerate(header_parts):
                # FIX: normalise header names
                h_clean = re.sub(r'[^a-z0-9]+', '_', h.lower()).strip('_')
                if h_clean in mandate_keywords:
                    mandatos_idx = i
                elif h_clean in total_keywords:
                    totais_idx = i

            if mandatos_idx is None:
                raise ValueError(f"❌ CRITICAL DATA ERROR: Dataset file '{filename}' (Year {year_str}) is missing a seats column.")

            parties_list = []
            party_indices = []
            for i, h in enumerate(header_parts):
                if i in (district_col_idx, mandatos_idx, totais_idx):
                    continue
                parties_list.append(h)
                party_indices.append(i)
            
            votes: Dict[str, Dict[str, int]] = {}
            district_caps: Dict[str, int] = {}
            total_votes_cast: Dict[str, int] = {}
            national_mandates_override = None 
            
            idx += 1
            while idx < len(lines):
                row_line = lines[idx].strip()
                if not row_line or row_line.startswith(',', 0, 2): break
                if re.match(r'^(\d{4})', row_line): break
                
                row_reader = csv.reader([row_line])
                row_parts = [r.strip() for r in next(row_reader)]
                
                while len(row_parts) < len(header_parts):
                    row_parts.append("0")
                    
                district = str(row_parts[district_col_idx])
                district_clean = district.lower().strip()
                
                if district_clean in target_mandate_override_keywords:
                    national_mandates_override = {}
                    for party, p_idx in zip(parties_list, party_indices):
                        val = row_parts[p_idx] if p_idx < len(row_parts) else "0"
                        national_mandates_override[party] = parse_int_safe(val)
                    idx += 1
                    continue

                if district_clean in summary_district_keywords:
                    idx += 1
                    continue
                
                seat_cap = parse_int_safe(row_parts[mandatos_idx])
                district_caps[district] = seat_cap
                
                votes[district] = {}
                for party, p_idx in zip(parties_list, party_indices):
                    val = row_parts[p_idx] if p_idx < len(row_parts) else "0"
                    votes[district][party] = parse_int_safe(val)
                
                if totais_idx is not None and totais_idx < len(row_parts) and row_parts[totais_idx]:
                    total_votes_cast[district] = parse_int_safe(row_parts[totais_idx])
                else:
                    total_votes_cast[district] = sum(votes[district].values())
                    
                idx += 1
                
            historical_elections[year_str] = {
                "parties_list": parties_list,
                "votes": votes,
                "district_caps": district_caps,
                "total_votes_cast": total_votes_cast,
                "has_total_column": (totais_idx is not None),
                "national_mandates": national_mandates_override
            }
        else:
            idx += 1
            
    return historical_elections