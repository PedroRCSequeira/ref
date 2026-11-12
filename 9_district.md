# District mandate analysis

Explore how registered electorates determine Portugal's district mandates, how
alternative distributions change party representation, and how close small
districts are to losing a seat.

VS Code groups the following files beneath this document using the workspace's
Explorer file nesting settings. The grouping is visual; files remain in the
repository root and run from their existing locations.

| Script | Purpose | Output |
| --- | --- | --- |
| `dist_mandatos.py` | Compare one- and two-seat initial bonuses, Sainte-Lague, and equalized districts; list cumulative seat losses as the total falls from 225 to 180. | Console tables and `dist_mandatos_excel.csv`. |
| `small_districts_loss_analysis.py` | Measure the minimum electorate loss that would cost a small district one mandate, for every election since 2015. | Console table, `small_districts_loss_analysis.csv`, and two graphs (equal election spacing and proportional date spacing). |
| `analise_circ_compensa.py` | Find the minimum compensatory national circle that reproduces the 226-seat national d'Hondt party totals. | Console matrices, `analise_circ_compensa.csv`, and `TREND_Compensatory_Circle_Size.png`. |

Run a script from the repository root:

```powershell
python dist_mandatos.py
python small_districts_loss_analysis.py
python analise_circ_compensa.py
```

All three analyses automatically validate `data_Portugal.csv` before starting any
calculations or writing output. The shared check compares every year's stored
`Mandatos` with a 226-seat d'Hondt allocation using `Inscritos` or `Eleitores`.
If any district differs, the run exits with an error identifying the year,
district, stored mandates, calculated mandates, and electorate. Existing reports
and graphs remain untouched. There is no separate checker to run.

The shared implementation is `auxiliary/district_validation.py`, an internal
module imported by all three scripts. It also supplies the common electorate reader
and exact d'Hondt allocation used for threshold calculations. Keep auxiliary
helpers in `auxiliary/` and runnable district analyses in this visual group.

All analyses exclude the four overseas mandates.
Party seats in every district use d'Hondt. Initial bonuses are added to a fresh
allocation of the remaining mandates, starting at divisor 1.

In the ordered-loss table, "Change" is the district's cumulative loss from the
226-seat baseline. "Lost a party?" shows the supplied party name only when that
single step reduces its district representation from one mandate to zero; it
shows `-` otherwise. The calculation compares district d'Hondt allocations
immediately before and after each step, using the same votes and tie rules.
The CSV includes the same information in `Lost_party` for removal-order rows.

The small-district analysis selects districts with at most six mandates in the
latest election and no decrease between any supplied elections since 2015.
An extra filter then keeps only those districts whose margin in 2025 is strictly
below 5%, retaining all election years for the remaining districts. This filter
and the graph's 0–10% range with 1% tick intervals are configured separately near
the top of `small_districts_loss_analysis.py`; the original selection rule remains
in `select_districts`.
Its percentage is the minimum integer voter loss divided by that year's original
electorate. Each calculation holds all other electorates and the 226-seat total
fixed, and verifies the cutoff by recalculating the allocation on both sides.

The combined CSV contains two labelled sections: the district-by-year percentage
summary, followed by yearly details with exact voter losses, cutoff electorates,
and the district receiving the lost mandate. District labels show their latest
mandates, and district order follows the source CSV.

Every run creates both graphs in the repository root, grouped under `9_district.md`
in VS Code:

- `TREND_Small_District_Seat_Loss_Margins.png` uses equally spaced election years.
- `TREND_Small_District_Seat_Loss_Margins_Time_Spaced.png` uses actual election dates,
  with horizontal spacing proportional to elapsed days.

Use `--graph` and `--time-graph` to override their respective output paths.
Both graphs clip values above 10%; the console and CSV retain the full percentages.

