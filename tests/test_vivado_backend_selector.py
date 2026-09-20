import tempfile
import unittest
from pathlib import Path

from scripts.vivado_backend import BackendBlockedError
from scripts.vivado_backend_selector import close_vivado_backend, select_vivado_backend


class VivadoBackendSelectorTests(unittest.TestCase):
    def test_native_is_the_explicit_default(self):
        with tempfile.TemporaryDirectory() as root:
            backend = select_vivado_backend(
                root=Path(root),
                vivado_bin="vivado",
                settings_path=None,
                environment={},
            )
        self.assertEqual(backend.name, "native")

    def test_native_can_be_selected_explicitly(self):
        with tempfile.TemporaryDirectory() as root:
            backend = select_vivado_backend(
                root=Path(root),
                vivado_bin="vivado",
                settings_path=None,
                environment={"VIBESILICON_VIVADO_BACKEND": "native"},
            )
        self.assertEqual(backend.name, "native")

    def test_unbundled_backend_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(BackendBlockedError, "separately reviewed adapter"):
                select_vivado_backend(
                    root=Path(root),
                    vivado_bin="vivado",
                    settings_path=None,
                    environment={"VIBESILICON_VIVADO_BACKEND": "external"},
                )

    def test_close_is_safe_for_native_backend(self):
        with tempfile.TemporaryDirectory() as root:
            backend = select_vivado_backend(
                root=Path(root),
                vivado_bin="vivado",
                settings_path=None,
                environment={},
            )
            close_vivado_backend(backend)


if __name__ == "__main__":
    unittest.main()
