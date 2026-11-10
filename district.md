# District mandate analysis

Explore how registered electorates determine Portugal's district mandates, how
alternative distributions change party representation, and how close small
districts are to losing a seat.

VS Code groups the following files beneath this document using the workspace's
Explorer file nesting settings. The grouping is visual; files remain in the
repository root and run from their existing locations.

| Script | Purpose | Output |
| --- | --- | --- |
| `check_voters_mandates.py` | Verify the stored district mandates against a 226-seat d'Hondt allocation using `Inscritos` or `Eleitores`. | Console matches or district mismatches. |
| `dist_mandatos.py` | Compare one- and two-seat initial bonuses, Sainte-Lague, and equalized districts; list cumulative seat losses as the total falls from 225 to 180. | Console tables and `dist_mandatos_excel.csv`. |
| `small_districts_loss_analysis.py` | Measure the minimum electorate loss that would cost a small district one mandate, for every election since 2015. | Console table, `small_districts_loss_analysis.csv`, and a graph in `portugal_trends`. |

Run a script from the repository root:

```powershell
python check_voters_mandates.py
python dist_mandatos.py
python small_districts_loss_analysis.py
```

All analyses read `data_Portugal.csv` and exclude the four overseas mandates.
Party seats in every district use d'Hondt. Initial bonuses are added to a fresh
allocation of the remaining mandates, starting at divisor 1.

The small-district analysis selects districts with at most six mandates in the
latest election and no decrease between any supplied elections since 2015.
Its percentage is the minimum integer voter loss divided by that year's original
electorate. Each calculation holds all other electorates and the 226-seat total
fixed, and verifies the cutoff by recalculating the allocation on both sides.

The combined CSV contains two labelled sections: the district-by-year percentage
summary, followed by yearly details with exact voter losses, cutoff electorates,
and the district receiving the lost mandate. District labels show their latest
mandates, and district order follows the source CSV.

The graph is saved to
`portugal_trends/TREND_Small_District_Seat_Loss_Margins.png` and uses equally spaced
election years. Analysis tests live in `tests/test_check_voters_mandates.py`,
`tests/test_dist_mandatos.py`, and `tests/test_small_districts_loss_analysis.py`.
