from odoo import api, models


class MailBot(models.AbstractModel):
    _inherit = "mail.bot"

    def _apply_logic(self, channel, values, command=None):
        # Completely disable OdooBot responses
        return

    @api.model
    def _register_hook(self):
        """Disable OdooBot for all existing users and remove OdooBot channels on module load."""
        super()._register_hook()
        odoobot = self.env.ref("base.partner_root", raise_if_not_found=False)
        if not odoobot:
            return

        # Set all users to disabled
        self.env.cr.execute(
            "UPDATE res_users SET odoobot_state = 'disabled' "
            "WHERE odoobot_state IS NULL OR odoobot_state != 'disabled'"
        )

        # Remove existing OdooBot direct message channels
        channels = self.env["discuss.channel"].search([
            ("channel_type", "=", "chat"),
            ("channel_member_ids.partner_id", "=", odoobot.id),
        ])
        if channels:
            channels.sudo().unlink()
