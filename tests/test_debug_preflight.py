import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.debug_preflight import check_run_plan
from scripts.evidence_contract import sha256_bytes

ROLES = ("player", "image", "device_tree", "golden", "host_validator")
CHECKS = {
    "persistent_marker": {"consumed": False}, "finalizer": {"entries": 0},
    "staging": {"entries": 0}, "transport": {"entries": 0},
    "trace": {"baseline_matches": True}, "services": {"restored": True},
}


def files(root):
    return {str(p.relative_to(root)): sha256_bytes(p.read_bytes())
            for p in root.rglob("*") if p.is_file()}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = "packages/try1-2026-11-10"
        evidence = "evidence/try1-2026-11-10"
        (self.root / package).mkdir(parents=True)
        (self.root / evidence).mkdir(parents=True)
        artifacts = []
        for role in ROLES:
            data = ("synthetic " + role).encode()
            path = package + "/" + role + ".txt"
            (self.root / path).write_bytes(data)
            artifacts.append({"path": path, "sha256": sha256_bytes(data)})
        checks = copy.deepcopy(CHECKS)
        checks["image"] = {"sha256": artifacts[1]["sha256"]}
        self.capture = {"schema_version": "1.0", "boot_id": "boot-1", "collector_id": "collector-1",
                        "sequence_start": 1, "sequence_end": 2, "checks": checks}
        self.plan = {"schema_version": "1.0", "attempt": "try1", "date": "2026-11-10",
                     "package_path": package, "evidence_path": evidence, "bound_boot": "boot-1",
                     "artifacts": artifacts, "bindings": {role: package + "/" + role + ".txt" for role in ROLES},
                     "capture_path": evidence + "/capture.json", "capture_sha256": ""}
        self.save_capture()

    def save_capture(self):
        data = json.dumps(self.capture).encode()
        (self.root / self.plan["capture_path"]).write_bytes(data)
        self.plan["capture_sha256"] = sha256_bytes(data)

    def blocked(self, plan=None):
        result = check_run_plan(self.root, self.plan if plan is None else plan)
        self.assertEqual(result["scope"], "offline_run_plan_validation")
        self.assertEqual(result["offline_checks"], "BLOCKED")
        self.assertTrue(result["reasons"])
        for key in ("eligible_for_hardware", "live_state_verified", "execution_authorized", "hardware_validated"):
            self.assertIs(result[key], False)

    def test_valid_immutable(self):
        original, before = copy.deepcopy(self.plan), files(self.root)
        result = check_run_plan(self.root, self.plan)
        self.assertEqual(result["offline_checks"], "PASS")
        self.assertEqual(result["scope"], "offline_run_plan_validation")
        for key in ("eligible_for_hardware", "live_state_verified", "execution_authorized", "hardware_validated"):
            self.assertIs(result[key], False)
        self.assertGreaterEqual(len(result["limitations"]), 3)
        self.assertEqual(original, self.plan)
        self.assertEqual(before, files(self.root))

    def test_bad_plan(self):
        cases = [("date", "2026-02-30"), ("attempt", "../x"), ("package_path", "packages/other"),
                 ("evidence_path", "packages/try1-2026-11-10"), ("bound_boot", "different"),
                 ("capture_sha256", "sha256:" + "0" * 64), ("commands", ["reboot"])]
        for field, value in cases:
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan[field] = value
                self.blocked(plan)

    def test_unknown_and_nonready_capture(self):
        bad = {"persistent_marker": {"consumed": True}, "finalizer": {"entries": 1},
               "staging": {"entries": 1}, "transport": {"entries": 1},
               "trace": {"baseline_matches": False}, "services": {"restored": False},
               "image": {"sha256": "sha256:" + "0" * 64}}
        original = copy.deepcopy(self.capture)
        for name in bad:
            for value in (None, bad[name]):
                with self.subTest(name=name, value=value):
                    self.capture = copy.deepcopy(original)
                    self.capture["checks"][name] = value
                    self.save_capture()
                    self.blocked()

    def test_invalid_capture(self):
        original = copy.deepcopy(self.capture)
        for mutation in ("missing", "extra", "bool_integer", "backwards", "wrong_boot", "commands", "float", "float_entries"):
            with self.subTest(mutation=mutation):
                self.capture = copy.deepcopy(original)
                if mutation == "missing":
                    del self.capture["checks"]["trace"]
                elif mutation == "extra":
                    self.capture["checks"]["other"] = None
                elif mutation == "bool_integer":
                    self.capture["sequence_start"] = True
                elif mutation == "backwards":
                    self.capture["sequence_start"] = 3
                elif mutation == "wrong_boot":
                    self.capture["boot_id"] = "boot-2"
                elif mutation == "commands":
                    self.capture["commands"] = ["reboot"]
                elif mutation == "float":
                    self.capture["sequence_start"] = 1.0
                else:
                    self.capture["checks"]["finalizer"]["entries"] = 0.0
                self.save_capture()
                self.blocked()

    def test_artifact_closure(self):
        for mutation in ("hash", "duplicate", "unbound", "duplicate_binding", "escape", "absent", "outside", "capture_outside"):
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan)
                if mutation == "hash":
                    plan["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
                elif mutation == "duplicate":
                    plan["artifacts"].append(copy.deepcopy(plan["artifacts"][0]))
                elif mutation == "unbound":
                    plan["bindings"]["player"] = "missing.txt"
                elif mutation == "duplicate_binding":
                    plan["bindings"]["player"] = plan["bindings"]["image"]
                elif mutation == "escape":
                    plan["artifacts"][0]["path"] = "../x"
                elif mutation == "absent":
                    plan["artifacts"][0]["path"] = "missing.txt"
                elif mutation == "outside":
                    plan["artifacts"][0]["path"] = plan["bindings"]["player"] = "player.txt"
                else:
                    plan["capture_path"] = "capture.json"
                self.blocked(plan)

    def test_bad_json(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.subTest(raw=raw):
                (self.root / self.plan["capture_path"]).write_bytes(raw)
                self.plan["capture_sha256"] = sha256_bytes(raw)
                self.blocked()

    def test_bad_path_types_and_actionable_diagnostics(self):
        for root in (None, [], {}, 1):
            with self.subTest(root=root):
                result = check_run_plan(root, self.plan)
                self.assertEqual(result["offline_checks"], "BLOCKED")
                self.assertFalse(result["execution_authorized"])
        missing = copy.deepcopy(self.plan)
        del missing["bound_boot"]
        self.assertIn("bound_boot", check_run_plan(self.root, missing)["reasons"][0])
        invalid = copy.deepcopy(self.plan)
        invalid["artifacts"][0]["sha256"] = "invalid"
        self.assertIn("/artifacts/0/sha256", check_run_plan(self.root, invalid)["reasons"][0])
        changed = copy.deepcopy(self.plan)
        changed["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
        self.assertIn(changed["artifacts"][0]["path"],
                      check_run_plan(self.root, changed)["reasons"][0])

    def test_cli_no_effect(self):
        path = self.root / "plan.json"
        path.write_text(json.dumps(self.plan), encoding="utf-8")
        before = files(self.root)
        cmd = [sys.executable, "-m", "scripts.debug_preflight", "--root", str(self.root), "--plan", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["offline_checks"], "PASS")
        path.write_text('{"x":NaN}', encoding="utf-8")
        before["plan.json"] = sha256_bytes(path.read_bytes())
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["offline_checks"], "BLOCKED")
        self.assertEqual(before, files(self.root))


if __name__ == "__main__":
    unittest.main()
