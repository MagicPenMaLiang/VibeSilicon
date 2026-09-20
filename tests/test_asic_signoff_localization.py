import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

from scripts import asic_signoff_localization as localization


ROOT = Path(__file__).resolve().parents[1]


class AsicSignoffLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.drc = self.root / "signoff-drc.lyrdb"
        self.lvs = self.root / "lvs.lvsdb"
        self.def_file = self.root / "final.def"
        self.drc.write_text(
            """<report-database>
 <top-cell>top</top-cell>
 <items>
  <item><category>'m3.6'</category><cell>top</cell><multiplicity>1</multiplicity><values><value>polygon: (10,20;12,20;12,22;10,22)</value></values></item>
  <item><category>'li.3'</category><cell>top</cell><multiplicity>1</multiplicity><values><value>edge-pair: (30,40;31,41)|(32,42;33,43)</value></values></item>
 </items>
</report-database>
""",
            encoding="utf-8",
        )
        self.def_file.write_text(
            """VERSION 5.8 ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 2 ;
 - u_clk CLOCK_CELL + PLACED ( 10000 20000 ) N ;
 - u_data DATA_CELL + PLACED ( 30000 40000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
 - VDD ( * VPWR ) + ROUTED met3 100 ( 10000 20000 ) ( 12000 22000 ) ;
END SPECIALNETS
NETS 2 ;
 - clk ( u_clk CLK ) + ROUTED met3 100 ( 10000 20000 ) ( 12000 22000 ) ;
 - data ( u_data D ) + ROUTED li1 100 ( 30000 40000 ) ( 33000 43000 ) ;
END NETS
END DESIGN
""",
            encoding="utf-8",
        )
        self.lvs.write_text(
            """#%lvsdb-klayout
 X(top
  N(1 I(VDD))
 )
 X(TOP
  N(2 I(VDD))
  N(3 I(clk))
 )
Z(
 X(top TOP X
  L(
   M(E B('Net VDD is not matching any net from reference netlist'))
  )
  Z(
   N(1 2 0)
   N(() 3 0)
  )
 )
)
""",
            encoding="utf-8",
        )

    def build(self):
        return localization.build_localization(self.drc, self.lvs, self.def_file)

    def test_builds_rule_geometry_instance_net_and_lvs_cross_references(self):
        value = self.build()
        self.assertEqual(
            value["drc"]["rule_counts"],
            [{"rule": "li.3", "count": 1}, {"rule": "m3.6", "count": 1}],
        )
        first = value["drc"]["violations"][0]
        self.assertEqual(first["bbox_um"], [10.0, 20.0, 12.0, 22.0])
        self.assertEqual(first["nearest_instances"][0]["instance"], "u_clk")
        self.assertEqual(first["nearest_nets"][0]["layer"], "met3")
        self.assertEqual(value["lvs"]["mismatch_count"], 2)
        self.assertEqual(
            value["lvs"]["cross_reference"][1]["reference_net"], "clk"
        )
        self.assertEqual(
            value["lvs"]["cross_reference"][1]["def_matches"][0]["connections"],
            [{"instance": "u_clk", "pin": "CLK"}],
        )
        self.assertFalse(value["security"]["repository_safe"])
        schema = json.loads(
            (ROOT / "schemas/asic_signoff_localization.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schema).validate(value)

    def test_clean_lvs_cross_reference_status_is_accepted(self):
        clean = (
            self.lvs.read_text(encoding="utf-8")
            .replace("X(top TOP X", "X(top TOP 1")
            .replace("N(1 2 0)", "N(1 2 1)")
            .replace("N(() 3 0)", "N(() 3 1)")
        )
        self.lvs.write_text(clean, encoding="utf-8")

        value = self.build()

        self.assertEqual(value["lvs"]["mismatch_count"], 0)
        self.assertEqual(value["lvs"]["cross_reference"], [])

    def test_identity_geometry_and_cross_reference_fail_closed(self):
        value = self.build()
        changed = copy.deepcopy(value)
        changed["drc"]["violations"][0]["rule"] = "m4.6"
        with self.assertRaisesRegex(
            localization.SignoffLocalizationError, "identity"
        ):
            localization.validate_localization(changed)

        self.drc.write_text(
            "<report-database><top-cell>top</top-cell><items>"
            "<item><category>'m3.6'</category><cell>top</cell></item>"
            "</items></report-database>",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            localization.SignoffLocalizationError, "finite geometry"
        ):
            self.build()

        self.setUp()
        self.lvs.write_text(
            self.lvs.read_text(encoding="utf-8").replace("N(() 3 0)", "N(() 999 0)"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            localization.SignoffLocalizationError, "unknown top net"
        ):
            self.build()

    def test_cli_refuses_overwrite_and_verifies(self):
        output = self.root / "localization.json"
        command = [
            sys.executable,
            str(ROOT / "scripts/asic_signoff_localization.py"),
            "build",
            "--drc-report",
            str(self.drc),
            "--lvs-report",
            str(self.lvs),
            "--def-file",
            str(self.def_file),
            "--output",
            str(output),
        ]
        self.assertEqual(subprocess.run(command, check=False).returncode, 0)
        self.assertEqual(subprocess.run(command, check=False).returncode, 1)
        self.assertEqual(
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/asic_signoff_localization.py"),
                    "verify",
                    str(output),
                ],
                check=False,
            ).returncode,
            0,
        )


if __name__ == "__main__":
    unittest.main()
