import logging

from markupsafe import Markup, escape

from odoo import models, fields, api, exceptions, _

from .services.direct_lookup_service import (
    DirectLookupService,
    LookupFailed,
    route_for_lease_option,
    route_for_object_option,
    all_routes,
)
from .services.record_management_service import RecordManagementService
from .utils.helpers import select_active_lease
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)

# Dialog title per entry point (used both when opening and when re-rendering).
_TITLES = {
    "rental_object": "Lägg till / ändra hyresobjekt",
    "tenant": "Lägg till / ändra hyresgäst",
}


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
    object_option_ref = fields.Reference(
        selection=[
            ("maintenance.rental.property.option", "Lägenhet"),
            ("maintenance.parking.space.option", "Bilplats"),
            ("maintenance.facility.option", "Lokal"),
        ],
        string="Hyresobjekt (tomställt)",
        readonly=True,
    )
    # True when the search resolved an object with no contract → attached as vacant.
    is_vacant = fields.Boolean(readonly=True)
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
        try:
            if self.lookup_kind == "tenant":
                result = service.load_contact_contracts(
                    self.maintenance_request_id, value
                )
            else:
                result = service.load_object_contracts(
                    self.maintenance_request_id, value
                )
        except LookupFailed as err:
            # A failed call is not a wrong number — say so rather than blaming the
            # value the user pasted.
            _logger.warning("Backfill lookup failed for %s: %s", value, err)
            raise exceptions.UserError(
                _(
                    "Uppslagningen mot OneCore misslyckades. Försök igen om en "
                    "stund, eller kontakta support om felet kvarstår."
                )
            ) from err
        if not result:
            raise exceptions.UserError(self._not_found_message(value))

        vals = {
            "state": "preview",
            "lease_option_id": False,
            "object_option_ref": False,
            "is_vacant": False,
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
            vals["object_option_ref"] = f"{obj._name},{obj.id}"
            vals["is_vacant"] = True
            vals.update(self._preview_vals(obj, None))
        self.write(vals)
        return self.action_window()

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
        elif self.object_option_ref:
            object_option = self.object_option_ref
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
        object left over from a previous attach).

        Every write runs with change tracking suppressed and one summary note is
        posted at the end: the attach touches half a dozen fields, and a
        ``message_post`` per write made confirming both slow and noisy in the log.
        """
        record_service = RecordManagementService(self.env)
        old_objects = {
            r["record_field"]: request[r["record_field"]] for r in all_routes()
        }
        old_lease = request.lease_id
        old_tenant = request.tenant_id
        before = self._attached_labels(request)

        # Everything that is a plain field write goes in one write: the space type,
        # the object fields of other types, and (vacant case) the cleared contract.
        vals = {}
        if request.space_caption != route["space"]:
            vals["space_caption"] = route["space"]
        for r in all_routes():
            field = r["record_field"]
            if field != route["record_field"] and request[field]:
                vals[field] = False
        if lease_option:
            if request.manually_vacated:
                vals["manually_vacated"] = False
        else:
            # Vacant object: leave it genuinely vacant — drop the old contract and
            # tenant, and flag it so the empty-tenant compute won't silently refetch.
            vals.update(
                {"lease_id": False, "tenant_id": False, "manually_vacated": True}
            )

        untracked = request.with_context(skip_change_tracking=True)
        if vals:
            untracked.write(vals)

        if object_option:
            getattr(record_service, route["save_method"])(
                untracked, {route["option_field"]: object_option.id}
            )

        if lease_option:
            record_service._save_lease(untracked, {"lease_option_id": lease_option.id})
            tenant_option = self._tenant_of(lease_option)
            if tenant_option:
                record_service._save_tenant(
                    untracked, {"tenant_option_id": tenant_option.id}
                )
            elif request.tenant_id:
                # Contract with no tenant → don't keep the previously attached one.
                untracked.write({"tenant_id": False})

        # Delete every replaced record. Always reconcile lease/tenant too: covers
        # replace, vacant clear, and empty-tenant contract (no-op when the record
        # is unchanged or was never set).
        for r in all_routes():
            field = r["record_field"]
            self._unlink_replaced(old_objects[field], request[field])
        self._unlink_replaced(old_lease, request.lease_id)
        self._unlink_replaced(old_tenant, request.tenant_id)

        self._post_attach_note(request, before)

    def _attached_labels(self, request):
        """Display names of the three things this wizard attaches."""
        objects = [request[r["record_field"]] for r in all_routes()]
        current = next((o for o in objects if o), None)
        return {
            "Hyresobjekt": current.display_name if current else None,
            "Kontrakt": request.lease_id.display_name if request.lease_id else None,
            "Hyresgäst": request.tenant_id.display_name if request.tenant_id else None,
        }

    def _post_attach_note(self, request, before):
        """One chatter note describing the whole attach."""
        after = self._attached_labels(request)
        lines = [
            Markup("%s: %s → %s")
            % (label, escape(before[label] or "–"), escape(after[label] or "–"))
            for label in before
            if before[label] != after[label]
        ]
        if not lines:
            return
        request.message_post(
            body=Markup("<div>") + Markup("<br/>").join(lines) + Markup("</div>"),
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )

    def _unlink_replaced(self, old_record, new_record):
        """Delete a permanent record that was just replaced by ``new_record``.

        Best-effort: if the delete is blocked (e.g. a reference elsewhere), log and
        leave the old record unreferenced rather than failing the confirm.

        A blocked delete is a foreign-key violation, which aborts the transaction,
        so the savepoint is what keeps "best-effort" honest: without it the caught
        exception would still take down the remaining unlinks and the chatter note,
        rolling back the attach the user just confirmed.
        """
        if not old_record or old_record == new_record or not old_record.exists():
            return
        try:
            with self.env.cr.savepoint():
                old_record.unlink()
        except Exception as err:
            _logger.warning(
                "Could not delete replaced %s record %s: %s",
                old_record._name,
                old_record.id,
                err,
            )

    def action_window(self):
        """The act_window that renders this wizard dialog — used both to open it
        and to re-render it (to show the preview state)."""
        self.ensure_one()
        return {
            "name": _TITLES[self.lookup_kind],
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": dict(self.env.context, dialog_size="medium"),
        }

    # ----------------------------------------------------------------- preview
    def _object_option_of(self, lease_option):
        return (
            lease_option.rental_property_option_id
            or lease_option.parking_space_option_id
            or lease_option.facility_option_id
        )

    def _tenant_of(self, lease_option):
        """The tenant to attach for a contract.

        On the kundnummer path a co-signed lease has several tenants; return the one
        whose contact_code matches the searched number (a bare ``limit=1`` would pick
        the primary tenant regardless of who was searched). Falls back to the first.
        """
        Tenant = self.env["maintenance.tenant.option"]
        domain = [
            ("lease_option_id", "=", lease_option.id),
            ("user_id", "=", self.env.uid),
        ]
        if self.lookup_kind == "tenant" and self.lookup_value:
            match = Tenant.search(
                domain + [("contact_code", "=", self.lookup_value.strip())], limit=1
            )
            if match:
                return match
        return Tenant.search(domain, limit=1)

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