The script stores the exact dates in `ELECTION_DATES`, verified against the
[SGMAI election history](https://www.sg.mai.gov.pt/pt/AdministracaoEleitoral/EleicoesReferendos/HistoricoEleicoes/Pages/default.aspx):
4 October 2015, 6 October 2019, 30 January 2022, 10 March 2024, and 18 May 2025.
Election years still come from the CSV. If a new analysed year has no saved date,
the script aborts before writing any outputs and requests a verified date.

Analysis tests live in `tests/test_district_validation.py`,
`tests/test_dist_mandatos.py`, `tests/test_small_districts_loss_analysis.py`,
and `tests/test_analise_circ_compensa.py`.
Run `python -B -m unittest discover -s tests` for the development tests; these
tests are separate from the automatic input check performed on every analysis.

## Minimum compensatory national circle

`analise_circ_compensa.py` analyses every election year discovered in the source.
The national target is a fresh 226-seat d'Hondt allocation on the sum of each
supplied party's domestic votes. Coalition names stay as supplied, and no votes
are invented for lists omitted from the party columns or inferred from `Totais`.

The search starts with a compensatory circle of zero mandates. At each step it
sums the positive differences between parties' district totals and their fixed
national targets, then **adds** that excess to the circle size. The remaining
district mandates (226 minus circle size) are freshly apportioned by d'Hondt
using `Inscritos`/`Eleitores`, followed by party d'Hondt within each district.
Stop when no party exceeds its national target. Each party receives exactly its
shortfall in the circle; allocating the circle independently by ordinary
d'Hondt would not in general reproduce the target.

Exact quotient ties favor the smaller electorate or vote count; equal counts
then favor alphabetical name. These are the existing district-analysis rules.
Fixed tie rules make both d'Hondt allocations nested when seats are removed.
An excess of E seats requires at least E further district-seat removals, so the
jumps cannot skip a feasible size. The script also checks that size C-1 still
has an excess whenever the result C is positive. This is the minimum under
electorate-based d'Hondt redistribution, with no guaranteed district minimum;
a district may reach zero seats. The overall total always remains 226.

Each election's console and CSV report contains:

- A single-line heading such as `2015 - Minimum compensatory circle: 23 mandates`.
- The minimum-size matrix followed by a fixed-size matrix, defaulting to a
  30-mandate circle and 196 district mandates. Override this with `--fixed-size`.
- A source-ordered district-by-party matrix with `original(change)` cells
  and district totals. For example, `6(-1)` means six original seats with one
  lost, leaving five; unchanged values have no parentheses. `District subtotal`
  shows local party totals and their changes; the separate `Compensatory circle`
  row shows plain final seat counts (for example, `7`, with no signs or
  parentheses); the `Total` row compares original totals with
  final totals including compensation using the same signed-change notation.
  Original plus change exactly matches each national target in the minimum
  scenario. Do not add the subtotal to district rows.

For the fixed scenario, first redistribute 226 minus the chosen circle size
by electorate d'Hondt, then allocate party seats within each district. Award
the circle seats one at a time using national party votes divided by
`district party seats + compensatory seats already awarded + 1`, with the same
exact tie rule. This continues national d'Hondt while retaining every district
seat; it is not an independent fresh d'Hondt allocation of just the circle.
When the circle is sufficient it exactly reproduces the national targets.
When district overhangs make that impossible, all circle seats are still
awarded and the final total stays 226. The `Total` row always shows the actual
district-plus-circle allocation.

If the fixed scenario deviates from the national target, append a purple
`Difference vs national target` row directly below `Total`, using the same party
columns. A positive number means extra seats relative to the national target;
a negative number means a shortfall. The differences sum to zero. Omit this row
when all party totals match. It compares with the national target, whereas
parentheses elsewhere compare with the original district allocation.

Red backgrounds highlight district-party cells that go from positive to zero;
yellow backgrounds highlight partial seat losses with representation retained.
Unchanged cells, district totals, subtotals, and national totals are uncolored;
the entire deviation row uses a purple background when present.
The matrix replaces the separate district and party loss sections. Losing local
representation does not mean losing national representation. Colors appear in
an interactive terminal, including VS Code's integrated terminal. Use
`--color always` to force ANSI color or `--color never` to disable it. Automatic
color respects `NO_COLOR` and is disabled for redirected output. The UTF-8 BOM
CSV contains the same matrices without ANSI escapes or formatting. Original
seats and their changes retain the loss information in plain text.

The PNG graph uses equally spaced election years and labels each minimum in
mandates. All outputs live beside the script and are visually nested under
this document in VS Code. Override paths with `--csv` (alias `--output`) and
`--graph`, or pass an alternative source CSV as the positional argument.
Generated CSV and PNG outputs are ignored by Git. Invalid source data aborts
before analysis or writing either output, preserving previous reports/graphs.
