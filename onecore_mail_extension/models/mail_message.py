from odoo import models, fields

class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    message_type = fields.Selection(
        selection_add=[
            ("from_tenant", "From tenant"),
            ("tenant_sms", "Sent to tenant by SMS"),
            ("tenant_mail", "Sent to tenant by email"),
            ("tenant_sms_error", "Sent to tenant by SMS, but sending failed"),
            ("tenant_mail_error", "Sent to tenant by email, but sending failed"),
        ],
        ondelete={
            "from_tenant": "set default",
            "tenant_sms": "set default",
            "tenant_mail": "set default",
            "tenant_sms_error": "set default",
            "tenant_mail_error": "set default",
        },
    )
