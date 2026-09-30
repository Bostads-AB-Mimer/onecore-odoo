from odoo import _, fields, models
from odoo.exceptions import UserError

PROTECTED_PREFIX = "onecore_"
# exclude_states for (up|down)stream_dependencies that keeps only installed modules
NOT_INSTALLED_STATES = ("uninstalled", "uninstallable", "to remove")


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    onecore_uninstall_protected = fields.Boolean(
        compute="_compute_onecore_uninstall_protected",
    )

    def _compute_onecore_uninstall_protected(self):
        protected = self._onecore_protected_names()
        for module in self:
            module.onecore_uninstall_protected = module.name in protected

    def _onecore_protected_names(self):
        """ONECore modules plus every installed module they depend on, directly
        or indirectly. Uninstalling any of them would break or remove ONECore."""
        onecore = self.sudo().search(
            [
                ("name", "=like", PROTECTED_PREFIX.replace("_", "\\_") + "%"),
                ("state", "not in", NOT_INSTALLED_STATES),
            ]
        )
        # Walk the dependency graph ourselves: upstream_dependencies() leaves out base
        protected = set()
        todo = set(onecore.mapped("name"))
        while todo:
            protected |= todo
            todo = (
                set(
                    self.env["ir.module.module.dependency"]
                    .sudo()
                    .search([("module_id.name", "in", list(todo))])
                    .mapped("name")
                )
                - protected
            )
        return protected

    def _check_protected_uninstall(self):
        if self.env.context.get("onecore_allow_uninstall"):
            return
        # Uninstalling a module also removes everything that depends on it
        affected = self | self.downstream_dependencies(
            exclude_states=NOT_INSTALLED_STATES
        )
        protected = self._onecore_protected_names()
        blocked = sorted(name for name in affected.mapped("name") if name in protected)
        if blocked:
            raise UserError(
                _(
                    "Följande moduler krävs av ONECore och kan inte avinstalleras: %s",
                    ", ".join(blocked),
                )
            )

    def button_uninstall_wizard(self):
        self._check_protected_uninstall()
        return super().button_uninstall_wizard()

    def button_uninstall(self):
        self._check_protected_uninstall()
        return super().button_uninstall()
