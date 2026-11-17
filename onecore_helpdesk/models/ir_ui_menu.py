from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _set_name_in_all_languages(self, name):
        """Name the menu ``name`` in en_US and every installed language.

        A menu renamed from XML only gets a new en_US value: the other
        languages keep the translation from the menu's own module.
        """
        self.ensure_one()
        langs = [code for code, _name in self.env["res.lang"].get_installed()]
        self.update_field_translations("name", dict.fromkeys([*langs, "en_US"], name))
        self.env.registry.clear_cache()
