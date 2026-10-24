"""Tests for rgpd_offshore_check. Standard library only; files go to temp dirs."""
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rgpd_offshore_check as rgc  # noqa: E402

SCRIPT = ROOT / "rgpd_offshore_check.py"
EXAMPLES = ROOT / "examples"


def compliant_answers():
    """A complete set-up with no open item (SCC path, everything documented)."""
    return {
        "label": "Fictitious complete set-up",
        "destination_country": "Morocco",
        "adequacy_decision": False,
        "safeguards": ["scc"],
        "tia_documented": True,
        "art28_contract": {
            "in_writing": True,
            "clauses": {key: True for key in rgc.CLAUSE_KEYS},
        },
        "security_controls": {key: True for key in rgc.CONTROL_KEYS},
        "breach_notification_procedure": True,
        "data_subject_rights_process": True,
        "iso27001_scope_verified": True,
    }


def adequacy_answers():
    """A set-up relying on an adequacy decision whose scope was verified."""
    answers = compliant_answers()
    answers["destination_country"] = "Fictitious adequate country"
    answers["adequacy_decision"] = True
    answers["adequacy_scope_verified"] = True
    del answers["safeguards"]
    del answers["tia_documented"]
    return answers


def by_id(report):
    return {finding.id: finding for finding in report.findings}


def run_cli(args, cwd=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=60,
    )


class TempFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_json(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def write_text(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return str(path)


class CompliantPathTests(unittest.TestCase):
    def test_complete_input_has_no_blocking_gap(self):
        report = rgc.evaluate(compliant_answers())
        summary = report.summary
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(summary["result"], "no_blocking_gap")
        self.assertEqual(summary["blocking_total"], 0)
        self.assertEqual(summary["blocking_gaps"], [])
        self.assertEqual(summary["blocking_to_verify"], [])
        self.assertEqual(summary["recommended_open"], [])
        self.assertEqual(summary["informational_open"], [])
        self.assertEqual(report.warnings, [])
        for finding in report.findings:
            self.assertEqual(finding.status, rgc.OK, finding.id)

    def test_no_blocking_gap_is_never_worded_as_compliance(self):
        for lang in rgc.LANGS:
            text = rgc.evaluate(compliant_answers(), lang).to_markdown()
            self.assertNotIn("compliant:", text.lower())
        text = rgc.evaluate(compliant_answers()).to_markdown()
        self.assertIn("not a finding of compliance", text)
        text = rgc.evaluate(compliant_answers(), "fr").to_markdown()
        self.assertIn("pas un constat de conformité", text)

    def test_adequacy_country_path(self):
        report = rgc.evaluate(adequacy_answers())
        found = by_id(report)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(found["TRANSFER-BASIS"].status, rgc.OK)
        self.assertEqual(found["TRANSFER-BASIS"].reason, "adequacy_verified")
        self.assertEqual(found["TRANSFER-TIA"].status, rgc.NOT_APPLICABLE)
        self.assertEqual(report.summary["counts"]["not_applicable"], 1)

    def test_adequacy_scope_not_confirmed_is_not_accepted(self):
        answers = adequacy_answers()
        del answers["adequacy_scope_verified"]
        found = by_id(rgc.evaluate(answers))
        self.assertEqual(found["TRANSFER-BASIS"].status, rgc.TO_VERIFY)
        self.assertEqual(found["TRANSFER-BASIS"].reason, "adequacy_scope_unverified")
        self.assertEqual(rgc.evaluate(answers).exit_code, 1)
        answers["adequacy_scope_verified"] = False
        found = by_id(rgc.evaluate(answers))
        self.assertEqual(found["TRANSFER-BASIS"].status, rgc.GAP)
        self.assertEqual(found["TRANSFER-BASIS"].severity, rgc.BLOCKING)

    def test_malformed_adequacy_answer_is_not_accepted(self):
        for bad in ("true", "yes", 1, [True]):
            with self.subTest(value=bad):
                answers = adequacy_answers()
                answers["adequacy_decision"] = bad
                report = rgc.evaluate(answers)
                found = by_id(report)
                self.assertEqual(found["TRANSFER-BASIS"].status, rgc.TO_VERIFY)
                self.assertEqual(found["TRANSFER-BASIS"].reason, "answer_malformed")
                self.assertEqual(found["TRANSFER-TIA"].status, rgc.TO_VERIFY)
                self.assertEqual(report.exit_code, 1)

    def test_adequacy_claim_without_destination_is_blocking(self):
        answers = adequacy_answers()
        del answers["destination_country"]
        report = rgc.evaluate(answers)
        self.assertEqual(by_id(report)["TRANSFER-DESTINATION"].status, rgc.TO_VERIFY)
        self.assertEqual(report.exit_code, 1)


class TransferTests(unittest.TestCase):
    def test_scc_without_tia_is_blocking(self):
        answers = compliant_answers()
        answers["tia_documented"] = False
        report = rgc.evaluate(answers)
        finding = by_id(report)["TRANSFER-TIA"]
        self.assertEqual(finding.status, rgc.GAP)
        self.assertEqual(finding.severity, rgc.BLOCKING)
        self.assertEqual(finding.reason, "scc_without_tia")
        self.assertEqual(report.summary["blocking_gaps"], ["TRANSFER-TIA"])
        self.assertEqual(report.exit_code, 1)

    def test_scc_with_unknown_tia_is_blocking_to_verify(self):
        answers = compliant_answers()
        del answers["tia_documented"]
        report = rgc.evaluate(answers)
        finding = by_id(report)["TRANSFER-TIA"]
        self.assertEqual(finding.status, rgc.TO_VERIFY)
        self.assertEqual(finding.severity, rgc.BLOCKING)
        self.assertEqual(report.exit_code, 1)

    def test_other_art46_tool_without_tia_is_recommended_only(self):
        answers = compliant_answers()
        answers["safeguards"] = ["bcr"]
        answers["tia_documented"] = False
        report = rgc.evaluate(answers)
        finding = by_id(report)["TRANSFER-TIA"]
        self.assertEqual(finding.status, rgc.GAP)
        self.assertEqual(finding.severity, rgc.RECOMMENDED)
        self.assertEqual(finding.reason, "tia_other_tool_absent")
        self.assertEqual(report.exit_code, 0)

    def test_no_adequacy_and_no_safeguard_is_blocking(self):
        answers = compliant_answers()
        answers["safeguards"] = []
        del answers["tia_documented"]
        report = rgc.evaluate(answers)
        found = by_id(report)
        self.assertEqual(found["TRANSFER-BASIS"].status, rgc.GAP)
        self.assertEqual(found["TRANSFER-BASIS"].reason, "no_adequacy_no_safeguard")
        self.assertEqual(report.exit_code, 1)

    def test_art49_derogation_alone_is_not_a_basis(self):
        answers = compliant_answers()
        answers["safeguards"] = ["art49_derogation"]
        found = by_id(rgc.evaluate(answers))
        self.assertEqual(found["TRANSFER-BASIS"].status, rgc.GAP)
        self.assertEqual(found["TRANSFER-BASIS"].reason, "derogation_only")

    def test_unknown_safeguard_value_is_ignored_with_warning(self):
        answers = compliant_answers()
        answers["safeguards"] = ["trust-me"]
        report = rgc.evaluate(answers)
        self.assertEqual(by_id(report)["TRANSFER-BASIS"].status, rgc.GAP)
        self.assertEqual([w["code"] for w in report.warnings], ["unknown_safeguard"])

    def test_safeguards_malformed_is_to_verify(self):
        for bad in ("scc", {"scc": True}, ["scc", 3], 7, True):
            with self.subTest(value=bad):
                answers = compliant_answers()
                answers["safeguards"] = bad
                found = by_id(rgc.evaluate(answers))
                self.assertEqual(found["TRANSFER-BASIS"].status, rgc.TO_VERIFY)
                self.assertEqual(found["TRANSFER-BASIS"].reason, "answer_malformed")

    def test_destination_must_be_a_nonempty_string(self):
        for bad in (None, "", "   ", 5, ["Morocco"]):
            with self.subTest(value=bad):
                answers = compliant_answers()
                answers["destination_country"] = bad
                found = by_id(rgc.evaluate(answers))
                self.assertEqual(found["TRANSFER-DESTINATION"].status, rgc.TO_VERIFY)


class ContractTests(unittest.TestCase):
    def test_each_missing_clause_is_blocking(self):
        for key in rgc.CLAUSE_KEYS:
            with self.subTest(clause=key):
                answers = compliant_answers()
                answers["art28_contract"]["clauses"][key] = False
                report = rgc.evaluate(answers)
                check_id = "ART28-" + key.upper().replace("_", "-")
                finding = by_id(report)[check_id]
                self.assertEqual(finding.status, rgc.GAP)
                self.assertEqual(finding.severity, rgc.BLOCKING)
                self.assertEqual(report.summary["blocking_gaps"], [check_id])
                self.assertEqual(report.exit_code, 1)

    def test_each_unanswered_clause_is_blocking_to_verify(self):
        for key in rgc.CLAUSE_KEYS:
            with self.subTest(clause=key):
                answers = compliant_answers()
                del answers["art28_contract"]["clauses"][key]
                report = rgc.evaluate(answers)
                check_id = "ART28-" + key.upper().replace("_", "-")
                self.assertEqual(by_id(report)[check_id].status, rgc.TO_VERIFY)
                self.assertEqual(report.exit_code, 1)

    def test_clause_list_matches_art28_text(self):
        self.assertEqual(len(rgc.CLAUSE_KEYS), 12)
        articles = {item[1] for item in rgc.CONTRACT_CLAUSES}
        for expected in ("Art. 28(3)(a)", "Art. 28(3)(h)", "Art. 28(4)"):
            self.assertIn(expected, articles)

    def test_no_written_contract_fails_every_clause(self):
        answers = compliant_answers()
        answers["art28_contract"]["in_writing"] = False
        report = rgc.evaluate(answers)
        found = by_id(report)
        self.assertEqual(found["ART28-WRITTEN"].status, rgc.GAP)
        for key in rgc.CLAUSE_KEYS:
            finding = found["ART28-" + key.upper().replace("_", "-")]
            self.assertEqual(finding.status, rgc.GAP)
            self.assertEqual(finding.reason, "contract_absent_clause")
        self.assertEqual(report.summary["blocking_total"], 1 + len(rgc.CLAUSE_KEYS))

    def test_contract_section_missing_or_malformed(self):
        for value in (None, "signed", ["x"], 3):
            with self.subTest(value=value):
                answers = compliant_answers()
                if value is None:
                    del answers["art28_contract"]
                else:
                    answers["art28_contract"] = value
                report = rgc.evaluate(answers)
                found = by_id(report)
                self.assertEqual(found["ART28-WRITTEN"].status, rgc.TO_VERIFY)
                self.assertEqual(
                    report.summary["blocking_total"], 1 + len(rgc.CLAUSE_KEYS)
                )

    def test_clauses_object_malformed(self):
        answers = compliant_answers()
        answers["art28_contract"]["clauses"] = ["documented_instructions"]
        report = rgc.evaluate(answers)
        self.assertEqual(by_id(report)["ART28-WRITTEN"].status, rgc.OK)
        for key in rgc.CLAUSE_KEYS:
            finding = by_id(report)["ART28-" + key.upper().replace("_", "-")]
            self.assertEqual(finding.status, rgc.TO_VERIFY)
            self.assertEqual(finding.reason, "answer_malformed")


class SecurityTests(unittest.TestCase):
    def test_individual_controls_are_recommended_not_blocking(self):
        answers = compliant_answers()
        answers["security_controls"]["clean_desk"] = False
        answers["security_controls"]["pseudonymisation"] = False
        report = rgc.evaluate(answers)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(
            report.summary["recommended_open"],
            ["ART32-PSEUDONYMISATION", "ART32-CLEAN-DESK"],
        )
        self.assertEqual(by_id(report)["ART32-BASELINE"].status, rgc.OK)

    def test_none_at_all_is_blocking(self):
        answers = compliant_answers()
        answers["security_controls"] = {key: False for key in rgc.CONTROL_KEYS}
        report = rgc.evaluate(answers)
        finding = by_id(report)["ART32-BASELINE"]
        self.assertEqual(finding.status, rgc.GAP)
        self.assertEqual(finding.severity, rgc.BLOCKING)
        self.assertEqual(report.exit_code, 1)

    def test_missing_or_unconfirmed_controls_are_blocking_to_verify(self):
        answers = compliant_answers()
        del answers["security_controls"]
        report = rgc.evaluate(answers)
        self.assertEqual(by_id(report)["ART32-BASELINE"].status, rgc.TO_VERIFY)
        self.assertEqual(report.exit_code, 1)
        answers["security_controls"] = {"encryption_in_transit": False}
        report = rgc.evaluate(answers)
        self.assertEqual(by_id(report)["ART32-BASELINE"].status, rgc.TO_VERIFY)
        self.assertEqual(report.exit_code, 1)

    def test_breach_procedure_absent_is_blocking(self):
        answers = compliant_answers()
        answers["breach_notification_procedure"] = False
        report = rgc.evaluate(answers)
        self.assertEqual(
            report.summary["blocking_gaps"], ["ART33-PROCESSOR-NOTIFICATION"]
        )
        self.assertEqual(report.exit_code, 1)

    def test_rights_process_and_iso_do_not_block(self):
        answers = compliant_answers()
        answers["data_subject_rights_process"] = False
        answers["iso27001_scope_verified"] = False
        report = rgc.evaluate(answers)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.summary["recommended_open"], ["RIGHTS-PROCESS"])
        self.assertEqual(report.summary["informational_open"], ["EVIDENCE-ISO27001"])
        self.assertEqual(by_id(report)["EVIDENCE-ISO27001"].severity, rgc.INFORMATIONAL)

    def test_iso_ok_is_flagged_as_not_proof(self):
        text = by_id(rgc.evaluate(compliant_answers()))["EVIDENCE-ISO27001"].detail
        self.assertIn("not proof of GDPR compliance", text)


class FailClosedTests(unittest.TestCase):
    def test_empty_object_has_no_ok_blocking_item(self):
        report = rgc.evaluate({})
        self.assertEqual(report.exit_code, 1)
        for finding in report.findings:
            self.assertEqual(finding.status, rgc.TO_VERIFY, finding.id)

    def test_malformed_booleans_are_never_compliant(self):
        paths = [
            ("tia_documented",),
            ("breach_notification_procedure",),
            ("data_subject_rights_process",),
            ("iso27001_scope_verified",),
            ("art28_contract", "in_writing"),
            ("art28_contract", "clauses", "documented_instructions"),
            ("security_controls", "encryption_in_transit"),
        ]
        for path in paths:
            for bad in ("true", "yes", "false", 1, 0, "", [], {}, 1.0):
                with self.subTest(path=path, value=bad):
                    answers = compliant_answers()
                    target = answers
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = bad
                    report = rgc.evaluate(answers)
                    before = rgc.evaluate(compliant_answers()).summary["counts"]
                    # A non-boolean in place of a true can only remove OK items.
                    self.assertLess(report.summary["counts"]["ok"], before["ok"])
                    malformed = [f for f in report.findings if f.reason == "answer_malformed"]
                    self.assertTrue(malformed, "malformed value must be reported")
                    for finding in malformed:
                        self.assertEqual(finding.status, rgc.TO_VERIFY)

    def test_null_is_unknown(self):
        answers = compliant_answers()
        answers["breach_notification_procedure"] = None
        found = by_id(rgc.evaluate(answers))
        self.assertEqual(found["ART33-PROCESSOR-NOTIFICATION"].status, rgc.TO_VERIFY)
        self.assertEqual(found["ART33-PROCESSOR-NOTIFICATION"].reason, "answer_missing")

    def test_string_true_for_breach_is_to_verify(self):
        answers = compliant_answers()
        answers["breach_notification_procedure"] = "true"
        report = rgc.evaluate(answers)
        finding = by_id(report)["ART33-PROCESSOR-NOTIFICATION"]
        self.assertEqual(finding.status, rgc.TO_VERIFY)
        self.assertEqual(finding.reason, "answer_malformed")
        self.assertEqual(report.exit_code, 1)

    def test_unknown_keys_warn_and_comments_are_ignored(self):
        answers = compliant_answers()
        answers["_comment"] = "free text"
        answers["adequacy_decison"] = True
        answers["art28_contract"]["clauses"]["extra_clause"] = True
        answers["security_controls"]["firewall"] = True
        report = rgc.evaluate(answers)
        self.assertEqual(report.exit_code, 0)
        paths = [warning["path"] for warning in report.warnings]
        self.assertEqual(
            paths, ["$", "$.art28_contract.clauses", "$.security_controls"]
        )
        self.assertTrue(all(w["code"] == "unknown_key" for w in report.warnings))

    def test_invalid_label_warns(self):
        answers = compliant_answers()
        answers["label"] = 12
        report = rgc.evaluate(answers)
        self.assertIsNone(report.label)
        self.assertEqual([w["code"] for w in report.warnings], ["invalid_label"])

    def test_control_characters_are_not_echoed(self):
        answers = compliant_answers()
        answers["label"] = "name\x1b[31m red\x00"
        answers["destination_country"] = "Mor\x07occo"
        report = rgc.evaluate(answers)
        text = report.to_markdown() + report.to_json()
        for char in ("\x1b", "\x00", "\x07"):
            self.assertNotIn(char, text)

    def test_evaluate_rejects_non_object_and_bad_lang(self):
        with self.assertRaises(rgc.InputError):
            rgc.evaluate([])
        with self.assertRaises(ValueError):
            rgc.evaluate({}, "de")


class OutputTests(unittest.TestCase):
    TOP_KEYS = [
        "tool",
        "version",
        "schema_version",
        "lang",
        "disclaimer",
        "input",
        "summary",
        "findings",
        "warnings",
        "notes",
        "sources",
    ]
    FINDING_KEYS = [
        "id",
        "category",
        "articles",
        "severity",
        "status",
        "reason",
        "title",
        "detail",
        "action",
    ]
    SUMMARY_KEYS = [
        "result",
        "exit_code",
        "blocking_total",
        "blocking_gaps",
        "blocking_to_verify",
        "recommended_open",
        "informational_open",
        "counts",
    ]

    def test_json_schema_is_stable(self):
        data = json.loads(rgc.evaluate(compliant_answers()).to_json())
        self.assertEqual(list(data), self.TOP_KEYS)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["tool"], "rgpd-offshore-check")
        self.assertEqual(list(data["summary"]), self.SUMMARY_KEYS)
        self.assertEqual(list(data["summary"]["counts"]), list(rgc.STATUSES))
        self.assertEqual(list(data["input"]), ["label", "destination_country"])
        for finding in data["findings"]:
            self.assertEqual(list(finding), self.FINDING_KEYS)
            self.assertIn(finding["status"], rgc.STATUSES)
            self.assertIn(finding["severity"], (rgc.BLOCKING, rgc.RECOMMENDED, rgc.INFORMATIONAL))
        self.assertEqual([f["id"] for f in data["findings"]], list(rgc.CHECK_IDS))
        self.assertEqual(len(set(rgc.CHECK_IDS)), len(rgc.CHECK_IDS))
        self.assertEqual(len(data["sources"]), 3)
        self.assertIn("not legal advice", data["disclaimer"])

    def test_output_is_deterministic(self):
        answers = compliant_answers()
        answers["tia_documented"] = False
        answers["x_unknown"] = 1
        first = rgc.evaluate(copy.deepcopy(answers))
        second = rgc.evaluate(copy.deepcopy(answers))
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.to_markdown(), second.to_markdown())

    def test_same_verdict_in_both_languages(self):
        answers = compliant_answers()
        answers["tia_documented"] = False
        english = rgc.evaluate(answers, "en")
        french = rgc.evaluate(answers, "fr")
        self.assertEqual(english.summary, french.summary)
        self.assertEqual(
            [(f.id, f.status, f.severity, f.reason) for f in english.findings],
            [(f.id, f.status, f.severity, f.reason) for f in french.findings],
        )
        self.assertNotEqual(english.findings[0].title, french.findings[0].title)

    def test_every_text_exists_in_both_languages(self):
        for spec in rgc.SPECS:
            for lang in rgc.LANGS:
                self.assertTrue(spec.title[lang].strip(), spec.id)
                self.assertTrue(spec.action[lang].strip(), spec.id)
        for name, texts in rgc.MESSAGES.items():
            self.assertEqual(sorted(texts), ["en", "fr"], name)
        for name, texts in rgc.UI.items():
            self.assertEqual(sorted(texts), ["en", "fr"], name)

    def test_markdown_sections_notes_and_sources(self):
        answers = compliant_answers()
        answers["tia_documented"] = False
        for lang, marker in (("en", "Not legal advice"), ("fr", "ni un avis juridique")):
            text = rgc.evaluate(answers, lang).to_markdown()
            self.assertIn("TRANSFER-TIA", text)
            self.assertIn("Art. 5(2)" if lang == "en" else "par. 2", text)
            self.assertIn("https://eur-lex.europa.eu/eli/reg/2016/679/oj", text)
            self.assertIn("https://eur-lex.europa.eu/eli/dec_impl/2021/914/oj", text)
            self.assertIn("C-311/18", text)
            self.assertTrue(marker.lower() in text.lower())
        self.assertIn("accountable", rgc.evaluate(answers, "en").to_markdown())
        self.assertIn("responsable", rgc.evaluate(answers, "fr").to_markdown())

    def test_example_files_behave_as_documented(self):
        report = rgc.evaluate(rgc.load_answers(str(EXAMPLES / "answers.json")))
        self.assertEqual(
            report.summary["blocking_gaps"],
            ["TRANSFER-TIA", "ART28-SUBPROCESSOR-PRIOR-AUTHORISATION"],
        )
        self.assertEqual(report.summary["blocking_to_verify"], [])
        self.assertEqual(report.warnings, [])
        minimal = rgc.evaluate(rgc.load_answers(str(EXAMPLES / "answers_minimal.json")))
        self.assertEqual(minimal.exit_code, 1)
        self.assertEqual(minimal.summary["counts"]["ok"], 1)
        self.assertEqual(minimal.summary["counts"]["gap"], 0)
        self.assertEqual(minimal.summary["counts"]["to_verify"], len(rgc.CHECK_IDS) - 1)


