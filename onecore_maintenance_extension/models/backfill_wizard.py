import logging

from odoo import models, fields, exceptions, _

from .services.direct_lookup_service import DirectLookupService
from .services.record_management_service import RecordManagementService
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)


class MaintenanceBackfillWizard(models.TransientModel):
    _name = "maintenance.backfill.wizard"
    _description = "Lägg till hyresobjekt/hyresgäst"

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Ärende", required=True, readonly=True
    )
    lookup_kind = fields.Selection(
        [("rental_object", "Hyresobjekt"), ("tenant", "Hyresgäst")],
        string="Typ",
        required=True,
    )
    lookup_value = fields.Char(string="Nummer")
    state = fields.Selection(
        [("input", "input"), ("preview", "preview")], default="input"
    )
    preview_text = fields.Text(string="Resultat", readonly=True)
    # Reference to the fetched transient option, materialized on confirm.
    option_model = fields.Char(readonly=True)
    option_res_id = fields.Integer(readonly=True)

    def _get_core_api(self):
        return core_api.CoreApi(self.env)

    @property
    def _value_label(self):
        return "objektnummer" if self.lookup_kind == "rental_object" else "kundnummer"

    def action_search(self):
        self.ensure_one()
        value = (self.lookup_value or "").strip()
        if not value:
            raise exceptions.UserError(_("Ange ett %s.") % self._value_label)

        service = DirectLookupService(self.env, self._get_core_api())
        if self.lookup_kind == "rental_object":
            option = service.create_rental_object_option(
                self.maintenance_request_id, value
            )
            if not option:
                raise exceptions.UserError(
                    _(
                        "Inget hyresobjekt hittades för objektnummer %s. "
                        "Kontrollera att numret är korrekt."
                    )
                    % value
                )
            preview = self._rental_object_preview(option)
        else:
            option = service.create_tenant_option(self.maintenance_request_id, value)
            if not option:
                raise exceptions.UserError(
                    _(
                        "Ingen hyresgäst hittades för kundnummer %s. "
                        "Kontrollera numret eller att kunden har ett avtal."
                    )
                    % value
                )
            preview = self._tenant_preview(option)

        self.write(
            {
                "option_model": option._name,
                "option_res_id": option.id,
                "preview_text": preview,
                "state": "preview",
            }
        )
        return self._reopen()

    def action_confirm(self):
        self.ensure_one()
        if not self.option_res_id or not self.option_model:
            raise exceptions.UserError(_("Sök fram ett resultat först."))
        option = self.env[self.option_model].browse(self.option_res_id)
        if not option.exists():
            raise exceptions.UserError(_("Resultatet är inte längre giltigt. Sök igen."))

        record_service = RecordManagementService(self.env)
        request = self.maintenance_request_id
        if self.lookup_kind == "tenant":
            # Attach the contact's active contract first (if any) so the tenant's
            # contract/phone/email block is unlocked, then the tenant itself.
            if option.lease_option_id:
                record_service._save_lease(
                    request, {"lease_option_id": option.lease_option_id.id}
                )
            record_service._save_tenant(request, {"tenant_option_id": option.id})
        else:
            route = DirectLookupService(
                self.env, self._get_core_api()
            ).route_for(request.space_caption)
            if not route:
                raise exceptions.UserError(
                    _("Det går inte att lägga till ett hyresobjekt för utrymmet \"%s\".")
                    % request.space_caption
                )
            getattr(record_service, route["save_method"])(
                request, {route["option_field"]: option.id}
            )
        # Close the dialog AND reload the underlying request form so the newly
        # materialized tenant/object is shown immediately (act_window_close alone
        # leaves the stale form on screen until a manual refresh).
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _reopen(self):
        """Re-render the same wizard dialog (to show the preview state)."""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": dict(self.env.context),
        }

    def _rental_object_preview(self, option):
        space = self.maintenance_request_id.space_caption
        if space == "Bilplats":
            lines = [
                f"Bilplats: {option.name or ''}",
                f"Kod: {option.code or ''}",
                f"Typ: {option.type_name or ''}",
                f"Fastighet: {option.property_name or ''}",
                f"Adress: {option.address or ''}",
            ]
        elif space == "Lokal":
            lines = [
                f"Lokal: {option.name or ''}",
                f"Kod: {option.code or ''}",
                f"Typ: {option.type_name or ''}",
                f"Byggnad: {option.building_name or ''}",
                f"Fastighet: {option.property_name or ''}",
            ]
        else:
            lines = [
                f"Hyresobjekt: {option.name or ''}",
                f"Adress: {option.address or ''}",
                f"Kod: {option.code or ''}",
                f"Fastighet: {option.estate or ''}",
                f"Byggnad: {option.building or ''}",
            ]
        return "\n".join(line for line in lines if line.split(": ", 1)[1])

    def _tenant_preview(self, option):
        lines = [
            f"Namn: {option.name or ''}",
            f"Kundnummer: {option.contact_code or ''}",
            f"Personnummer: {option.national_registration_number or ''}",
            f"Telefon: {option.phone_number or ''}",
            f"E-post: {option.email_address or ''}",
        ]
        if option.lease_option_id:
            lines.append(f"Kontrakt: {option.lease_option_id.name or ''}")
            lines.append(f"Kontraktstyp: {option.lease_option_id.lease_type or ''}")
        return "\n".join(line for line in lines if line.split(": ", 1)[1])
