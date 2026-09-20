import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import jsonschema

from scripts import asic_toolchain_provenance as provenance


ORFS = "d26bf27e1467d4ac903655694ac31e2ec3f85260"
OPENROAD = "c3e680b01b8bc61eb1dfaf144594b371cc222efc"
YOSYS = "a5af9d690a43744bf6b2cc3dea2717c16b54621c"


class AsicToolchainProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.orfs = self.root / "orfs"
        (self.orfs / "tools" / "OpenROAD").mkdir(parents=True)
        (self.orfs / "tools" / "yosys").mkdir(parents=True)
        (self.orfs / "build_openroad.sh").write_text("build\n", encoding="utf-8")
        (self.orfs / "openroad_deps_prefixes.txt").write_text("deps\n", encoding="utf-8")
        self.binaries = {}
        for name in ("yosys", "openroad", "strmrun"):
            path = self.root / name
            path.write_bytes((name + "\n").encode())
            self.binaries[name] = path
        self.vars = self.root / "vars.sh"
        self.vars.write_text(
            'export SKIP_REPAIR_TIE_FANOUT="0"\nexport SKIP_INCREMENTAL_REPAIR="0"\n',
            encoding="utf-8",
        )
        self.odb = self.root / "2_floorplan.odb"
        self.sdc = self.root / "2_floorplan.sdc"
        self.odb.write_bytes(b"odb")
        self.sdc.write_bytes(b"sdc")
        self.profile = {
            "schema_version": 1,
            "profile_id": "orfs-sky130hd-gcd-v1",
            "reference": {
                "design_id": "orfs-sky130hd-gcd",
                "orfs_revision": ORFS,
                "tool_source_revisions": {"openroad": OPENROAD, "yosys": YOSYS},
            },
        }

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        if argv[0] == "git":
            root = Path(argv[2])
            if root == self.orfs.resolve():
                output = ORFS
            elif root == (self.orfs / "tools" / "OpenROAD").resolve():
                output = OPENROAD
            else:
                output = YOSYS
        elif Path(argv[0]).name == "yosys":
            output = "Yosys 0.68+ (git sha1 a5af9d690)"
        elif Path(argv[0]).name == "strmrun":
            output = "0.30.12 re71272c3b"
        elif kwargs.get("input"):
            output = "repair_tie_fanout=1\nreplace_arith_modules=1"
        else:
            output = "26Q3-1985-gc3e680b01b"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    def collect(self):
        return provenance.collect_provenance(
            self.profile,
            orfs_root=self.orfs,
            openroad=self.binaries["openroad"],
            yosys=self.binaries["yosys"],
            strmrun=self.binaries["strmrun"],
            strmrun_library_dirs=[],
            vars_file=self.vars,
            floorplan_odb=self.odb,
            floorplan_sdc=self.sdc,
            runner=self.runner,
        )

    def test_collect_and_verify_repository_safe_provenance(self):
        result = self.collect()
        provenance.validate_provenance(result, self.profile)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas/asic_toolchain_provenance.schema.json")
            .read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(result)
        self.assertEqual(result["status"], provenance.STATUS)
        self.assertEqual(result["diagnostic_overrides"], [])
        serialized = json.dumps(result)
        self.assertNotIn(str(self.root), serialized)

    def test_source_revision_drift_fails_closed(self):
        self.profile["reference"]["tool_source_revisions"]["openroad"] = "1" * 40
        with self.assertRaisesRegex(
            provenance.AsicToolchainProvenanceError, "source revisions drift"
        ):
            self.collect()

    def test_diagnostic_override_fails_closed(self):
        self.vars.write_text('export SKIP_REPAIR_TIE_FANOUT="1"\n', encoding="utf-8")
        with self.assertRaisesRegex(
            provenance.AsicToolchainProvenanceError, "diagnostic overrides"
        ):
            self.collect()

    def test_missing_command_and_tamper_fail_closed(self):
        original = self.runner

        def missing_command(argv, **kwargs):
            completed = original(argv, **kwargs)
            if kwargs.get("input"):
                completed.stdout = "repair_tie_fanout=1\nreplace_arith_modules=0"
            return completed

        with self.assertRaisesRegex(
            provenance.AsicToolchainProvenanceError, "command surface"
        ):
            provenance.collect_provenance(
                self.profile,
                orfs_root=self.orfs,
                openroad=self.binaries["openroad"],
                yosys=self.binaries["yosys"],
                strmrun=self.binaries["strmrun"],
                strmrun_library_dirs=[],
                vars_file=self.vars,
                floorplan_odb=self.odb,
                floorplan_sdc=self.sdc,
                runner=missing_command,
            )
        result = self.collect()
        tampered = copy.deepcopy(result)
        tampered["compatibility_gate"]["result_status"] = "FAIL"
        with self.assertRaisesRegex(
            provenance.AsicToolchainProvenanceError, "content ID mismatch"
        ):
            provenance.validate_provenance(tampered, self.profile)


if __name__ == "__main__":
    unittest.main()
