from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models import ir_module_module
from ..models.ir_module_module import ALLOW_UNINSTALL_PARAM


@tagged("onecore")
class TestIrModuleUninstallProtection(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Module = self.env["ir.module.module"]

    def _module(self, name):
        module = self.Module.search([("name", "=", name)])
        self.assertTrue(module, f"Module {name} not found")
        return module

    def _unprotected_installed_module(self):
        protected = self.Module._onecore_protected_names()
        for module in self.Module.search([("state", "=", "installed")]):
            if module.name in protected:
                continue
            # Must not drag a protected module along when uninstalled either
            dependants = module.downstream_dependencies().mapped("name")
            if not protected.intersection(dependants):
                return module
        self.skipTest("No installed module outside the ONECore dependency tree")

    def test_onecore_modules_and_their_dependencies_are_protected(self):
        for name in ("onecore_base_extension", "mail", "base"):
            self.assertTrue(
                self._module(name).onecore_uninstall_protected,
                f"{name} should be protected",
            )

    def test_unrelated_module_is_not_protected(self):
        self.assertFalse(self._unprotected_installed_module().onecore_uninstall_protected)

    def test_uninstall_onecore_module_is_blocked(self):
        module = self._module("onecore_base_extension")
        with self.assertRaises(UserError):
            module.button_uninstall_wizard()
        with self.assertRaises(UserError):
            module.button_uninstall()
        self.assertEqual(module.state, "installed")

    def test_uninstall_dependency_of_onecore_is_blocked(self):
        module = self._module("mail")
        with self.assertRaises(UserError):
            module.button_uninstall_wizard()
        with self.assertRaises(UserError):
            module.button_uninstall()
        self.assertEqual(module.state, "installed")

    def test_module_uninstall_is_blocked(self):
        # Public RPC method that bypasses button_uninstall
        module = self._module("onecore_base_extension")
        with self.assertRaises(UserError):
            module.module_uninstall()
        self.assertEqual(module.state, "installed")

    def test_writing_to_remove_state_is_blocked(self):
        for name in ("onecore_base_extension", "mail"):
            module = self._module(name)
            with self.assertRaises(UserError):
                module.write({"state": "to remove"})
            self.assertEqual(module.state, "installed")

    def test_context_flag_does_not_bypass_check(self):
        module = self._module("onecore_base_extension")
        with self.assertRaises(UserError):
            module.with_context(onecore_allow_uninstall=True).button_uninstall()

    def test_config_parameter_bypasses_check_outside_requests(self):
        self.env["ir.config_parameter"].set_param(ALLOW_UNINSTALL_PARAM, "True")
        # Does not raise
        self._module("onecore_base_extension")._check_protected_uninstall()

    def test_config_parameter_is_ignored_during_http_requests(self):
        self.env["ir.config_parameter"].set_param(ALLOW_UNINSTALL_PARAM, "True")
        module = self._module("onecore_base_extension")
        with patch(f"{ir_module_module.__name__}.request", MagicMock()):
            with self.assertRaises(UserError):
                module._check_protected_uninstall()

    def test_unrelated_module_can_open_uninstall_wizard(self):
        action = self._unprotected_installed_module().button_uninstall_wizard()
        self.assertEqual(action["res_model"], "base.module.uninstall")
