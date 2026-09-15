"""Keycloak login hooks (MIM-2011).

Lives here and not in onecore_base_extension because only a module that
depends on ``auth_oauth`` is guaranteed to load after it — and stock
``_auth_oauth_signin`` does not call super(), so an override that loads
first is silently dead. MIM-2010 (auto-create users at first login) builds on
this same method; keep this layer minimal.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# ir.config_parameter key naming the userinfo claim that carries the AD unit.
# Ops create the Keycloak protocol mapper by hand (the realm is not in git);
# if they pick another claim name it must not take a release to follow.
OFFICE_LOCATION_CLAIM_PARAM = "onecore_auth.office_location_claim"
OFFICE_LOCATION_CLAIM_DEFAULT = "office_location"


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        login = super()._auth_oauth_signin(provider, validation, params)
        if login:
            self._sync_ad_office_location(login, validation)
        return login

    @api.model
    def _sync_ad_office_location(self, login, validation):
        """Copy the AD unit claim onto the user, when there is one.

        Stored raw: normalisation is the reader's job
        (onecore_maintenance_extension.maintenance_ad_unit.normalize_ad_unit),
        so the SSO path and the seed import yield identical data.

        Never raises. The OAuth controller turns any exception here into a
        failed login (oauth_error=2), and a malformed claim must not lock
        anyone out.

        The savepoint is what makes that true for *database* errors, not just
        Python ones: a serialization failure, a deadlock or a
        constraint from another res.users override aborts the whole Postgres
        transaction, and swallowing the exception would then only move the
        failure to the controller's next query as InFailedSqlTransaction —
        locking the user out anyway, from somewhere that points nowhere near
        here. Same pattern as direct_lookup_service._safe_update_form_options.
        """
        # Soft dependency: the field belongs to onecore_maintenance_extension.
        # This module must stay installable without it.
        if "ad_office_location" not in self._fields:
            return
        try:
            claim = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(OFFICE_LOCATION_CLAIM_PARAM, OFFICE_LOCATION_CLAIM_DEFAULT)
            )
            if claim not in validation:
                return
            value = validation[claim]
            if value is None:
                return
            if not isinstance(value, str):
                # A multivalued protocol mapper delivers a list, and str()
                # would happily store "['Kundcenterenheten']" — no exception,
                # so the except below never fires, and normalize_ad_unit then
                # silently matches no maintenance.ad.unit row with nothing in
                # the log to explain why. The mapper is created by hand in
                # Keycloak and the spec says multivalued OFF, so this is a
                # configuration mistake worth shouting about.
                _logger.warning(
                    "MIM-2011: Keycloak claim %r for %s is %s, expected a "
                    "string. Check that the protocol mapper has multivalued "
                    "OFF. The AD unit was not written.",
                    claim,
                    login,
                    type(value).__name__,
                )
                return
            value = value.strip()
            if not value:
                return
            # savepoint: a database-level failure here (serialization,
            # deadlock, a constraint from another res.users override) aborts
            # the whole transaction. Swallowing it below without rolling back
            # would just move the failure to the controller's next query.
            with self.env.cr.savepoint():
                user = self.sudo().search([("login", "=", login)], limit=1)
                if user and user.ad_office_location != value:
                    user.write({"ad_office_location": value})
        except Exception:
            _logger.exception(
                "MIM-2011: could not sync AD unit from Keycloak for %s", login
            )
