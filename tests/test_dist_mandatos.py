"""Check allocation rules, removal ordering, and console/CSV report output."""

import contextlib
import csv
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import dist_mandatos as analysis
from baseline_engines import dhondt_apportion, sainte_lague_apportion


class MandateDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = analysis.build_analysis(analysis.DEFAULT_SOURCE)
        cls.elections, _ = analysis.load_elections(analysis.DEFAULT_SOURCE)

    def test_guaranteed_seats_precede_a_fresh_allocation(self):
        weights = {"Large": 1000, "Small": 1}
        self.assertEqual(analysis.allocate_seats(weights, 6)[0], {"Large": 6, "Small": 0})
        self.assertEqual(
            analysis.allocate_seats(weights, 6, guaranteed=1)[0], {"Large": 5, "Small": 1}
        )
        self.assertEqual(
            analysis.allocate_seats(weights, 6, guaranteed=2)[0], {"Large": 4, "Small": 2}
        )
        for year, data in self.results.items():
            for minimum in (1, 2):
                with self.subTest(year=year, minimum=minimum):
                    expected = dhondt_apportion(data["voters"], 226 - 20 * minimum)
                    self.assertEqual(
                        data["scenarios"][f"Guaranteed {minimum}"],
                        {district: seats + minimum for district, seats in expected.items()},
                    )

    def test_standard_sainte_lague_uses_odd_divisors(self):
        weights = {"A": 100, "B": 60}
        self.assertEqual(analysis.allocate_seats(weights, 4)[0], {"A": 3, "B": 1})
        self.assertEqual(
            analysis.allocate_seats(weights, 4, divisor_step=2)[0], {"A": 2, "B": 2}
        )
        for year, data in self.results.items():
            with self.subTest(year=year):
                expected, _ = sainte_lague_apportion(data["voters"], 226)
                self.assertEqual(data["scenarios"]["Sainte-Lague"], expected)

    def test_equalization_gives_six_largest_twelve_seats(self):
        weights = {f"District {i:02}": i + 1 for i in range(20)}
        caps = analysis.equalized_seats(weights)
        self.assertEqual(sum(caps.values()), 226)
        self.assertEqual(Counter(caps.values()), {11: 14, 12: 6})
        self.assertEqual({d for d, seats in caps.items() if seats == 12}, {f"District {i:02}" for i in range(14, 20)})

    def test_party_totals_use_local_dhondt(self):
        votes = {"D1": {"A": 60, "B": 40}, "D2": {"A": 10, "B": 90}}
        self.assertEqual(
            analysis.party_totals(votes, {"D1": 3, "D2": 1}, ["A", "B"]), {"A": 2, "B": 2}
        )
        self.assertEqual(
            analysis.party_totals(votes, {"D1": 1, "D2": 3}, ["A", "B"]), {"A": 1, "B": 3}
        )
        self.assertEqual(dhondt_apportion({"A": 70, "B": 130}, 4), {"A": 1, "B": 3})
        for data in self.results.values():
            for totals in data["parties"].values():
                self.assertEqual(sum(totals.values()), 226)

    def test_every_removal_matches_a_fresh_smaller_allocation(self):
        for year, data in self.results.items():
            reduced = data["current"].copy()
            self.assertEqual([loss["total"] for loss in data["removals"]], list(range(225, 179, -1)))
            for loss in data["removals"]:
                with self.subTest(year=year, total=loss["total"]):
                    reduced[loss["district"]] -= 1
                    expected = dhondt_apportion(data["voters"], loss["total"])
                    self.assertEqual(reduced, expected)
                    self.assertEqual(loss["new"], reduced[loss["district"]])
                    self.assertEqual(loss["change"], reduced[loss["district"]] - data["current"][loss["district"]])

    def test_lost_party_compares_local_representation_at_each_step(self):
        for year, data in self.results.items():
            for loss in data["removals"]:
                with self.subTest(year=year, total=loss["total"]):
                    votes = self.elections[year]["votes"][loss["district"]]
                    before = dhondt_apportion(votes, loss["new"] + 1)
                    after = dhondt_apportion(votes, loss["new"])
                    lost = [party for party in before if before[party] == 1 and after[party] == 0]
                    self.assertLessEqual(len(lost), 1)
                    self.assertEqual(loss["lost_party"], lost[0] if lost else "-")
        # PAN disappears from Lisboa at 213, rather than every subsequent step.
        lisboa = [loss for loss in self.results["2015"]["removals"] if loss["district"] == "Lisboa"]
        pan_step = next(index for index, loss in enumerate(lisboa) if loss["total"] == 213)
        self.assertEqual(lisboa[pan_step]["lost_party"], "PAN")
        self.assertEqual(lisboa[pan_step + 1]["lost_party"], "-")
        self.assertEqual(self.results["2025"]["removals"][0]["lost_party"], "AD")

    def test_cli_writes_utf8_csv_and_preserves_source(self):
        original = analysis.DEFAULT_SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist_mandatos_excel.csv"
            messages = io.StringIO()
            with contextlib.redirect_stdout(messages):
                status = analysis.main(["--output", str(output)])
            self.assertEqual(status, 0)
            self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
            with output.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(analysis.CSV_FIELDS))
                rows = list(reader)
            for year in self.results:
                self.assertIn(f"\n{year}\n", messages.getvalue())
                losses = [r for r in rows if r["Year"] == year and r["Analysis"] == "Removal order"]
                self.assertEqual(len(losses), 46)
                self.assertEqual([int(r["Total_mandates"]) for r in losses], list(range(225, 179, -1)))
                self.assertEqual([r["Lost_party"] for r in losses],
                                 [loss["lost_party"] for loss in self.results[year]["removals"]])
                for scenario in analysis.SCENARIOS:
                    parties = [r for r in rows if r["Year"] == year and r["Analysis"] == "Party totals" and r["Scenario"] == scenario]
                    self.assertEqual(sum(int(r["New_mandates"]) for r in parties), 226)
            first = self.results["2015"]["removals"][0]
            first_loss_row = messages.getvalue().split(
                "Ordered losses as total mandates decrease (cumulative change):\n", 1
            )[1].splitlines()[1]
            self.assertIn("Lost a party?", messages.getvalue())
            self.assertEqual(first_loss_row.split(), [*first["district"].split(), "-1", "225", first["lost_party"]])
            self.assertIn("Açores", output.read_text(encoding="utf-8-sig"))
        self.assertEqual(analysis.DEFAULT_SOURCE.read_bytes(), original)

    def test_invalid_baseline_preserves_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            text = analysis.DEFAULT_SOURCE.read_text(encoding="utf-8-sig")
            source.write_text(text.replace(",5,88817", ",6,88817", 1), encoding="utf-8")
            output = Path(directory) / "report.csv"
            output.write_text("previous report", encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = analysis.main([str(source), "--output", str(output)])
            self.assertEqual(status, 1)
            self.assertIn("do not match", errors.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "previous report")

    def test_output_cannot_overwrite_source(self):
        with contextlib.redirect_stderr(io.StringIO()):
            status = analysis.main(["--output", str(analysis.DEFAULT_SOURCE)])
        self.assertEqual(status, 1)


if __name__ == "__main__":
    unittest.main()
