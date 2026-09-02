from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

import logging
import requests
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)

# ============================================================================
# HÄNDELSELOGG CATEGORIES (MIM-1956)
# ============================================================================
# Categories for the chatter log filter. Derived, never stored, so the rules
# apply retroactively to every existing message and cannot go stale.
LOG_CATEGORY_EVENT = "event"
LOG_CATEGORY_INTERNAL_NOTE = "internal_note"
LOG_CATEGORY_COMMUNICATION = "communication"


class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    informs_opposite_party = fields.Boolean(
        string="Informera motparten",
        default=False,
        help="Loggnoteringar som markeras här visar dialogindikatorn (orange) "
        "för motparten — Mimer ⇄ extern entreprenör.",
    )
    is_dialog_unread_for_side = fields.Boolean(
        string="Okvitterad dialognotering",
        compute="_compute_is_dialog_unread_for_side",
        store=False,
    )
    # Pin state reuses the native mail.message.pinned_at field (truthiness =
    # pinned). We add only attribution + the permission flag. Odoo's Discuss pin
    # uses the same field but its UI is gated to discuss.channel, so it never
    # touches maintenance/res.partner chatter.
    pinned_by_id = fields.Many2one(
        "res.users",
        string="Fäst av",
    )
    pinned_by_name = fields.Char(
        string="Fäst av (namn)",
        compute="_compute_pinned_by_name",
        store=False,
    )
    can_pin = fields.Boolean(
        string="Får fästa",
        compute="_compute_can_pin",
        store=False,
    )

    @api.depends(
        "author_id",
        "date",
        "message_type",
        "subtype_id",
        "model",
        "res_id",
        "informs_opposite_party",
    )
    def _compute_is_dialog_unread_for_side(self):
        # Highlights log notes from the opposite party (internal Mimer vs
        # external contractor) on maintenance.request until acknowledged via
        # action_acknowledge_dialog on the parent record. The classification is
        # owned by maintenance.request._dialog_unread_message_ids so the rules
        # are not duplicated here.
        for message in self:
            message.is_dialog_unread_for_side = False

        # onecore_mail_extension does not declare a dependency on the
        # maintenance module, so guard against it being absent.
        if "maintenance.request" not in self.env:
            return

        unread_ids = self.env["maintenance.request"]._dialog_unread_message_ids(self)
        for message in self:
            if message.id in unread_ids:
                message.is_dialog_unread_for_side = True

    @api.depends("pinned_by_id")
    def _compute_pinned_by_name(self):
        for message in self:
            message.pinned_by_name = message.pinned_by_id.name or ""

    def _user_can_pin(self):
        # Central gate for who may pin chatter messages. Currently everyone
        # (internal users AND external contractors) may pin. To restrict this
        # later, change ONLY this method (e.g. return a group check) — both the
        # can_pin field and the action_toggle_pin guard route through here.
        return True

    @api.depends_context("uid")
    def _compute_can_pin(self):
        # depends_context("uid") keeps the cache keyed per user, so once
        # _user_can_pin becomes user-dependent it takes effect without a stale
        # value being shared across users in the same transaction.
        can_pin = self._user_can_pin()
        for message in self:
            message.can_pin = can_pin

    def _to_store_defaults(self, target):
        # Exposes is_dialog_unread_for_side (dialog highlight) plus the pin
        # attribution/permission fields to the OWL chatter store. The pin state
        # itself is the native pinned_at, already serialized by base Odoo.
        return super()._to_store_defaults(target) + [
            "is_dialog_unread_for_side",
            "pinned_by_name",
            "can_pin",
            "onecore_log_category",
        ]

    @api.model
    def _fetch_pinned_messages(self, thread):
        # Returns every pinned message on the thread, ignoring the chatter's
        # 30-message pagination window. The web chatter only holds the most
        # recent FETCH_LIMIT messages, so a note pinned before that window would
        # otherwise never reach the "Fästa" section until the user scrolled it
        # into view (MIM-1301 review). limit=None lifts that cap; passing the
        # thread scopes the query to this record and excludes user_notification.
        return self._message_fetch(
            domain=[("pinned_at", "!=", False)], thread=thread, limit=None
        )["messages"]

    def action_toggle_pin(self):
        # Shared pin toggle for the chatter "Fästa" section. Anyone who passes
        # _user_can_pin (currently everyone, incl. external contractors) may
        # toggle. Pin state is the native pinned_at (truthiness). Writes with
        # sudo because pinning is a cross-user action on messages the caller does
        # not own, and mail.message write ACLs otherwise restrict edits to the
        # author. Read access to the message is still enforced naturally by the
        # self.pinned_at read below.
        self.ensure_one()
        if not self._user_can_pin():
            raise AccessError(_("Du har inte behörighet att fästa noteringar."))
        if self.pinned_at:
            self.sudo().write({"pinned_at": False, "pinned_by_id": False})
        else:
            self.sudo().write(
                {
                    "pinned_at": fields.Datetime.now(),
                    "pinned_by_id": self.env.user.id,
                }
            )
        return {
            "pinned_at": self.pinned_at,
            "pinned_by_name": self.pinned_by_name,
        }

    # MIM-1956 — adding a type here has a side effect on the händelselogg
    # filter: anything that is neither "comment" nor "notification" is
    # classified as Kommunikation (see _onecore_log_category_for), i.e. it
    # shows up in the filter handläggare read as the tenant conversation.
    # Decide whether that is right, then add the type to EXPECTED_CATEGORIES in
    # tests/test_log_category.py — the suite fails until you do.
    message_type = fields.Selection(
        selection_add=[
            ("from_tenant", "From tenant"),
            # MIM-1960 — our confirmation that a Mina-sidor message was read.
            # Deliberately NOT prefixed tenant_: create() treats every tenant_*
            # type as an outbound SMS/email dispatch, and this must stay silent.
            ("receipt_to_tenant", "Kvittens till hyresgäst"),
            ("tenant_sms", "Sent to tenant by SMS"),
            ("tenant_mail", "Sent to tenant by email"),
            ("tenant_mail_and_sms", "Sent to tenant by email and SMS"),
            ("failed_tenant_sms", "Sent to tenant by SMS, but sending failed"),
            ("failed_tenant_mail", "Sent to tenant by email, but sending failed"),
            (
                "failed_tenant_mail_and_sms",
                "Sent to tenant by email and SMS, but both sending failed",
            ),
            (
                "tenant_mail_ok_and_sms_failed",
                "Sent to tenant by email and SMS, but sending SMS failed",
            ),
            (
                "tenant_mail_failed_and_sms_ok",
                "Sent to tenant by email and SMS, but sending email failed",
            ),
        ],
        ondelete={
            "from_tenant": "set default",
            "receipt_to_tenant": "set default",
            "tenant_sms": "set default",
            "tenant_mail": "set default",
            "tenant_mail_and_sms": "set default",
            "failed_tenant_sms": "set default",
            "failed_tenant_mail": "set default",
            "failed_tenant_mail_and_sms": "set default",
            "tenant_mail_ok_and_sms_failed": "set default",
            "tenant_mail_failed_and_sms_ok": "set default",
        },
    )

    def get_core_api(self):
        return core_api.CoreApi(self.env)

    def _send_email(
        self,
        to_email,
        subject,
        text,
        team_name=None,
        contact_code=None,
        triggered_by_user=None,
    ):
        data = {
            "to": to_email,
            "subject": subject,
            "text": text,
            "externalContractorName": team_name,
            "contactCode": contact_code,
            "triggeredByUser": triggered_by_user,
        }

        try:
            response = self.get_core_api().request(
                "POST", "/work-orders/send-email", data=data
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    def _send_sms(
        self,
        phone_number,
        text,
        team_name=None,
        contact_code=None,
        triggered_by_user=None,
    ):
        data = {
            "phoneNumber": phone_number,
            "text": text,
            "externalContractorName": team_name,
            "contactCode": contact_code,
            "triggeredByUser": triggered_by_user,
        }

        try:
            response = self.get_core_api().request(
                "POST", "/work-orders/send-sms", data=data
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values["message_type"].startswith("tenant_"):
                the_record = self.env["maintenance.request"].search(
                    [("id", "=", values["res_id"])]
                )
                subject = f"Ang. serviceanmälan: {the_record.name}"
                body = values["body"].replace("<br>", "\\n")

                team_name = (
                    the_record.maintenance_team_id.name
                    if self.env.user.has_group(
                        "onecore_maintenance_extension.group_external_contractor"
                    )
                    else None
                )

                # Attach the dispatch to the tenant's timeline (contactCode) and
                # record who triggered it, so OneCore can write a communication
                # log entry for the outbound SMS/email.
                contact_code = the_record.tenant_id.contact_code
                triggered_by_user = self.env.user.name

                # send by sms
                if values["message_type"] == "tenant_sms":
                    send_sms_result = self._send_sms(
                        the_record.tenant_id.phone_number,
                        body,
                        team_name,
                        contact_code,
                        triggered_by_user,
                    )

                    if send_sms_result is None:
                        values["message_type"] = "failed_tenant_sms"

                # send by email
                if values["message_type"] == "tenant_mail":
                    send_email_result = self._send_email(
                        the_record.tenant_id.email_address,
                        subject,
                        body,
                        team_name,
                        contact_code,
                        triggered_by_user,
                    )

                    if send_email_result is None:
                        values["message_type"] = "failed_tenant_mail"

                # send by email and sms
                if values["message_type"] == "tenant_mail_and_sms":
                    send_email_result = self._send_email(
                        the_record.tenant_id.email_address,
                        subject,
                        body,
                        team_name,
                        contact_code,
                        triggered_by_user,
                    )
                    send_sms_result = self._send_sms(
                        the_record.tenant_id.phone_number,
                        body,
                        team_name,
                        contact_code,
                        triggered_by_user,
                    )

                    if send_email_result is None and send_sms_result is not None:
                        values["message_type"] = "tenant_mail_failed_and_sms_ok"
                    if send_sms_result is None and send_email_result is not None:
                        values["message_type"] = "tenant_mail_ok_and_sms_failed"
                    if send_email_result is None and send_sms_result is None:
                        values["message_type"] = "failed_tenant_mail_and_sms"

        messages = super(OneCoreMailMessage, self).create(values_list)

        return messages

    # ========================================================================
    # HÄNDELSELOGG CATEGORY (MIM-1956)
    # ========================================================================

    onecore_log_category = fields.Selection(
        [
            (LOG_CATEGORY_EVENT, "Händelse"),
            (LOG_CATEGORY_INTERNAL_NOTE, "Intern notering"),
            (LOG_CATEGORY_COMMUNICATION, "Kommunikation"),
        ],
        string="Loggkategori",
        compute="_compute_onecore_log_category",
        store=False,
    )

    @api.model
    def _onecore_log_category_for(self, message_type, subtype_internal):
        """The single rule table behind the händelselogg filter.

        First match wins. Both consumers — the computed field and
        _onecore_log_category_domain — read these rules, so the server filter
        and the value the OWL store sees cannot drift apart.

        NOTE: Kommunikation is the catch-all. Any NEW message_type that is
        neither "comment" nor "notification" therefore lands in the filter
        handläggare read as the tenant conversation. tests/test_log_category.py
        fails the build until such a type is classified deliberately.
        """
        if message_type == "notification":
            return LOG_CATEGORY_EVENT
        if message_type == "comment" and subtype_internal:
            return LOG_CATEGORY_INTERNAL_NOTE
        return LOG_CATEGORY_COMMUNICATION

    @api.depends("message_type", "subtype_id.internal")
    def _compute_onecore_log_category(self):
        for message in self:
            message.onecore_log_category = self._onecore_log_category_for(
                message.message_type, message.subtype_id.internal
            )

    @api.model
    def _onecore_log_category_domain(self, category):
        """The search-domain twin of _onecore_log_category_for."""
        event = Domain("message_type", "=", "notification")
        internal_note = Domain("message_type", "=", "comment") & Domain(
            "subtype_id.internal", "=", True
        )
        if category == LOG_CATEGORY_EVENT:
            return event
        if category == LOG_CATEGORY_INTERNAL_NOTE:
            return internal_note
        if category == LOG_CATEGORY_COMMUNICATION:
            # Complement of the other two, so the three categories partition
            # the log exactly. DomainNot renders "(...) IS NOT TRUE", which
            # keeps messages with no subtype at all in this bucket — pinned by
            # test_message_without_subtype_is_communication.
            return ~event & ~internal_note
        raise ValueError(f"Okänd loggkategori: {category}")

    @api.model
    def _message_fetch(self, domain, *, onecore_log_category=None, **kwargs):
        """Adds the händelselogg category filter to the chatter fetch.

        Applied as a plain search domain with no sudo(), so mail.message ACLs
        and record rules still decide what an external contractor sees.
        """
        if onecore_log_category:
            domain = Domain(
                True if domain is None else domain
            ) & self._onecore_log_category_domain(onecore_log_category)
        return super()._message_fetch(domain, **kwargs)
