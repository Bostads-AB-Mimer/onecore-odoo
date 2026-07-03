import logging

from odoo import models, fields, api, exceptions, _

from .services.direct_lookup_service import (
    DirectLookupService,
    route_for_lease_option,
    route_for_object_option,
    all_routes,
)
from .services.record_management_service import RecordManagementService
from .utils.helpers import select_active_lease
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)


class MaintenanceBackfillWizard(models.TransientModel):
    _name = "maintenance.backfill.wizard"
    _description = "Lägg till/ändra hyresobjekt och hyresgäst"

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Ärende", required=True, readonly=True
    )
    # Which id the user pastes (drives the OneCore lookup); both entry points end
    # up attaching object + contract + tenant together.
    lookup_kind = fields.Selection(
        [("rental_object", "Hyresobjekt"), ("tenant", "Hyresgäst")],
        string="Typ",
        required=True,
    )
    lookup_value = fields.Char(string="Nummer")
    state = fields.Selection(
        [("input", "input"), ("preview", "preview")], default="input"
    )
    # The contracts found by Sök; the chosen one drives what gets attached.
    lease_option_id = fields.Many2one("maintenance.lease.option", string="Kontrakt")
    # Vacant-object case (object found but no contract): the object option to attach.
    object_model = fields.Char(readonly=True)
    object_res_id = fields.Integer(readonly=True)
    # Read-only preview of what will be attached (kept in sync with the contract).
    prev_object_id = fields.Char(string="Hyresobjekt", readonly=True)
    prev_object_address = fields.Char(string="Adress", readonly=True)
    prev_object_property = fields.Char(string="Fastighet", readonly=True)
    prev_tenant_name = fields.Char(string="Hyresgäst", readonly=True)
    prev_tenant_contact = fields.Char(string="Kundnummer", readonly=True)

    def _get_core_api(self):
        return core_api.CoreApi(self.env)

    @property
    def _value_label(self):
        return "objektnummer" if self.lookup_kind == "rental_object" else "kundnummer"

    # ------------------------------------------------------------------ search
    def action_search(self):
        self.ensure_one()
        value = (self.lookup_value or "").strip()
        if not value:
            raise exceptions.UserError(_("Ange ett %s.") % self._value_label)

        service = DirectLookupService(self.env, self._get_core_api())
        if self.lookup_kind == "tenant":
            result = service.load_contact_contracts(self.maintenance_request_id, value)
        else:
            result = service.load_object_contracts(self.maintenance_request_id, value)
        if not result:
            raise exceptions.UserError(self._not_found_message(value))

        vals = {
            "state": "preview",
            "lease_option_id": False,
            "object_model": False,
            "object_res_id": False,
        }
        lease_options = result.get("lease_options")
        if lease_options:
            active = select_active_lease(lease_options)
            vals["lease_option_id"] = active.id
            vals.update(
                self._preview_vals(self._object_option_of(active), self._tenant_of(active))
            )
        else:
            # Vacant object (objektnummer with no contract): just attach the object.
            obj = result["object_option"]
            vals["object_model"] = obj._name
            vals["object_res_id"] = obj.id
            vals.update(self._preview_vals(obj, None))
        self.write(vals)
        return self._reopen()

    def _not_found_message(self, value):
        if self.lookup_kind == "rental_object":
            return _(
                "Inget hyresobjekt hittades för objektnummer %s. "
                "Kontrollera att numret är korrekt."
            ) % value
        return _(
            "Ingen hyresgäst hittades för kundnummer %s. "
            "Kontrollera numret eller att kunden har ett avtal."
        ) % value

    @api.onchange("lease_option_id")
    def _onchange_lease_option_id(self):
        # Keep the preview in sync with the contract the user picks.
        if self.state == "preview" and self.lease_option_id:
            for field, val in self._preview_vals(
                self._object_option_of(self.lease_option_id),
                self._tenant_of(self.lease_option_id),
            ).items():
                self[field] = val

    # ----------------------------------------------------------------- confirm
    def action_confirm(self):
        self.ensure_one()
        request = self.maintenance_request_id

        if self.lease_option_id and self.lease_option_id.exists():
            lease_option = self.lease_option_id
            route = route_for_lease_option(lease_option)
            if not route:
                raise exceptions.UserError(
                    _("Kunde inte avgöra hyresobjektets typ för det valda kontraktet.")
                )
            self._attach(request, route, lease_option[route["option_field"]], lease_option)
        elif self.object_res_id and self.object_model:
            object_option = self.env[self.object_model].browse(self.object_res_id)
            if not object_option.exists():
                raise exceptions.UserError(
                    _("Resultatet är inte längre giltigt. Sök igen.")
                )
            route = route_for_object_option(object_option)
            if not route:
                raise exceptions.UserError(
                    _("Kunde inte avgöra hyresobjektets typ.")
                )
            self._attach(request, route, object_option, None)
        else:
            raise exceptions.UserError(_("Sök fram ett resultat först."))

        # Close the dialog AND reload the underlying form so the newly attached
        # data shows immediately (act_window_close alone leaves the stale form).
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _attach(self, request, route, object_option, lease_option):
        """Materialize object (+ contract + tenant), align the space type to the
        object's kind, and delete whatever we replaced (including a different-typed
        object left over from a previous attach)."""
        record_service = RecordManagementService(self.env)
        old_objects = {
            r["record_field"]: request[r["record_field"]] for r in all_routes()
        }
        old_lease = request.lease_id
        old_tenant = request.tenant_id

        if request.space_caption != route["space"]:
            request.space_caption = route["space"]

        if object_option:
            getattr(record_service, route["save_method"])(
                request, {route["option_field"]: object_option.id}
            )
        if lease_option:
            record_service._save_lease(request, {"lease_option_id": lease_option.id})
            tenant_option = self.env["maintenance.tenant.option"].search(
                [
                    ("lease_option_id", "=", lease_option.id),
                    ("user_id", "=", self.env.uid),
                ],
                limit=1,
            )
            if tenant_option:
                record_service._save_tenant(
                    request, {"tenant_option_id": tenant_option.id}
                )

        # Clear stale object fields of other types, then delete every replaced record.
        for r in all_routes():
            field = r["record_field"]
            if field != route["record_field"] and request[field]:
                request[field] = False
            self._unlink_replaced(old_objects[field], request[field])
        if lease_option:
            self._unlink_replaced(old_lease, request.lease_id)
            self._unlink_replaced(old_tenant, request.tenant_id)

    def _unlink_replaced(self, old_record, new_record):
        """Delete a permanent record that was just replaced by ``new_record``.

        Best-effort: if the delete is blocked (e.g. a reference elsewhere), log and
        leave the old record unreferenced rather than failing the confirm.
        """
        if not old_record or old_record == new_record or not old_record.exists():
            return
        try:
            old_record.unlink()
        except Exception as err:
            _logger.warning(
                "Could not delete replaced %s record %s: %s",
                old_record._name,
                old_record.id,
                err,
            )

    def _reopen(self):
        """Re-render the same wizard dialog (to show the preview state)."""
        title = (
            "Lägg till / ändra hyresobjekt"
            if self.lookup_kind == "rental_object"
            else "Lägg till / ändra hyresgäst"
        )
        return {
            "name": title,
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": dict(self.env.context),
        }

    # ----------------------------------------------------------------- preview
    def _object_option_of(self, lease_option):
        return (
            lease_option.rental_property_option_id
            or lease_option.parking_space_option_id
            or lease_option.facility_option_id
        )

    def _tenant_of(self, lease_option):
        return self.env["maintenance.tenant.option"].search(
            [
                ("lease_option_id", "=", lease_option.id),
                ("user_id", "=", self.env.uid),
            ],
            limit=1,
        )

    def _preview_vals(self, object_option, tenant_option):
        """Values for the read-only preview fields (object identity + tenant)."""
        vals = {
            "prev_object_id": False,
            "prev_object_address": False,
            "prev_object_property": False,
            "prev_tenant_name": False,
            "prev_tenant_contact": False,
        }
        if object_option:
            vals["prev_object_id"] = object_option.name
            if object_option._name == "maintenance.rental.property.option":
                vals["prev_object_address"] = object_option.address
                vals["prev_object_property"] = object_option.estate
            elif object_option._name == "maintenance.parking.space.option":
                vals["prev_object_address"] = object_option.address
                vals["prev_object_property"] = object_option.property_name
            else:  # facility
                vals["prev_object_address"] = object_option.building_name
                vals["prev_object_property"] = object_option.property_name
        if tenant_option:
            vals["prev_tenant_name"] = tenant_option.name
            vals["prev_tenant_contact"] = tenant_option.contact_code
        return vals
