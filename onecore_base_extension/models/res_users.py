from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _on_webclient_bootstrap(self):
        # Set state to disabled before super() so mail_bot skips _init_odoobot()
        if self._is_internal() and self.odoobot_state in [False, "not_initialized"]:
            self.sudo().odoobot_state = "disabled"
        super()._on_webclient_bootstrap()
