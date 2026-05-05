from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _on_webclient_bootstrap(self):
        # Set state to disabled before super() so mail_bot skips _init_odoobot()
        if self._is_internal() and self.odoobot_state in [False, "not_initialized"]:
            self.sudo().odoobot_state = "disabled"
        super()._on_webclient_bootstrap()

    def _login(self, credential, user_agent_env):
        if credential and credential.get("login"):
            credential = dict(credential)
            credential["login"] = credential["login"].strip().lower()
        return super()._login(credential, user_agent_env)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("login"):
                vals["login"] = vals["login"].strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("login"):
            vals["login"] = vals["login"].strip().lower()
        return super().write(vals)
