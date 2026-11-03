import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import load_module


vitis_hls = load_module("vibesilicon_vitis_hls_security", "mcp/vitis-hls-mcp/server.py")


class VitisHlsMcpSecurityTests(unittest.TestCase):
    def test_project_directory_is_confined_to_declared_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            old_root = vitis_hls.PROJECT_ROOT
            vitis_hls.PROJECT_ROOT = Path(root).resolve()
            try:
                with self.assertRaisesRegex(ValueError, "project root"):
                    vitis_hls._resolve_project_dir(outside)
            finally:
                vitis_hls.PROJECT_ROOT = old_root

    def test_identifiers_and_part_reject_tcl_injection(self):
        with self.assertRaises(ValueError):
            vitis_hls._identifier("top\nexec calc", "top_function")
        with self.assertRaises(ValueError):
            vitis_hls._part("xc7a35t; exec calc")

    def test_csynth_requires_explicit_target_part(self):
        tools = {tool.name: tool for tool in asyncio.run(vitis_hls.list_tools())}
        self.assertIn("part", tools["csynth"].inputSchema["required"])
        self.assertNotIn("default", tools["csynth"].inputSchema["properties"]["part"])

    def test_csim_rejects_injection_paths_before_writing_or_running_tcl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "hls_project"
            project.mkdir()
            (project / "testbench.cpp").write_text("int main() { return 0; }", encoding="utf-8")
            payloads = [
                "testbench.cpp\nputs INJECTED", "testbench.cpp\rputs INJECTED",
                "testbench.cpp;puts INJECTED", "[puts INJECTED].cpp", "$env(HOME).cpp",
                "{testbench.cpp}", "../testbench.cpp", "..\\testbench.cpp",
                str(project / "testbench.cpp"), "C:" + "/testbench.cpp", "C:testbench.cpp",
                "//server/share/testbench.cpp", "missing.cpp", "testbench.txt", ".", "", None,
            ]
            with patch.object(vitis_hls, "PROJECT_ROOT", root):
                with patch.object(vitis_hls, "_write_tcl") as writer, patch.object(vitis_hls, "_run_vitis_hls") as runner:
                    for payload in payloads:
                        with self.subTest(payload=payload):
                            with self.assertRaises((ValueError, FileNotFoundError)):
                                asyncio.run(vitis_hls.call_tool("csim", {
                                    "project_dir": "hls_project", "top_function": "top", "testbench": payload,
                                }))
                    writer.assert_not_called()
                    runner.assert_not_called()

    def test_csim_quotes_valid_nested_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "hls_project"
            testbench = project / "test sources" / "self check.cpp"
            testbench.parent.mkdir(parents=True)
            testbench.write_text("int main() { return 0; }", encoding="utf-8")
            captured = []

            def capture(script, cwd):
                captured.append(script.read_text(encoding="utf-8"))
                self.assertEqual(cwd, project)
                return {"success": True}

            with patch.object(vitis_hls, "PROJECT_ROOT", root), patch.object(vitis_hls, "_run_vitis_hls", side_effect=capture):
                for path in ("test sources/self check.cpp", "test sources\\self check.cpp"):
                    asyncio.run(vitis_hls.call_tool("csim", {
                        "project_dir": "hls_project", "top_function": "top", "testbench": path,
                    }))
            self.assertEqual(len(captured), 2)
            self.assertIn(f"add_files -tb {{{testbench.as_posix()}}}\n", captured[0])
            self.assertEqual(captured[0], captured[1])
            self.assertEqual(len(captured[0].splitlines()), 6)

    def test_testbench_symlink_cannot_escape_its_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "hls_project"
            project.mkdir()
            target = root / "outside.cpp"
            target.write_text("int main() { return 0; }", encoding="utf-8")
            link = project / "testbench.cpp"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "within project_dir"):
                vitis_hls._testbench_path(project, "testbench.cpp")


if __name__ == "__main__":
    unittest.main()
