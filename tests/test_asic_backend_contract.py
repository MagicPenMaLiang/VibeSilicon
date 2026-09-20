import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import jsonschema

from scripts import asic_backend_contract as asic


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/asic_backend_policy.json"


class AsicBackendContractTests(unittest.TestCase):
    def policy(self):
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def schema(self):
        return json.loads(
            (ROOT / "schemas/asic_backend_contract.schema.json").read_text(
                encoding="utf-8"
            )
        )

    def test_reviewed_policy_builds_dormant_a01_contract(self):
        result = asic.build_contract(self.policy())
        self.assertEqual(result["status"], "A01_PART_A_CONTRACT_READY")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["pdk_configured"])
        self.assertFalse(result["design_configured"])
        self.assertFalse(result["asic_metrics_mixed_with_fpga"])
        self.assertEqual(result["closure_status"], "BLOCKED")
        asic.validate_contract(result, self.policy())
        jsonschema.Draft202012Validator(self.schema()).validate(result)

    def test_policy_drift_and_contract_tamper_fail_closed(self):
        policy = self.policy()
        changed = copy.deepcopy(policy)
        changed["security"]["network_access"] = True
        with self.assertRaisesRegex(asic.AsicContractError, "security"):
            asic.validate_policy(changed)
        result = asic.build_contract(policy)
        result["execution_authorized"] = True
        with self.assertRaisesRegex(asic.AsicContractError, "content ID"):
            asic.validate_contract(result, policy)

    def test_missing_tools_are_blocked_without_invoking_runner(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner must not be called for missing tools")

        result = asic.discover_capabilities(
            self.policy(), runner=runner, resolver=lambda _name: None
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual([item["status"] for item in result["tools"]], ["MISSING"] * 3)
        self.assertEqual(calls, [])
        asic.validate_capabilities(result, self.policy())
        jsonschema.Draft202012Validator(self.schema()).validate(result)

    def test_fixed_read_only_version_probes_can_report_present_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tools = {}
            for name in ("yosys", "openroad", "strmrun"):
                path = directory / f"{name}.exe"
                path.write_bytes((name + " binary").encode("ascii"))
                tools[name] = str(path)
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                name = Path(command[0]).stem
                return subprocess.CompletedProcess(command, 0, f"{name} 1.0\n", "")

            result = asic.discover_capabilities(
                self.policy(), runner=runner, resolver=tools.get
            )
        self.assertEqual(result["status"], "CAPABILITIES_PRESENT_UNQUALIFIED")
        self.assertEqual([item["status"] for item in result["tools"]], ["PASS"] * 3)
        self.assertTrue(all(item["binary_sha256"].startswith("sha256:") for item in result["tools"]))
        self.assertTrue(all(call[1]["shell"] is False for call in calls))
        self.assertEqual(calls[0][0][1:], ["-V"])
        self.assertEqual(calls[1][0][1:], ["-version"])
        self.assertEqual(calls[2][0][1:], ["--version"])
        self.assertFalse(result["execution_authorized"])
        asic.validate_capabilities(result, self.policy())

    def test_failed_probe_is_error_and_cannot_keep_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tool.exe"
            path.write_bytes(b"tool")

            def runner(command, **_kwargs):
                return subprocess.CompletedProcess(command, 2, "", "failed")

            result = asic.discover_capabilities(
                self.policy(), runner=runner, resolver=lambda _name: str(path)
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual([item["status"] for item in result["tools"]], ["ERROR"] * 3)
        self.assertTrue(all(item["version"] is None for item in result["tools"]))
        self.assertTrue(all(item["binary_sha256"] is None for item in result["tools"]))

    def test_capability_context_and_status_cannot_be_rewritten(self):
        result = asic.discover_capabilities(self.policy(), resolver=lambda _name: None)
        changed = copy.deepcopy(result)
        changed["status"] = "CAPABILITIES_PRESENT_UNQUALIFIED"
        changed["capability_id"] = asic._content_id(changed, "capability_id")
        with self.assertRaisesRegex(asic.AsicContractError, "aggregate status"):
            asic.validate_capabilities(changed, self.policy())
        changed = copy.deepcopy(result)
        changed["execution_authorized"] = True
        changed["capability_id"] = asic._content_id(changed, "capability_id")
        with self.assertRaisesRegex(asic.AsicContractError, "cannot grant"):
            asic.validate_capabilities(changed, self.policy())

    def test_build_cli_is_exclusive_and_discover_remains_blocked_locally(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path = root / "config" / "asic_backend_policy.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(
                json.dumps(self.policy(), ensure_ascii=False), encoding="utf-8"
            )
            output = Path("results") / "contract.json"
            arguments = [
                "build",
                "--root",
                str(root),
                "--policy",
                "config/asic_backend_policy.json",
                "--output",
                str(output),
            ]
            self.assertEqual(asic.main(arguments), 0)
            self.assertEqual(asic.main(arguments), 2)
            value = json.loads((root / output).read_text(encoding="utf-8"))
            asic.validate_contract(value, self.policy())

    def test_cli_surface_has_no_execute_action(self):
        source = (ROOT / "scripts/asic_backend_contract.py").read_text(encoding="utf-8")
        self.assertIn('choices=("build", "discover", "verify")', source)
        self.assertNotIn('choices=("build", "discover", "verify", "execute")', source)


if __name__ == "__main__":
    unittest.main()
