"""Decline a tenant's close request with a reason the tenant reads (MIM-2036)."""

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import clean_context

from .constants import CLOSE_REQUEST_DECLINED_MESSAGE_TYPE
from .utils.helpers import close_request_reason_html


class MaintenanceCloseRequestDeclineWizard(models.TransientModel):
    _name = "maintenance.close.request.decline.wizard"
    _description = "Avslå begäran om avslut"

    # Not readonly: the dialog is opened with default_request_id, and the web
    # client does not send readonly fields on save.
    request_id = fields.Many2one(
        "maintenance.request",
        string="Ärende",
        required=True,
        ondelete="cascade",
    )
    reason = fields.Text(
        string="Orsak",
        required=True,
        help="Visas för hyresgästen på Mina sidor.",
    )

    def action_confirm(self):
        """Post the decline and resolve the request.

        Locked and re-read first: the dialog can sit open while someone else
        declines or the case is closed from the kanban, and a stale second
        answer must not reach the tenant.
        """
        self.ensure_one()
        # The dialog's default_request_id must not leak into the message post.
        request = self.request_id.with_context(clean_context(self.env.context))
        request._lock_for_close_request()
        if not request.close_request_pending:
            raise UserError(_("Begäran om avslut är redan hanterad."))
        reason_html = close_request_reason_html(self.reason)
        if not reason_html:
            raise UserError(_("Ange en orsak till att begäran avslås."))
        # Posted as the deciding user, so MIM-2040 names the sender to the
        # tenant — "Mimers Leverantör - <resursgrupp>" when a contractor
        # declines.
        request.message_post(
            body=reason_html,
            message_type=CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
            subtype_xmlid="mail.mt_note",
        )
        request.write({"close_request_resolved_at": fields.Datetime.now()})
        return {"type": "ir.actions.act_window_close"}
