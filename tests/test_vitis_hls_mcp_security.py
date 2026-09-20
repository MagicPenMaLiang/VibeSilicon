import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.support import load_module


vitis_hls = load_module("vibesilicon_vitis_hls_security", "mcp/vitis-hls-mcp/server.py")


class VitisHlsMcpSecurityTests(unittest.TestCase):
    def test_project_directory_is_confined_to_declared_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            old_root = vitis_hls.PROJECT_ROOT
            vitis_hls.PROJECT_ROOT = Path(root).resolve()
            try:
                with self.assertRaisesRegex(ValueError, "项目根目录"):
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


if __name__ == "__main__":
    unittest.main()
