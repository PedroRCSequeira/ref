"""Check excess jumps against an independent exhaustive seat-sequence search."""

import contextlib
import csv
import io
import tempfile
import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import analise_circ_compensa as analysis


def reference_order(weights, total):
    # Sort all possible quotients instead of using the production allocator.
    quotients = [(-Fraction(weight, divisor), weight, name)
                 for name, weight in weights.items() if weight > 0
                 for divisor in range(1, total + 1)]
    return [name for _, _, name in sorted(quotients)[:total]]


def exhaustive_minimum(votes, voters, total):
    national = {p: sum(row[p] for row in votes.values()) for p in next(iter(votes.values()))}
    targets = Counter(reference_order(national, total))
    district_order = reference_order(voters, total)
    local_orders = {d: reference_order(row, total) for d, row in votes.items()}
    for size in range(total + 1):
        caps = Counter(district_order[:total - size])
        totals = Counter()
        for district in votes:
            totals.update(local_orders[district][:caps[district]])
        if all(totals[p] <= targets[p] for p in national):
            return size
    raise AssertionError("The all-compensatory allocation must be feasible.")


class CompensatoryAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = analysis.build_analysis()
        cls.elections, _ = analysis.load_elections(analysis.DEFAULT_SOURCE)
        cls.electorates = analysis.load_validated_elections()

    def multi_jump_case(self):
        # The high-electorate district has very few actual party votes.
        # Party and district source orders deliberately differ from sorting.
        votes = {
            "Z District": {"B": 0, "A": 10, "Zero": 0},
            "A District": {"B": 100, "A": 0, "Zero": 0},
        }
        voters = {"Z District": 9, "A District": 1}
        caps = {"Z District": 9, "A District": 1}
        return analysis.analyse_election(votes, voters, caps, ["B", "A", "Zero"], total=10)

    def test_excess_jumps_accumulate_and_can_empty_a_district(self):
        data = self.multi_jump_case()
        self.assertEqual(data["steps"], [
            {"size": 0, "excess": 8}, {"size": 8, "excess": 1}, {"size": 9, "excess": 0},
        ])
        self.assertEqual(data["size"], 9)
        self.assertEqual(data["caps"], {"Z District": 1, "A District": 0})
        self.assertEqual(data["targets"], {"B": 9, "A": 1, "Zero": 0})
        self.assertEqual(data["compensatory"], {"B": 9, "A": 0, "Zero": 0})
        self.assertGreater(data["previous_excess"], 0)

    def test_zero_circle_and_all_compensatory_boundaries(self):
        votes = {"D": {"Only": 100, "Zero": 0}}
        data = analysis.analyse_election(votes, {"D": 1}, {"D": 5}, ["Only", "Zero"], total=5)
        self.assertEqual(data["size"], 0)
        self.assertEqual(data["steps"], [{"size": 0, "excess": 0}])
        self.assertEqual(sum(data["compensatory"].values()), 0)
        self.assertIsNone(data["previous_excess"])
        votes = {"D1": {"A": 1, "B": 0}, "D2": {"A": 0, "B": 100}}
        data = analysis.analyse_election(votes, {"D1": 9, "D2": 1}, {"D1": 1, "D2": 0}, ["A", "B"], total=1)
        self.assertEqual(data["size"], 1)
        self.assertEqual(data["caps"], {"D1": 0, "D2": 0})
        self.assertEqual(data["compensatory"], {"A": 0, "B": 1})

    def test_every_year_matches_independent_exhaustive_search(self):
        for year, data in self.results.items():
            with self.subTest(year=year):
                self.assertEqual(data["size"], exhaustive_minimum(
                    self.elections[year]["votes"], self.electorates[year]["voters"], 226,
                ))
                self.assertEqual(data["steps"][-1]["excess"], 0)
                for current, following in zip(data["steps"], data["steps"][1:]):
                    self.assertEqual(following["size"], current["size"] + current["excess"])

    def test_each_matrix_and_compensatory_total_matches_its_target(self):
        for year, data in self.results.items():
            with self.subTest(year=year):
                self.assertEqual(list(data["original"]), list(self.elections[year]["votes"]))
                self.assertEqual(data["parties"], self.elections[year]["parties_list"])
                self.assertTrue({"Eleitores", "Inscritos", "Totais", "Mandatos"}.isdisjoint(data["parties"]))
                self.assertEqual(sum(data["compensatory"].values()), data["size"])
                self.assertEqual(sum(data["caps"].values()), 226 - data["size"])
                national_votes = {p: sum(row[p] for row in self.elections[year]["votes"].values())
                                  for p in data["parties"]}
                reference_targets = Counter(reference_order(national_votes, 226))
                for party in data["parties"]:
                    original = sum(row[party] for row in data["original"].values())
                    remaining = sum(row[party] for row in data["remaining"].values())
                    self.assertEqual(data["original_totals"][party], original)
                    self.assertEqual(remaining + data["compensatory"][party], reference_targets[party])
                for district in data["caps"]:
                    self.assertEqual(sum(data["remaining"][district].values()), data["caps"][district])
                    original_reference = Counter(reference_order(
                        self.elections[year]["votes"][district], data["current_caps"][district],
                    ))
                    for party in data["parties"]:
                        self.assertEqual(data["original"][district][party], original_reference[party])

    def test_ties_are_exact_and_follow_existing_district_analysis_rule(self):
        # 10 and 100/10 tie exactly; the smaller vote count gets the seat.
        seats, _ = analysis.allocate_seats({"Large": 100, "Small": 10}, 10)
        self.assertEqual(seats, {"Large": 9, "Small": 1})
        self.assertEqual(analysis.allocate_seats({"Z": 1, "A": 1}, 1)[0], {"A": 1, "Z": 0})

    def test_source_order_and_plain_compensatory_counts(self):
        data = self.multi_jump_case()
        headers, rows, highlights = analysis.matrix_table(data)
        self.assertEqual(headers, ["District", "B", "A", "Zero", "Mandatos"])
        self.assertEqual(rows[0], ["Z District", "0", "9(-8)", "0", "9(-8)"])
        self.assertEqual(rows[1], ["A District", "1(-1)", "0", "0", "1(-1)"])
        self.assertEqual(rows[-3], ["District subtotal", "1(-1)", "9(-8)", "0", "10(-9)"])
        self.assertEqual(rows[-2], ["Compensatory circle", "9", "0", "0", "9"])
        self.assertEqual(rows[-1], ["TOTAL (national target)", "1(+8)", "9(-8)", "0", "10"])
        self.assertEqual(highlights, {(0, 2): analysis.YELLOW_BACKGROUND, (1, 1): analysis.RED_BACKGROUND})

    def test_district_loss_backgrounds_distinguish_complete_and_partial_losses(self):
        data = self.multi_jump_case()
        headers, rows, highlights = analysis.matrix_table(data)
        colored, plain = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(colored):
            analysis.print_table(headers, rows, highlights=highlights, color=True)
        with contextlib.redirect_stdout(plain):
            analysis.print_table(headers, rows, highlights=highlights, color=False)
        text = colored.getvalue()
        self.assertEqual(text.count(analysis.RED_BACKGROUND), 1)
        self.assertEqual(text.count(analysis.YELLOW_BACKGROUND), 1)
        self.assertIn(analysis.RED_BACKGROUND + "1(-1)", text)
        self.assertIn(analysis.YELLOW_BACKGROUND + "9(-8)", text)
        self.assertEqual(text.replace(analysis.RED_BACKGROUND, "").replace(analysis.YELLOW_BACKGROUND, "").replace(analysis.RESET_COLOR, ""), plain.getvalue())

    def test_multiple_excluded_parties_keep_source_column_order(self):
        votes = {"D1": {"Z": 1, "A": 1, "R": 1}, "D2": {"Z": 0, "A": 0, "R": 100}}
        data = analysis.analyse_election(votes, {"D1": 3, "D2": 2},
                                        {"D1": 3, "D2": 2}, ["Z", "A", "R"], total=5)
        headers, rows, highlights = analysis.matrix_table(data)
        self.assertEqual(headers, ["District", "Z", "A", "R", "Mandatos"])
        self.assertEqual(rows[0], ["D1", "1(-1)", "1(-1)", "1(-1)", "3(-3)"])
        self.assertEqual(rows[1], ["D2", "0", "0", "2(-2)", "2(-2)"])
        self.assertEqual(highlights, {cell: analysis.RED_BACKGROUND
                                     for cell in ((0, 1), (0, 2), (0, 3), (1, 3))})

    def test_long_loss_lists_wrap_without_losing_information(self):
        losses = "; ".join(f"District {i} (-1)" for i in range(12))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            analysis.print_table(["Party", "District losses", "Lost representation in"],
                                 [["A", losses, "-"], ["B", "-", "-"]])
        lines = output.getvalue().splitlines()
        self.assertTrue(all(len(line) <= 95 for line in lines))
        self.assertGreater(len(lines), 3)
        reconstructed = " ".join(" ".join(line[7:67].split()) for line in lines[1:-1])
        self.assertEqual(reconstructed, losses)

    def test_cli_csv_and_graph_are_complete_and_source_is_unchanged(self):
        original = analysis.DEFAULT_SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            report, graph = Path(directory) / "report.csv", Path(directory) / "trend.png"
            messages = io.StringIO()
            with contextlib.redirect_stdout(messages):
                status = analysis.main(["--csv", str(report), "--graph", str(graph), "--color", "always"])
            self.assertEqual(status, 0)
            self.assertTrue(report.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertTrue(graph.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn(analysis.RED_BACKGROUND, messages.getvalue())
            self.assertIn(analysis.YELLOW_BACKGROUND, messages.getvalue())
            report_text = report.read_text(encoding="utf-8-sig")
            self.assertNotIn("\033", report_text)
            self.assertNotIn("Party district-seat losses", report_text)
            self.assertNotIn("Party district-seat losses", messages.getvalue())
            for removed in ("Districts losing mandates", "District mandates", "Final national mandates", "final national total"):
                self.assertNotIn(removed, report_text)
                self.assertNotIn(removed, messages.getvalue())
            self.assertNotIn("(0)", report_text)
            with report.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            for year, data in self.results.items():
                start = rows.index(["Year", year])
                self.assertEqual(rows[start + 1], ["Minimum compensatory mandates", str(data["size"])])
                next_year = next((i for i in range(start + 1, len(rows)) if rows[i][:1] == ["Year"]), len(rows))
                block = rows[start:next_year]
                headers, matrix, _ = analysis.matrix_table(data)
                matrix_start = block.index(headers)
                self.assertEqual(block[matrix_start + 1:matrix_start + 1 + len(matrix)], matrix)
                circle = next(row for row in block if row[:1] == ["Compensatory circle"])
                self.assertEqual(circle[1:], [str(data["compensatory"][p]) for p in data["parties"]] + [str(data["size"])])
                self.assertIn(f"\n{year}\n", messages.getvalue())
            self.assertIn("A\u00e7ores", report.read_text(encoding="utf-8-sig"))
        self.assertEqual(analysis.DEFAULT_SOURCE.read_bytes(), original)

    def test_invalid_year_preserves_both_outputs_and_stops_before_analysis(self):
        original = analysis.DEFAULT_SOURCE.read_text(encoding="utf-8-sig")
        corruptions = [
            original.replace(",5,88817", ",6,88817", 1),
            original.replace(",3,72041,118320", ",3,72041,117358"),
            original.replace("A\u00e7ores,37720,", "A\u00e7ores,invalid,", 1),
        ]
        for text in corruptions:
            with self.subTest(corruption=text[:100]), tempfile.TemporaryDirectory() as directory:
                self.assertNotEqual(text, original)
                source = Path(directory) / "source.csv"
                report, graph = Path(directory) / "report.csv", Path(directory) / "graph.png"
                source.write_text(text, encoding="utf-8")
                report.write_bytes(b"old report")
                graph.write_bytes(b"old graph")
                with patch.object(analysis, "analyse_election") as calculate, \
                        patch.object(analysis, "plot_sizes") as plot, \
                        contextlib.redirect_stderr(io.StringIO()):
                    status = analysis.main([str(source), "--csv", str(report), "--graph", str(graph)])
                self.assertEqual(status, 1)
                calculate.assert_not_called()
                plot.assert_not_called()
                self.assertEqual(report.read_bytes(), b"old report")
                self.assertEqual(graph.read_bytes(), b"old graph")

    def test_source_and_outputs_must_have_distinct_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "same.csv")
            cases = (["--csv", str(analysis.DEFAULT_SOURCE)],
                     ["--graph", str(analysis.DEFAULT_SOURCE)],
                     ["--csv", path, "--graph", path])
            for args in cases:
                with self.subTest(args=args), patch.object(analysis, "build_analysis") as build, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(analysis.main(args), 1)
                    build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
