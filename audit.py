import glob
import os
from typing import Any, Dict, Tuple

from baseline_engines import get_national_party_caps
from config import GREEN, RED, RESET, SUPPORTED_REGIONS
from data_parser import parse_stacked_country_file


def audit_datasets() -> Tuple[Dict[str, Dict[str, Any]], int, int]:
    """
    Scans for data_*.csv files, parses them, validates structural seat caps
    and vote sums upfront, returning parsed dataset cache and global counters.
    """
    input_files = sorted(glob.glob("data_*.csv"))
    if not input_files:
        print(f"{RED}Error: No country datasets found matching pattern 'data_*.csv'.{RESET}")
        raise FileNotFoundError("No matching input CSV files found.")

    all_datasets = {}
    validation_errors = []
    global_max_possible_coverage = 0
    historical_election_count = 0

    print("🔍 Launching Upfront Dataset Integrity Audits...")

    for file_path in input_files:
        filename = os.path.basename(file_path)
        country_name = filename.replace("data_", "").replace(".csv", "").strip().title()

        if country_name.lower() not in SUPPORTED_REGIONS:
            print("\n" + "!" * 80)
            print(f"❌ {RED}PROTECTION STOP: UNSUPPORTED REGION DETECTED ('{country_name}'){RESET}")
            print("!" * 80 + "\n")
            raise ValueError(f"Aborted: Region '{country_name}' is missing configured system rules.")

        elections_archive = parse_stacked_country_file(file_path)
        all_datasets[file_path] = {
            "country_name": country_name,
            "filename": filename,
            "archive": elections_archive
        }

        for year, dataset in elections_archive.items():
            historical_election_count += 1
            votes = dataset["votes"]
            district_caps = dataset["district_caps"]
            total_votes_cast = dataset["total_votes_cast"]
            parties_list = dataset["parties_list"]
            has_total_column = dataset["has_total_column"]
            num_districts = len(votes)

            global_max_possible_coverage += (num_districts * len(parties_list))

            if has_total_column:
                for d in votes.keys():
                    sum_listed_parties = sum(votes[d].values())
                    if total_votes_cast[d] < sum_listed_parties:
                        validation_errors.append(
                            f"[{country_name.upper()} - {year}] District '{d}' total raw votes count ({total_votes_cast[d]:,}) is smaller than listed party subset sum ({sum_listed_parties:,})."
                        )

            total_mandates_sum = sum(district_caps.values())
            if country_name.lower() == "portugal" and total_mandates_sum != 226:
                validation_errors.append(
                    f"[{country_name.upper()} - {year}] Portugal context failure: Total structural seats equals {total_mandates_sum} instead of 226 bounds."
                )

            national_party_votes = {p: sum(votes[d][p] for d in votes.keys()) for p in parties_list}
            party_caps = get_national_party_caps(
                country_name, national_party_votes, total_mandates_sum, dataset.get("national_mandates")
            )

            if sum(party_caps.values()) != total_mandates_sum:
                validation_errors.append(
                    f"[{country_name.upper()} - {year}] National targets matching error: National party mandates sum to {sum(party_caps.values())} while structure bounds freeze at {total_mandates_sum}."
                )

    if validation_errors:
        print(f"\n{RED}❌ DATA VALIDATION FAILED — {len(validation_errors)} critical database issue(s) identified:{RESET}")
        for err in validation_errors:
            print(f"   - {err}")
        raise ValueError("Electoral pipeline execution aborted.")

    print(f"{GREEN}✅ All datasets passed upfront integrity passes. Proceeding to compilation pipeline.{RESET}\n")

    return all_datasets, historical_election_count, global_max_possible_coverage