# Repository guidance

## Project and entry points

This is a Python electoral-analysis project for Portugal and Zurich. Prefer the
existing parsers and allocation engines when extending an analysis.

| File | Role |
| --- | --- |
| `data_parser.py` | Read stacked CSV election blocks and distinguish party votes from metadata. |
| `baseline_engines.py`, `custom_methods.py` | Seat allocation algorithms and alternative methods. |
| `audit.py`, `runner.py`, `monte_carlo.py` | Input audits, historical elections, and simulations. |
| `main.py`, `reporting.py`, `visuals_export.py` | Full pipeline, reports, and plots; run settings live in `config.py`. |
| `check_voters_mandates.py` | Validate Portugal's district mandates against registered-electorate d'Hondt. |
| `dist_mandatos.py` | Compare alternative district distributions and their party totals. |
| `small_districts_loss_analysis.py` | Calculate small districts' margins before losing one mandate. |
| `export_site_map_metrics.py` | Generate the electoral map JSON; see `README_site_map_metrics.md`. |

Read `district.md` for district-analysis commands and report definitions.
VS Code groups related files using `.vscode/settings.json`; these are visual
groups, not directories. Preserve that organization when adding related files.

## Source data and calculation conventions

- Source datasets include `data_Portugal.csv` and
  `z_data_storage/data_zurich.csv`. Preserve source data unless the task calls
  for editing it; report suspected errors instead of silently correcting them.
- Discover election years from the CSV. Preserve district order from the source
  in tables, CSV reports, and graph legends.
- `Inscritos` and `Eleitores` are registered-electorate metadata, never parties
  or votes cast. `Mandatos` stores district seats; `Totais` stores valid votes
  and can include votes for lists omitted from the supplied party columns.
- Portugal's domestic analyses allocate 226 mandates across 20 constituencies,
  excluding the four overseas seats. Do not apply this seat total to Zurich.
- Party totals in district-distribution analyses always use d'Hondt separately
  within each district. Keep coalition names as supplied; do not invent votes
  for omitted parties or replace local allocation with national allocation.
- Initial one- or two-seat bonuses are added to a fresh d'Hondt allocation of
  the remaining seats, starting at divisor 1. Bonuses do not affect divisors.
- Standard Sainte-Lague uses divisors 1, 3, 5, and so on. An equalized 226-seat
  distribution uses fourteen districts with 11 seats and six with 12.
- Threshold percentages use the minimum integer electorate loss divided by the
  original electorate, with all other electorates and 226 seats fixed. Verify
  that the seat is lost at that change and retained with one voter less change.
  Use exact arithmetic where threshold or quotient ties matter, and state the
  tie rule used; preserve existing engine behavior outside the requested scope.

## Generated files and Git

- Generated reports, exports, plots, caches, and local environments belong in
  `.gitignore`. This includes generated CSV/XLSX reports, JSON exports, PNG
  graphs, `__pycache__`, `venv`, and `.venv`.
- When introducing a generated output, add its filename pattern or output
  directory to `.gitignore`. Keep the generator and its source inputs tracked.
- Use targeted rules. Do not blanket-ignore all CSV, JSON, or image files:
  source datasets and reference fixtures such as `references/` must remain
  available in Git.
- If an artifact is already tracked, remove only the relevant generated paths
  from the index with `git rm --cached` (and `-r` for directories), preserving
  local files. Do not force-add generated files or rewrite repository history
  to remove old copies unless the user explicitly requests it.
- Reports must be reproducible by running their scripts. Users may delete local
  generated files; their absence must not be treated as missing source data.

## Output and validation

- Use UTF-8 for text and UTF-8 with BOM for CSV reports intended for Excel.
  Keep console tables aligned and identify scenario baselines and units.
- Plot election years at equally spaced categorical positions, rather than
  elapsed-time coordinates. Follow the style in `portugal_trends` and its
  generators. Label districts with their latest mandate count where relevant.
- Make focused changes and preserve unrelated working-tree edits. Prefer
  existing dependencies and avoid running long simulations for small changes.
- Run relevant tests when changing calculations or behavior. The full suite is
  `python -B -m unittest discover -s tests`; `-B` avoids bytecode generation.
- After Portugal electorate data or mandate-validation changes, run
  `python -B check_voters_mandates.py`. Check that allocations sum to their
  targets and that metadata is excluded from party votes.
- For Git hygiene changes, use `git check-ignore` and `git ls-files` to verify
  generated files are ignored and untracked, and source inputs remain tracked.
