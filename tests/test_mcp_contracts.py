import asyncio
import unittest

from tests.support import load_module


python_sim = load_module("vibesilicon_python_sim_contract", "mcp/python-sim-mcp/server.py")
vitis_hls = load_module("vibesilicon_vitis_hls_contract", "mcp/vitis-hls-mcp/server.py")
vivado = load_module("vibesilicon_vivado_contract", "mcp/vivado-mcp/server.py")


class McpContractTests(unittest.TestCase):
    def test_all_servers_load_and_publish_expected_tools(self):
        expected = {
            "python-sim": (
                python_sim,
                {"fxp_sim", "numpy_diff", "load_vectors", "psnr_ssim"},
            ),
            "vitis-hls": (
                vitis_hls,
                {"csim", "csynth", "co_sim", "export"},
            ),
            "vivado": (
                vivado,
                {
                    "backend_capabilities",
                    "synth_design",
                    "place_route",
                    "report_timing",
                    "analyze_checkpoint",
                    "report_cdc",
                    "write_bitstream",
                },
            ),
        }

        for server_name, (module, required_tools) in expected.items():
            with self.subTest(server=server_name):
                published = {tool.name for tool in asyncio.run(module.list_tools())}
                self.assertTrue(required_tools.issubset(published))


if __name__ == "__main__":
    unittest.main()
