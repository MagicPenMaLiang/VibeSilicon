import copy
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from tests.support import ROOT, load_module


contract = load_module("vibesilicon_ip_productization_contract", "scripts/ip_productization_contract.py")


class IpProductizationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_path = ROOT / "config" / "ip_productization_profile.json"
        cls.profile = json.loads(cls.profile_path.read_text(encoding="utf-8"))
        cls.profile_sha256 = contract._file_id(cls.profile_path)

    def declaration(self, target="FPGA"):
        names = {item["id"]: item["name"] for item in self.profile["capabilities"]}
        priorities = {item["id"]: item["priority_stars"] for item in self.profile["capabilities"]}
        required = set(self.profile["release_gates"][target])
        capabilities = []
        for index, capability_id in enumerate(contract.CAPABILITY_IDS, start=1):
            status = "PASS" if capability_id in required else "BLOCKED"
            summary = f"Reviewed sanitized acceptance evidence for capability {capability_id}"
            if capability_id == "C4" and target == "FPGA":
                status = "NOT_APPLICABLE"
                summary = "FPGA delivery candidate; ASIC gate not requested"
            capabilities.append(
                {
                    "id": capability_id,
                    "name": names[capability_id],
                    "priority_stars": priorities[capability_id],
                    "status": status,
                    "owner_approved": status == "PASS",
                    "reviewer": f"reviewer-{capability_id.lower()}",
                    "evidence_ids": ["sha256:" + str(index) * 64] if status == "PASS" else [],
                    "acceptance_summary": summary,
                }
            )
        return {
            "schema_version": 1,
            "profile_id": self.profile["profile_id"],
            "ip": {
                "ip_id": "reference-ip",
                "release_candidate": "rc-2026-09",
                "delivery_target": target,
                "owner": "ip-product-owner",
                "author": "rtl-delivery-author",
                "confidentiality": "CONFIDENTIAL_HASH_ONLY",
            },
            "requested_state": "READY_FOR_OWNER_REVIEW",
            "capabilities": capabilities,
            "security": {
                "raw_customer_spec_present": False,
                "raw_customer_rtl_present": False,
                "external_model_export": False,
                "repository_content": "HASHES_AND_SANITIZED_SUMMARIES_ONLY",
            },
        }

    def build(self, target="FPGA"):
        return contract.build_contract(self.declaration(target), self.profile, self.profile_sha256)

    def test_fpga_five_star_gates_are_ready_for_independent_review(self):
        result = self.build()
        self.assertEqual(result["assessment"]["status"], "READY_FOR_OWNER_REVIEW")
        self.assertEqual(result["assessment"]["required_capabilities"], ["C1", "C2", "C3", "C5"])
        self.assertTrue(result["assessment"]["human_release_required"])
        self.assertEqual(result["capabilities"][3]["status"], "NOT_APPLICABLE")
        contract.validate_contract(result, self.profile, self.profile_sha256)
        schema = json.loads(
            (ROOT / "schemas" / "ip_productization_contract.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_asic_delivery_promotes_c4_to_required_gate(self):
        result = self.build("ASIC")
        self.assertEqual(result["assessment"]["required_capabilities"], ["C1", "C2", "C3", "C4", "C5"])
        self.assertEqual(result["assessment"]["status"], "READY_FOR_OWNER_REVIEW")

        declaration = self.declaration("ASIC")
        declaration["capabilities"][3].update(
            {"status": "BLOCKED", "owner_approved": False, "evidence_ids": []}
        )
        blocked = contract.build_contract(declaration, self.profile, self.profile_sha256)
        self.assertEqual(blocked["assessment"]["status"], "BLOCKED")
        self.assertEqual(blocked["assessment"]["blocking_capabilities"], ["C4"])

    def test_five_star_gap_and_draft_request_remain_blocked(self):
        declaration = self.declaration()
        declaration["capabilities"][2].update(
            {"status": "BLOCKED", "owner_approved": False, "evidence_ids": []}
        )
        result = contract.build_contract(declaration, self.profile, self.profile_sha256)
        self.assertEqual(result["assessment"]["blocking_capabilities"], ["C3"])
        self.assertEqual(result["assessment"]["status"], "BLOCKED")

        declaration = self.declaration()
        declaration["requested_state"] = "DRAFT"
        result = contract.build_contract(declaration, self.profile, self.profile_sha256)
        self.assertEqual(result["assessment"]["status"], "BLOCKED")

    def test_priority_and_evidence_claims_fail_closed(self):
        declaration = self.declaration()
        declaration["capabilities"][0]["priority_stars"] = 3
        with self.assertRaisesRegex(contract.IpProductizationContractError, "priority differs"):
            contract.build_contract(declaration, self.profile, self.profile_sha256)

        declaration = self.declaration()
        declaration["capabilities"][1]["evidence_ids"] = []
        with self.assertRaisesRegex(
            contract.IpProductizationContractError, "requires owner approval and evidence"
        ):
            contract.build_contract(declaration, self.profile, self.profile_sha256)

    def test_project_profile_can_use_domain_neutral_custom_names_and_priorities(self):
        profile = copy.deepcopy(self.profile)
        profile["profile_id"] = "project-specific-ip-v1"
        profile["capabilities"][0]["name"] = "streaming_architecture_and_interface"
        profile["capabilities"][3]["priority_stars"] = 5
        declaration = self.declaration()
        declaration["profile_id"] = profile["profile_id"]
        for item, profile_item in zip(declaration["capabilities"], profile["capabilities"], strict=True):
            item["name"] = profile_item["name"]
            item["priority_stars"] = profile_item["priority_stars"]
        result = contract.build_contract(declaration, profile, "sha256:" + "a" * 64)
        self.assertEqual(result["profile_id"], "project-specific-ip-v1")
        self.assertEqual(result["assessment"]["status"], "READY_FOR_OWNER_REVIEW")

    def test_review_independence_and_security_are_enforced(self):
        declaration = self.declaration()
        declaration["capabilities"][0]["reviewer"] = declaration["ip"]["author"]
        with self.assertRaisesRegex(contract.IpProductizationContractError, "independent"):
            contract.build_contract(declaration, self.profile, self.profile_sha256)

        declaration = self.declaration()
        declaration["security"]["raw_customer_spec_present"] = True
        with self.assertRaisesRegex(contract.IpProductizationContractError, "forbidden"):
            contract.build_contract(declaration, self.profile, self.profile_sha256)

        declaration = self.declaration()
        declaration["capabilities"][0]["acceptance_summary"] = "see " + "D:" + "/private/spec.md"
        with self.assertRaisesRegex(contract.IpProductizationContractError, "path or URL"):
            contract.build_contract(declaration, self.profile, self.profile_sha256)

    def test_rehashed_assessment_tamper_is_rebuilt_and_rejected(self):
        result = self.build()
        result["assessment"]["blocking_capabilities"] = ["C6"]
        result["contract_id"] = contract._content_id(result, "contract_id")
        with self.assertRaisesRegex(contract.IpProductizationContractError, "differs from rebuilt"):
            contract.validate_contract(result, self.profile, self.profile_sha256)

    def test_template_is_non_authorizing_and_cli_build_verify_is_standalone(self):
        template = ROOT / "templates" / "ip_productization_contract.template.json"
        with self.assertRaises(contract.IpProductizationContractError):
            contract.validate_declaration(
                json.loads(template.read_text(encoding="utf-8")),
                self.profile,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declaration_path = root / "declaration.json"
            output_path = root / "contract.json"
            declaration_path.write_text(
                json.dumps(self.declaration(), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(
                contract.main(
                    [
                        "build",
                        str(declaration_path),
                        "--profile",
                        str(self.profile_path),
                        "--root",
                        str(root),
                        "--output",
                        str(output_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                contract.main(["verify", str(output_path), "--profile", str(self.profile_path)]),
                0,
            )
            self.assertEqual(
                contract.main(
                    [
                        "build",
                        str(declaration_path),
                        "--profile",
                        str(self.profile_path),
                        "--root",
                        str(root),
                        "--output",
                        str(output_path),
                    ]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
