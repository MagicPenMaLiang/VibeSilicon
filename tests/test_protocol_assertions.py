import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


assertions = load_module(
    "vibesilicon_protocol_assertions", "scripts/quality_gate/protocol_assertions.py"
)
FIXTURES = ROOT / "tests" / "fixtures" / "protocol"


class ProtocolAssertionTests(unittest.TestCase):
    def test_spi_mode0_pass_trace(self):
        report = assertions.analyze(FIXTURES / "spi_mode0_pass.json", root=ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"], {"violations": 0, "blocking": 0})
        self.assertIsNone(report["waveform"])
        self.assertEqual(report["evidence_id"], "sha256:" + report["trace_sha256"])

    def test_spi_partial_byte_fails_and_writes_waveform(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as output:
            report = assertions.analyze(
                FIXTURES / "spi_partial_byte_fail.json",
                root=ROOT,
                waveform_dir=Path(output),
            )
            waveform = ROOT / report["waveform"]
            content = waveform.read_text(encoding="ascii")
        rules = {item["rule_id"] for item in report["violations"]}
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SPI-P002", rules)
        self.assertIn("SPI-P003", rules)
        self.assertIn("$var wire 1 ! violation", content)

    def test_axi_stream_accepts_stable_backpressure(self):
        report = assertions.analyze(FIXTURES / "axi_stream_pass.json", root=ROOT)
        self.assertEqual(report["status"], "PASS")

    def test_axi_stream_payload_change_is_blocking(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as output:
            report = assertions.analyze(
                FIXTURES / "axi_stream_unstable_fail.json",
                root=ROOT,
                waveform_dir=Path(output),
            )
            waveform_exists = (ROOT / report["waveform"]).is_file()
        rules = {item["rule_id"] for item in report["violations"]}
        self.assertIn("AXIS-P001", rules)
        self.assertIn("AXIS-P003", rules)
        self.assertTrue(waveform_exists)

    def test_axi_stream_valid_cannot_drop_before_handshake(self):
        value = json.loads((FIXTURES / "axi_stream_pass.json").read_text(encoding="utf-8"))
        value["trace_id"] = "AXIS-FAIL-VALID-DROP"
        value["config"]["expected_beats"] = []
        value["samples"] = value["samples"][:3]
        value["samples"][2]["signals"]["tvalid"] = 0
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            trace = Path(temp_dir) / "trace.json"
            trace.write_text(json.dumps(value), encoding="utf-8")
            report = assertions.analyze(trace, root=ROOT)
        self.assertIn("AXIS-P001", {item["rule_id"] for item in report["violations"]})

    def test_axi_timeout_tlast_and_incomplete_packet_rules(self):
        value = json.loads((FIXTURES / "axi_stream_pass.json").read_text(encoding="utf-8"))
        value["trace_id"] = "AXIS-FAIL-CONTROL"
        value["config"]["expected_beats"] = []
        value["config"]["max_stall_cycles"] = 1
        value["samples"] = [
            {"cycle": 0, "signals": {"reset_n": 1, "tvalid": 0, "tready": 0, "tdata": 0, "tlast": 1}},
            {"cycle": 1, "signals": {"reset_n": 1, "tvalid": 1, "tready": 0, "tdata": 1, "tlast": 0}},
            {"cycle": 2, "signals": {"reset_n": 1, "tvalid": 1, "tready": 0, "tdata": 1, "tlast": 0}},
            {"cycle": 3, "signals": {"reset_n": 1, "tvalid": 1, "tready": 1, "tdata": 1, "tlast": 0}},
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            trace = Path(temp_dir) / "trace.json"
            trace.write_text(json.dumps(value), encoding="utf-8")
            report = assertions.analyze(trace, root=ROOT)
        rules = {item["rule_id"] for item in report["violations"]}
        self.assertTrue({"AXIS-P002", "AXIS-P004", "AXIS-P005"}.issubset(rules))

    def test_spi_idle_and_timeout_rules(self):
        value = json.loads((FIXTURES / "spi_mode0_pass.json").read_text(encoding="utf-8"))
        value["trace_id"] = "SPI-FAIL-TIMING"
        value["samples"][0]["signals"]["sck"] = 1
        value["samples"][4]["cycle"] = 7
        for index in range(5, len(value["samples"])):
            value["samples"][index]["cycle"] += 3
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            trace = Path(temp_dir) / "trace.json"
            trace.write_text(json.dumps(value), encoding="utf-8")
            report = assertions.analyze(trace, root=ROOT)
        rules = {item["rule_id"] for item in report["violations"]}
        self.assertIn("SPI-P001", rules)
        self.assertIn("SPI-P004", rules)

    def test_malformed_and_outside_traces_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            trace = Path(outside) / "trace.json"
            trace.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(assertions.ProtocolTraceError, "outside"):
                assertions.analyze(trace, root=ROOT)
        value = json.loads((FIXTURES / "spi_mode0_pass.json").read_text(encoding="utf-8"))
        value["samples"][1]["signals"]["mosi"] = "x"
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            trace = Path(temp_dir) / "trace.json"
            trace.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(assertions.ProtocolTraceError, "must be 0 or 1"):
                assertions.analyze(trace, root=ROOT)

    def test_cli_failure_returns_one_and_writes_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            output = Path(temp_dir) / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/quality_gate/protocol_assertions.py"),
                    str(FIXTURES / "spi_partial_byte_fail.json"),
                    "--root",
                    str(ROOT),
                    "--waveform-dir",
                    temp_dir,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(report["status"], "FAIL")

    def test_report_schema_is_versioned(self):
        schema = json.loads(
            (ROOT / "schemas/protocol_assertion_report.schema.json").read_text(encoding="utf-8")
        )
        report = assertions.analyze(FIXTURES / "spi_mode0_pass.json", root=ROOT)
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(set(report), set(schema["required"]))

    def test_bindable_sva_templates_have_contracts_and_assertions(self):
        template_dir = ROOT / "templates" / "rtl" / "assertions"
        for name in ("spi_mode0_assertions.sv", "axi_stream_assertions.sv"):
            text = (template_dir / name).read_text(encoding="utf-8")
            self.assertIn("// Module       :", text)
            self.assertIn("assert property", text)
            self.assertIn("`default_nettype none", text)
            self.assertTrue(text.rstrip().endswith("`default_nettype wire"))


if __name__ == "__main__":
    unittest.main()