class LoadAnswersTests(TempFiles):
    def test_valid_file(self):
        path = self.write_json("ok.json", {"destination_country": "Madagascar"})
        self.assertEqual(rgc.load_answers(path), {"destination_country": "Madagascar"})

    def test_bom_is_accepted(self):
        path = self.tmp / "bom.json"
        path.write_bytes(b"\xef\xbb\xbf" + b'{"label": "x"}')
        self.assertEqual(rgc.load_answers(str(path)), {"label": "x"})

    def test_invalid_inputs_raise(self):
        cases = {
            "not_json.json": "{nope",
            "empty.json": "",
            "list.json": "[1, 2]",
            "string.json": '"hello"',
            "null.json": "null",
            "dup.json": '{"a": true, "a": false}',
            "nan.json": '{"a": NaN}',
            "deep.json": "[" * 100000,
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                path = self.write_text(name, text)
                with self.assertRaises(rgc.InputError):
                    rgc.load_answers(path)

    def test_missing_file_and_directory_raise(self):
        with self.assertRaises(rgc.InputError):
            rgc.load_answers(str(self.tmp / "absent.json"))
        with self.assertRaises(rgc.InputError):
            rgc.load_answers(str(self.tmp))

    def test_binary_file_raises(self):
        path = self.tmp / "bin.json"
        path.write_bytes(b"\xff\xfe\x00\x01")
        with self.assertRaises(rgc.InputError):
            rgc.load_answers(str(path))


class MainFunctionTests(TempFiles):
    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rgc.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_in_process(self):
        good = self.write_json("good.json", compliant_answers())
        bad = compliant_answers()
        bad["tia_documented"] = False
        gap = self.write_json("gap.json", bad)
        self.assertEqual(self.call([good])[0], 0)
        self.assertEqual(self.call([gap])[0], 1)
        code, out, err = self.call([str(self.tmp / "absent.json")])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("error:", err)

    def test_usage_errors_return_2(self):
        for args in ([], ["--lang", "de", "x.json"], ["--nope", "x.json"]):
            with self.subTest(args=args):
                self.assertEqual(self.call(args)[0], 2)

    def test_json_flag_prints_json(self):
        good = self.write_json("good.json", compliant_answers())
        code, out, _err = self.call([good, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["summary"]["exit_code"], 0)


class CliSubprocessTests(TempFiles):
    def test_example_gap_report_exits_1(self):
        proc = run_cli([str(EXAMPLES / "answers.json")])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertIn("# GDPR offshore outsourcing checklist", proc.stdout)
        self.assertIn("TRANSFER-TIA", proc.stdout)
        self.assertIn("not legal advice", proc.stdout)

    def test_minimal_example_exits_1_with_unknowns(self):
        proc = run_cli([str(EXAMPLES / "answers_minimal.json"), "--json"])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["summary"]["blocking_gaps"], [])
        self.assertGreater(len(data["summary"]["blocking_to_verify"]), 10)

    def test_compliant_file_exits_0(self):
        path = self.write_json("good.json", compliant_answers())
        proc = run_cli([path])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no blocking gap", proc.stdout)

    def test_json_and_french_output(self):
        path = self.write_json("good.json", compliant_answers())
        proc = run_cli([path, "--json", "--lang", "fr"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["lang"], "fr")
        self.assertIn("avis juridique", data["disclaimer"])
        proc = run_cli([path, "--lang", "fr"])
        self.assertIn("Synthèse", proc.stdout)

    def test_invalid_file_exits_2(self):
        bad = self.write_text("bad.json", "{broken")
        proc = run_cli([bad])
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("error:", proc.stderr)
        proc = run_cli([bad, "--json"])
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        proc = run_cli([str(self.tmp / "absent.json")])
        self.assertEqual(proc.returncode, 2)
        listing = self.write_text("list.json", "[]")
        self.assertEqual(run_cli([listing]).returncode, 2)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run_cli([]).returncode, 2)
        self.assertEqual(run_cli(["--lang", "de", str(EXAMPLES / "answers.json")]).returncode, 2)

    def test_help_and_version_exit_0(self):
        proc = run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Exit codes", proc.stdout)
        proc = run_cli(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("rgpd-offshore-check", proc.stdout)


if __name__ == "__main__":
    unittest.main()
