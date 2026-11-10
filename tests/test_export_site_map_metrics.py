"""Behavior checks for map semantics, source validation, and refresh safety."""

import contextlib
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import export_site_map_metrics as exporter


class MapMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = exporter.discover_source()
        cls.payload = exporter.build_export(cls.source)
        cls.elections, cls.mappings = exporter.load_elections(cls.source)
        cls.regions = exporter.load_regions(exporter.DEFAULT_SCHEMA)

    def write_source(self, directory, text):
        path = Path(directory) / "data_Portugal.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def source_text(self):
        return self.source.read_text(encoding="utf-8-sig")

    def test_real_source_contract_and_independent_current_spot_check(self):
        self.assertEqual(set(self.payload["years"]), set(self.elections))
        self.assertEqual(len(self.payload["regions"]), 20)
        self.assertEqual(set(self.payload["metrics"]), set(exporter.METRICS))
        self.assertNotIn("effective_threshold_pct", json.dumps(self.payload))
        self.assertFalse(self.payload["demo"])
        # Lisboa 2015 elects PS, PSD-CDS, BE, CDU and PAN under district D'Hondt.
        votes = self.elections["2015"]["votes"]["Lisboa"]
        valid_votes = self.elections["2015"]["total_votes_cast"]["Lisboa"]
        omitted = valid_votes - sum(votes.values())
        wasted = omitted + sum(v for p, v in votes.items() if p not in {"PS", "PSD-CDS", "BE", "CDU", "PAN"})
        metrics = self.payload["values"]["current"]["2015"]["lisboa"]
        self.assertEqual(metrics["represented_parties_count"], 5)
        self.assertAlmostEqual(metrics["wasted_votes_pct"], 100 * wasted / valid_votes, places=6)

    def test_default_input_format_counts_omitted_valid_votes_as_wasted(self):
        self.assertTrue(self.payload["source"]["omitted_lists_assumed_unrepresented"])
        self.assertEqual(self.payload["source"]["valid_votes_basis"], "Totais")
        self.assertTrue(self.payload["source"]["assumptions"])
        # Every supplied list wins nationally in 2019; the omitted votes remain wasted.
        data = self.elections["2019"]
        valid = data["total_votes_cast"]["Lisboa"]
        expected = 100 * (valid - sum(data["votes"]["Lisboa"].values())) / valid
        self.assertAlmostEqual(self.payload["values"]["proposal"]["2019"]["lisboa"]["wasted_votes_pct"], expected, places=6)

    def test_future_year_is_discovered_without_changing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, self.source_text().replace("2025,", "2028,", 1))
            payload = exporter.build_export(source)
        self.assertIn("2028", payload["years"])
        self.assertNotIn("2025", payload["years"])
        for model in exporter.MODELS:
            self.assertEqual(len(payload["values"][model]["2028"]), 20)

    def test_national_waste_and_local_coalition_count(self):
        # A list winning only in Lisboa still represents its votes in Aveiro nationally.
        names = [info["name"] for info in self.regions.values()]
        rows = ["2028,,,", "Circulo,A-B,C,D,Mandatos,Totais"]
        rows.extend(
            f"{name},0,100,1,1,101" if name == "Lisboa" else f"{name},100,1,1,1,102"
            for name in names
        )
        with tempfile.TemporaryDirectory() as directory:
            payload = exporter.build_export(self.write_source(directory, "\n".join(rows)))
        current = payload["values"]["current"]["2028"]["aveiro"]
        proposal = payload["values"]["proposal"]["2028"]["aveiro"]
        self.assertAlmostEqual(current["wasted_votes_pct"], 200 / 102, places=6)
        self.assertAlmostEqual(proposal["wasted_votes_pct"], 100 / 102, places=6)
        self.assertEqual(current["represented_parties_count"], 1)
        self.assertEqual(proposal["represented_parties_count"], 1)
        self.assertNotIn("europa", payload["values"]["proposal"]["2028"])
        # C wins nationally without winning in the map; D has no national seat.
        votes = {"A-B": 80, "C": 15, "D": 5}
        seats = {"A-B": 1, "C": 0, "D": 0}
        self.assertEqual(exporter.district_metrics(votes, seats, {"A-B"}, 100)["wasted_votes_pct"], 20.0)
        metrics = exporter.district_metrics(votes, seats, {"A-B", "C"}, 100)
        self.assertEqual(metrics, {"wasted_votes_pct": 5.0, "represented_parties_count": 1})
        # Ten additional valid votes are for omitted lists, assumed unrepresented.
        metrics = exporter.district_metrics(votes, seats, {"A-B", "C"}, 110)
        self.assertAlmostEqual(metrics["wasted_votes_pct"], 100 * 15 / 110, places=6)

    def test_overseas_rows_are_rejected_before_any_electoral_calculation(self):
        names = [info["name"] for info in self.regions.values()]
        rows = ["2028,,,", "Circulo,A-B,C,D,Mandatos,Totais"]
        rows.extend(f"{name},100,1,1,1,102" for name in names)
        for district in ("Europa", "Fora da Europa"):
            with self.subTest(district=district), tempfile.TemporaryDirectory() as directory:
                source = self.write_source(directory, "\n".join(rows + [f"{district},0,100,0,1,100"]))
                with patch.object(exporter, "dhondt_apportion") as current, \
                        patch.object(exporter, "get_national_party_caps") as national, \
                        patch.object(exporter, "proposal_config") as proposal:
                    with self.assertRaisesRegex(ValueError, "calculations accept only"):
                        exporter.build_export(source)
                current.assert_not_called()
                national.assert_not_called()
                proposal.assert_not_called()

    def test_proposal_uses_standard_danish_pool_with_single_cap_four(self):
        method = exporter.proposal_config()
        self.assertIs(method["func"], exporter.allocate_two_speed_pool_method)
        self.assertEqual(self.payload["models"]["proposal"]["method"], "2-Speed Danish Pool")
        self.assertEqual(self.payload["models"]["proposal"]["parameters"], {"round1_district_cap": 4})
        # With one list and five seats per district, every district's first round
        # receives four seats, regardless of its size; the second round fills it.
        votes = {name: {"A-B": 100} for name in self.regions}
        caps = {name: 5 for name in self.regions}
        tracker = {}
        seats, totals, _ = method["func"](votes, {"A-B": 100}, caps, phase_tracker=tracker, **method["kwargs"])
        self.assertTrue(all(row["A-B"] == 4 for row in tracker["phase1"].values()))
        self.assertTrue(all(row["A-B"] == 5 for row in seats.values()))
        self.assertEqual(totals, {"A-B": 100})

    def test_broken_vote_cells_are_never_coerced_to_zero(self):
        for invalid in ("", "broken", "-1", "1.5", "nan", "inf"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                source = self.write_source(directory, self.source_text().replace("37720", invalid, 1))
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    exporter.build_export(source)

    def test_missing_region_and_inconsistent_totals_fail(self):
        text = self.source_text()
        alterations = (
            ("\n".join(line for line in text.splitlines() if not line.startswith("Açores,")), "missing map constituencies"),
            (text.replace(",5,88817", ",5,1", 1), "Totais is smaller"),
            (text.replace(",5,88817", ",0,88817", 1), "district seats must be positive"),
            (text.replace("Portalegre,", "Unknown,", 1), "unrecognized constituency"),
        )
        for modified, error in alterations:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, error):
                    exporter.build_export(self.write_source(directory, modified))

    def test_duplicate_year_district_and_truncated_row_fail(self):
        text = self.source_text()
        row = next(line for line in text.splitlines() if line.startswith("Açores,"))
        width = len(next(csv.reader([row])))
        alterations = (
            (text.replace("2019,", "2015,", 1), "duplicate election year"),
            (text.replace(row, row + "\n" + row, 1), "duplicate district"),
            (text.replace(row, row.rsplit(",", 1)[0], 1), f"expected {width} columns"),
        )
        for modified, error in alterations:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, error):
                    exporter.build_export(self.write_source(directory, modified))

    def test_parser_cannot_silently_drop_rows_after_separator(self):
        text = self.source_text().replace("Madeira,26208", "\nMadeira,26208", 1)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "omitted or changed"):
                exporter.build_export(self.write_source(directory, text))

    def test_national_mandate_override_is_preserved_and_checked(self):
        names = [info["name"] for info in self.regions.values()]
        rows = ["2028,,,", "Circulo,A-B,C,Mandatos,Totais"]
        rows.extend(f"{name},100,10,1,110" for name in names)
        rows.append("Totais Mandatos,10,10,,")
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, "\n".join(rows))
            payload = exporter.build_export(source)
            self.assertEqual(payload["values"]["proposal"]["2028"]["aveiro"]["wasted_votes_pct"], 0.0)
            source.write_text("\n".join(rows).replace("Totais Mandatos,10,10", "Totais Mandatos,10,9"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "national party targets are inconsistent"):
                exporter.build_export(source)

    def test_invalid_or_incomplete_output_fails_validation(self):
        corruptions = (
            lambda p: p["values"]["proposal"].pop("2015"),
            lambda p: p["values"]["current"]["2015"].pop("aveiro"),
            lambda p: p["values"]["current"]["2015"]["aveiro"].pop("wasted_votes_pct"),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(wasted_votes_pct=float("nan")),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(wasted_votes_pct=101),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(wasted_votes_pct=True),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(represented_parties_count=1.5),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(represented_parties_count=True),
            lambda p: p["values"]["current"]["2015"]["aveiro"].update(represented_parties_count=999),
        )
        for corrupt in corruptions:
            with self.subTest(corrupt=corrupt):
                payload = copy.deepcopy(self.payload)
                corrupt(payload)
                with self.assertRaises(ValueError):
                    exporter.validate_export(payload, self.elections, self.mappings, self.regions)

    def test_invalid_schema_region_id_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = {"regions": copy.deepcopy(self.regions)}
            reference["regions"]["azores"] = reference["regions"].pop("acores")
            schema = Path(directory) / "schema.json"
            schema.write_text(json.dumps(reference), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "20 expected map region ids"):
                exporter.build_export(self.source, schema)

    def test_incomplete_proposal_allocation_is_rejected(self):
        original = exporter.proposal_config()
        def broken(votes, targets, caps, **kwargs):
            seats, totals, history = original["func"](votes, targets, caps, **kwargs)
            seats.pop(next(iter(seats)))
            return seats, totals, history
        with patch.object(exporter, "proposal_config", return_value={**original, "func": broken}):
            with self.assertRaisesRegex(ValueError, "incomplete allocation districts"):
                exporter.build_export(self.source)

    def test_cli_failure_preserves_previous_output_and_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "map.json"
            output.write_text("previous output", encoding="utf-8")
            missing_source = Path(directory) / "missing.csv"
            invalid_source = self.write_source(directory, self.source_text().replace(",5,88817", ",5,1", 1))
            for source, message in ((missing_source, "Export failed:"), (invalid_source, "Totais is smaller")):
                with self.subTest(source=source):
                    error = io.StringIO()
                    with patch.object(exporter, "discover_source", return_value=source), \
                            patch.object(exporter, "DEFAULT_OUTPUT", output), \
                            contextlib.redirect_stderr(error):
                        status = exporter.main()
                    self.assertEqual(status, 1)
                    self.assertIn(message, error.getvalue())
                    self.assertEqual(output.read_text(encoding="utf-8"), "previous output")

    def test_no_argument_run_validates_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs" / "map.json"
            messages = io.StringIO()
            with patch.object(exporter, "DEFAULT_OUTPUT", output), contextlib.redirect_stdout(messages):
                status = exporter.main()
            self.assertEqual(status, 0)
            self.assertIn("Validation passed:", messages.getvalue())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.payload)

    def test_successful_output_round_trip_and_repeatability(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs" / "map.json"
            exporter.write_export(self.payload, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.payload)
            self.assertEqual(list(output.parent.glob("*.tmp")), [])
        self.assertEqual(exporter.build_export(self.source), self.payload)


if __name__ == "__main__":
    unittest.main()
