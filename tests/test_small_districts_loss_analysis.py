"""Check district eligibility, exact loss margins, and election-year spacing."""

import copy
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import small_districts_loss_analysis as analysis
from auxiliary.district_validation import apportion_mandates, read_elections


class SmallDistrictThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elections = read_elections(analysis.DEFAULT_SOURCE)
        cls.years, cls.districts, cls.rows = analysis.build_analysis(analysis.DEFAULT_SOURCE)

    def test_eligibility_uses_full_history_and_source_order(self):
        _, original_selection = analysis.select_districts(self.elections)
        self.assertEqual(original_selection, [
            "Açores", "Madeira", "Vila Real", "Bragança", "Castelo Branco",
            "Évora", "Beja", "Portalegre",
        ])
        elections = copy.deepcopy(self.elections)
        # A later recovery does not erase an earlier seat loss.
        elections["2019"]["mandates"]["Beja"] = 2
        elections["2025"]["mandates"]["Madeira"] = 7
        _, selected = analysis.select_districts(elections)
        self.assertNotIn("Beja", selected)
        self.assertNotIn("Madeira", selected)
        del elections["2015"]
        with self.assertRaisesRegex(ValueError, "include 2015"):
            analysis.select_districts(elections)

    def test_extra_filter_keeps_only_2025_margins_strictly_below_five_percent(self):
        self.assertEqual(self.districts, ["Castelo Branco", "Beja"])
        self.assertEqual(self.years, ["2015", "2019", "2022", "2024", "2025"])
        rows = [
            {"District": "A", "Year": "2015", "Minimum_voter_loss": 1, "Registered_voters": 10000},
            {"District": "A", "Year": "2025", "Minimum_voter_loss": 500, "Registered_voters": 10000},
            {"District": "B", "Year": "2025", "Minimum_voter_loss": 499, "Registered_voters": 10000},
            {"District": "C", "Year": "2025", "Minimum_voter_loss": 501, "Registered_voters": 10000},
            {"District": "D", "Year": "2025", "Minimum_voter_loss": 1, "Registered_voters": 10000},
        ]
        # D passes the margin test but is absent from the original selection.
        self.assertEqual(analysis.trim_districts(["A", "B", "C"], rows), ["B"])
        with self.assertRaisesRegex(ValueError, "include 2025"):
            analysis.trim_districts(["A"], rows[:1])
        with self.assertRaisesRegex(ValueError, "No eligible districts"):
            analysis.trim_districts(["A", "C"], rows)

    def test_beja_reproduces_verified_historical_minima(self):
        expected = {
            "2015": (9399, "Porto"), "2019": (5598, "Lisboa"),
            "2022": (2479, "Setúbal"), "2024": (1840, "Lisboa"),
            "2025": (962, "Braga"),
        }
        for row in self.rows:
            if row["District"] == "Beja":
                with self.subTest(year=row["Year"]):
                    self.assertEqual((row["Minimum_voter_loss"], row["Gaining_district"]), expected[row["Year"]])
                    self.assertAlmostEqual(row["Loss_pct"], 100 * expected[row["Year"]][0] / row["Registered_voters"])
                    self.assertEqual(row["District_label"], "Beja (3)")
                    self.assertEqual(row["Mandates_after"], 2)
        self.assertEqual(len(self.rows), len(self.districts) * len(self.years))

    def test_exact_tie_keeps_seat_until_one_more_voter_is_lost(self):
        voters = {"A": 114, "B": 114}
        baseline = apportion_mandates(voters)
        result = analysis.minimum_voter_loss(voters, "A", baseline)
        # At A=113, A's 113th quotient ties B's 114th (both 1),
        # and A keeps its seat as the smaller electorate.
        self.assertEqual(result["Minimum_voter_loss"], 2)
        self.assertEqual(result["Last_safe_electorate"], 113)
        self.assertEqual(result["Electorate_at_loss"], 112)
        self.assertEqual(result["Gaining_district"], "B")

    def test_combined_csv_keeps_both_tables_labels_order_and_numeric_percentages(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "small_districts_loss_analysis.csv"
            analysis.write_report(self.years, self.districts, self.rows, report)
            with report.open(encoding="utf-8-sig", newline="") as stream:
                sections = list(csv.reader(stream))
            self.assertTrue(sections[0][0].startswith("SUMMARY:"))
            separator = sections.index([])
            table = [dict(zip(sections[1], row)) for row in sections[2:separator]]
            self.assertEqual(len(table), len(self.districts))
            self.assertEqual(
                [row[f"District ({self.years[-1]} mandates)"] for row in table],
                [f"{district} ({self.elections[self.years[-1]]['mandates'][district]})" for district in self.districts],
            )
            beja = next(row for row in table if row[f"District ({self.years[-1]} mandates)"] == "Beja (3)")
            self.assertNotIn("After_losing_one", sections[1])
            headers, values = analysis.summary_table(self.years, self.districts, self.rows)
            self.assertEqual(headers, ["District (2025 mandates)", *self.years])
            self.assertTrue(all(len(row) == len(headers) for row in values))
            self.assertAlmostEqual(float(beja["2025_loss_pct"]), 100 * 962 / 118320, places=6)
            self.assertTrue(sections[separator + 1][0].startswith("YEARLY DETAILS:"))
            detail_header = sections[separator + 2]
            self.assertEqual(detail_header, list(analysis.DETAIL_FIELDS))
            self.assertNotIn("Mandates_after", detail_header)
            detail_rows = [dict(zip(detail_header, row)) for row in sections[separator + 3:]]
            self.assertEqual(len(detail_rows), len(self.districts) * len(self.years))
            beja_details = next(row for row in detail_rows if row["District"] == "Beja" and row["Year"] == "2025")
            self.assertEqual(beja_details["Minimum_voter_loss"], "962")
            self.assertEqual(beja_details["Gaining_district"], "Braga")
            self.assertEqual(report.read_bytes()[:3], b"\xef\xbb\xbf")

    def test_graph_uses_equal_election_gaps_and_current_mandate_labels(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.png"
            # Keep the generated figure available briefly to inspect its axes.
            with patch.object(plt, "close"):
                analysis.plot_margins(self.years, self.districts, self.rows, graph)
            fig = plt.gcf()
            try:
                ax = fig.axes[0]
                self.assertEqual(ax.get_xlabel(), "Election Year")
                self.assertEqual(ax.get_ylim(), (0, 10))
                self.assertEqual(
                    [tick for tick in ax.get_yticks() if 0 <= tick <= 10], list(range(11))
                )
                self.assertTrue(all("n - 1" not in text.get_text() for text in fig.texts))
                self.assertEqual([tick.get_text() for tick in ax.get_xticklabels()], self.years)
                for line in ax.lines:
                    self.assertEqual(list(line.get_xdata()), [0, 1, 2, 3, 4])
                self.assertEqual([line.get_label() for line in ax.lines], [
                    f"{district} ({self.elections[self.years[-1]]['mandates'][district]})"
                    for district in self.districts
                ])
                self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            finally:
                plt.close(fig)

    def test_alternative_graph_spaces_elections_by_exact_elapsed_days(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "time_graph.png"
            with patch.object(plt, "close"):
                analysis.plot_margins(self.years, self.districts, self.rows, graph, time_proportional=True)
            fig = plt.gcf()
            try:
                ax = fig.axes[0]
                self.assertEqual(ax.get_xlabel(), "Election Date")
                self.assertEqual([tick.get_text() for tick in ax.get_xticklabels()], [
                    "04/10\n2015", "06/10\n2019", "30/01\n2022", "10/03\n2024", "18/05\n2025",
                ])
                self.assertEqual(ax.get_ylim(), (0, 10))
                for line in ax.lines:
                    positions = list(line.get_xdata(orig=False))
                    self.assertEqual([b - a for a, b in zip(positions, positions[1:])],
                                     [1463, 847, 770, 434])
                    expected = [row["Loss_pct"] for row in self.rows
                                if row["District_label"] == line.get_label()]
                    self.assertEqual(list(line.get_ydata()), expected)
                self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            finally:
                plt.close(fig)

    def test_run_creates_both_graphs_and_missing_dates_preserve_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.csv"
            graph = Path(directory) / "graph.png"
            time_graph = Path(directory) / "time_graph.png"
            args = ["--csv", str(report), "--graph", str(graph), "--time-graph", str(time_graph)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(analysis.main(args), 0)
            for output in (graph, time_graph):
                self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            previous = {path: path.read_bytes() for path in (report, graph, time_graph)}
            error = io.StringIO()
            with patch.dict(analysis.ELECTION_DATES, {}, clear=True), \
                    contextlib.redirect_stderr(error):
                self.assertEqual(analysis.main(args), 1)
            self.assertIn("Add verified election dates", error.getvalue())
            self.assertEqual(previous, {path: path.read_bytes() for path in previous})
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(analysis.main([*args, "--time-graph", str(graph)]), 1)
            self.assertEqual(previous, {path: path.read_bytes() for path in previous})


if __name__ == "__main__":
    unittest.main()
