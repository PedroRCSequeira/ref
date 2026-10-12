# Electoral map export

Run the Python file normally from your IDE, or use:

```powershell
python export_site_map_metrics.py
```

No options or extra input are needed. Each run discovers all election years,
validates the data, and writes `outputs/mapa-teste-metricas-real.json`. It reports
success or a specific error in the console. Refresh it after adding an election
block to the CSV or changing the proposal's registry settings.

The source is `data_Portugal.csv` in the main repository folder, alongside the
exporter. Move Portugal there when it is the active dataset. The exporter reports
an error if that file is missing; it does not read datasets in `z_data_storage`.
Paths are relative to the script, so launching it from another directory also
works. The script uses only the standard library, preserves source data and
existing reports, and disables Python bytecode writes automatically.

## Calculations and input format

- The input contains the **18 mainland districts, Açores and Madeira**, with the
  relevant electoral lists, district mandates, and `Totais` in every year block.
  All calculations, including national party targets, use only these 20
  constituencies. Other constituencies, including `Europa` and `Fora da Europa`,
  are rejected before any seat allocation. The current dataset totals 226 seats;
  no overseas votes or seats are added.
- `current` calls `baseline_engines.dhondt_apportion` separately for each district.
  Wasted votes are votes for lists with no seat **in that district**.
- `proposal` uses **2-Speed Danish Pool**, registry entry `2-Speed`, calling
  `custom_methods.allocate_two_speed_pool_method` with its registry arguments.
  Round 1 has a single per-party-per-district cap of **4**, regardless of district
  size. Round 2 removes that cap while retaining district capacities and national
  party targets. Metadata records the registry parameters used.
- National party targets use
  `baseline_engines.get_national_party_caps("portugal", ...)`, including a source
  mandate override when present. Monte Carlo and reporting toggles do not affect
  this historical export.
- Proposal wasted votes are votes for lists with no seat **anywhere within the
  20 constituencies**, based on the final allocation. Represented parties are
  counted **locally** in both models. Each coalition counts as one electoral list
  and its column name remains intact.
- **`Totais` contains all valid votes**, including votes for omitted electoral
  lists. It is the denominator for wasted-vote percentages, rounded to six
  decimal places. Blank/invalid ballots must not be included in `Totais`.

The agreed input format lists every party relevant to seat allocation. Omitted
lists are assumed to win no seats in either model. Their combined valid votes
(`Totais` minus the listed vote sum) are counted as wasted in both models. The
script applies this automatically and records it in the JSON and console output.
It does not invent an aggregate party or include omitted lists in represented
party counts.

## Validation on every run

The exporter automatically checks source years, duplicate/empty/malformed rows,
required vote and seat counts, all 20 constituencies, party keys, district seat
sums, proposal national targets, and every output combination. In particular,
**`Totais` must be at least the sum of the listed party votes** in each district;
otherwise the run stops with the year, district, and conflicting counts.

Percentages must be finite numbers in 0–100. Represented-list counts must be
integers within the district capacity and number of listed parties. Missing
metrics are never filled with zero. The exporter replaces the destination only
after validation and complete serialization. On failure, it reports the error,
exits with status 1, and preserves the previous output.

These automatic consistency checks validate the actual input and output. The
separate development test suite verifies the exporter's behavior with synthetic
and malformed examples; it is not run during each export. Run it separately if
needed:

```powershell
python -B -m unittest discover -s tests -p test_export_site_map_metrics.py
```

## Website contract

Values use `values[model][year][region][metric]`, with exactly
`wasted_votes_pct` and `represented_parties_count`. Region ids, display names,
and geography codes come from the reference JSON. District names are converted
to lowercase, accents removed, and spaces converted to hyphens: `Açores` becomes
`acores`, `Évora` becomes `evora`, and `Castelo Branco` becomes `castelo-branco`.
The islands' full autonomous-region names are also recognized. The reference
must retain all 20 expected ids.

The example JSON's years and fictitious values are never used. The output retains
schema version 2 and palette/unit metadata, sets `demo` to false, and omits
`effective_threshold_pct` entirely.
