"""Verify shared mandate validation and both analyses' automatic safeguards."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auxiliary import district_validation as checker
import dist_mandatos
import small_districts_loss_analysis
from data_parser import parse_stacked_country_file
from export_site_map_metrics import build_export, validate_source_rows


class VoterMandateTests(unittest.TestCase):
    def source_text(self, voter_header="Inscritos", year="2028"):
        # Weights exactly proportional to these 226 mandates give a known result.
        self.caps = {f"District {i}": (12 if i < 6 else 11) for i in range(20)}
        header = "Circulo,A,B,Mandatos,Totais"
        if voter_header:
            header += f",{voter_header}"
        rows = [f"{year},,,,,", header]
        for district, mandates in self.caps.items():
            row = f"{district},60,40,{mandates},100"
            if voter_header:
                row += f",{mandates * 1000}"
            rows.append(row)
        return "\n".join(rows)

    def run_check(self, text):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data_Portugal.csv"
            source.write_text(text, encoding="utf-8-sig")
            output, error = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    elections = checker.load_validated_elections(source)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(error.getvalue(), "")
            finally:
                self.assertEqual(source.read_text(encoding="utf-8-sig"), text)
        return elections

    def test_both_voter_headers_match_multiple_years(self):
        for header in ("Inscritos", "Eleitores"):
            with self.subTest(header=header):
                text = self.source_text(header) + "\n,,,,,\n" + self.source_text(header, "2030")
                elections = self.run_check(text)
                self.assertEqual(list(elections), ["2028", "2030"])
                self.assertEqual(elections["2028"]["mandates"], self.caps)
                self.assertEqual(elections["2030"]["mandates"], self.caps)

    def test_mismatch_reports_each_district_even_when_total_is_226(self):
        text = self.source_text()
        text = text.replace("District 0,60,40,12", "District 0,60,40,11")
        text = text.replace("District 6,60,40,11", "District 6,60,40,12")
        with self.assertRaises(ValueError) as error:
            self.run_check(text)
        self.assertIn("stored total: 226", str(error.exception))
        self.assertIn("District 0: stored=11, calculated=12", str(error.exception))
        self.assertIn("District 6: stored=12, calculated=11", str(error.exception))

    def test_invalid_or_incomplete_source_cannot_report_matches(self):
        valid = self.source_text()
        cases = ["", self.source_text(None), valid + "\n" + valid]
        cases.extend(valid.replace(",12000", f",{value}", 1) for value in ("", "oops", "-1", "0", "1.5", "nan"))
        cases.extend((
            "\n".join(valid.splitlines()[:-1]),
            valid + "\n" + valid.splitlines()[-1],
            valid.replace("District 0,", "Europa,", 1),
            valid.replace("District 0,60,40,12,100,12000", "District 0,60,40,12,100", 1),
        ))
        for text in cases:
            with self.subTest(text=text[:80]):
                with self.assertRaises(ValueError):
                    self.run_check(text)

    def test_default_source_stays_in_repository_root(self):
        self.assertEqual(checker.DEFAULT_SOURCE, Path(__file__).resolve().parents[1] / "data_Portugal.csv")

    def test_both_analyses_stop_before_calculating_or_overwriting_outputs(self):
        original = checker.DEFAULT_SOURCE.read_text(encoding="utf-8-sig")
        corruptions = {
            "seats": original.replace(",3,72041,118320", ",2,72041,118320").replace(
                ",2,54688,90045", ",3,54688,90045"
            ),
            "voters": original.replace(",3,72041,118320", ",3,72041,117358"),
        }
        for fault, text in corruptions.items():
            self.assertNotEqual(text, original)
            for module, analysis_func in (
                (dist_mandatos, "party_totals"),
                (small_districts_loss_analysis, "minimum_voter_loss"),
            ):
                with self.subTest(fault=fault, script=module.__name__), tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "data_Portugal.csv"
                    source.write_text(text, encoding="utf-8")
                    report, graph = Path(directory) / "report.csv", Path(directory) / "graph.png"
                    report.write_bytes(b"previous report")
                    graph.write_bytes(b"previous graph")
                    time_graph = Path(directory) / "time_graph.png"
                    time_graph.write_bytes(b"previous time graph")
                    args = [str(source)]
                    if module is dist_mandatos:
                        args += ["--output", str(report)]
                    else:
                        args += ["--csv", str(report), "--graph", str(graph), "--time-graph", str(time_graph)]
                    output, error = io.StringIO(), io.StringIO()
                    with patch.object(module, analysis_func) as calculate, \
                            patch.object(small_districts_loss_analysis, "plot_margins") as plot, \
                            contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        status = module.main(args)
                    self.assertEqual(status, 1)
                    self.assertIn("Mandate validation failed", error.getvalue())
                    self.assertIn("2025", error.getvalue())
                    self.assertIn("Beja", error.getvalue())
                    self.assertEqual(output.getvalue(), "")
                    calculate.assert_not_called()
                    plot.assert_not_called()
                    self.assertEqual(report.read_bytes(), b"previous report")
                    self.assertEqual(graph.read_bytes(), b"previous graph")
                    self.assertEqual(time_graph.read_bytes(), b"previous time graph")
                    self.assertEqual(source.read_text(encoding="utf-8"), text)

    def test_voter_column_anywhere_does_not_change_parser_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            source.write_text(self.source_text(None), encoding="utf-8")
            expected = parse_stacked_country_file(str(source))
            for header in ("Inscritos", "Eleitores"):
                text = self.source_text(header)
                # Also test insertion before the party columns.
                moved = []
                for line in text.splitlines():
                    cells = line.split(",")
                    moved.append(",".join([cells[0], cells[-1], *cells[1:-1]]))
                for variant in (text, "\n".join(moved)):
                    with self.subTest(header=header, variant=variant[:50]):
                        source.write_text(variant, encoding="utf-8")
                        self.assertEqual(parse_stacked_country_file(str(source)), expected)
                        self.assertEqual(validate_source_rows(source)["2028"]["parties"], ["A", "B"])

    def test_real_map_results_equal_results_without_voter_column(self):
        source = checker.DEFAULT_SOURCE
        lines = source.read_text(encoding="utf-8-sig").splitlines()
        stripped = "\n".join(line.rsplit(",", 1)[0] for line in lines)
        with tempfile.TemporaryDirectory() as directory:
            old_source = Path(directory) / "data_Portugal.csv"
            old_source.write_text(stripped, encoding="utf-8")
            self.assertEqual(
                parse_stacked_country_file(str(source)), parse_stacked_country_file(str(old_source))
            )
            self.assertEqual(build_export(source)["values"], build_export(old_source)["values"])

    def test_exact_quotients_break_ties_in_favor_of_smaller_electorate(self):
        # CNE's seven-seat example: D's 3000 beats A's tied 12000/4.
        from unittest.mock import patch
        with patch.object(checker, "TOTAL_MANDATES", 7):
            self.assertEqual(
                checker.apportion_mandates({"A": 12000, "B": 7500, "C": 4500, "D": 3000}),
                {"A": 3, "B": 2, "C": 1, "D": 1},
            )


if __name__ == "__main__":
    unittest.main()
