from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # MIM-2011: the user's department (Entra ID ``officeLocation``), written at
    # every SSO login by onecore_auth from the Keycloak userinfo claim, and by
    # the one-off seed import for the password users who never log in via
    # SSO. Stored as AD has it (stripped); AD is kept to one spelling per unit,
    # so there is no normalisation or mapping on top. Copied onto every request
    # the user orders as "Beställande avdelning" (OrderingDepartmentService).
    # Deliberately not readonly — the import wizard hides readonly fields, and
    # the seed import is the only way the ~260 password users ever get a value.
    ad_office_location = fields.Char(
        string="Avdelning",
        copy=False,
        help=(
            "Avdelningen enligt AD (officeLocation). Skrivs automatiskt vid "
            "inloggning via Keycloak, eller via import. Blir Beställande "
            "avdelning på ärenden som användaren skapar."
        ),
    )

    # ------------------------------------------------------------------
    # MIM-2010: what this module adds to a user onecore_auth creates at their
    # first Keycloak login. The policy lives here, not in onecore_auth: that
    # module knows about logins, this one knows what it takes to work with
    # requests.
    #
    # getattr(super()) instead of a plain super() call, on purpose. This
    # module and onecore_auth do not depend on each other, so their load
    # order — and with it the MRO — is undefined. A plain override would be
    # silently skipped whenever this class happens to load first, and a plain
    # super() call would raise when onecore_auth is not installed at all.
    # Written this way both definitions run, in either order, and this one
    # is inert on its own.
    # ------------------------------------------------------------------
    @api.model
    def _auto_create_group_ids(self):
        """Admin Ärendehantering. Without it an internal user sees no
        requests at all (tests/security/test_basic_user.py)."""
        parent = getattr(super(), "_auto_create_group_ids", None)
        group_ids = set(parent() if parent else [])
        group_ids.add(self.env.ref("maintenance.group_equipment_manager").id)
        return list(group_ids)

    @api.model
    def _auto_relink_group_ids(self, user):
        """Admin Ärendehantering for a re-linked employee who lacks it.

        Sebastian, 2026-09-21: every mimer.nu account needs it — there is no
        other way to work in Odoo the way Mimer does — so a password account
        that logs in via Keycloak for the first time gets it too, not only a
        brand-new user. The only people who work without it are the external
        contractors. They are outside the e-mail domain gate and normally
        never get here, but one with a mimer.nu address must not be promoted,
        and neither must a portal user (mixing user types is an error that
        would deny the login).
        """
        parent = getattr(super(), "_auto_relink_group_ids", None)
        group_ids = set(parent(user) if parent else [])
        contractor = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor",
            raise_if_not_found=False,
        )
        is_contractor = bool(contractor) and contractor in user.all_group_ids
        if user._is_internal() and not is_contractor:
            group_ids.add(self.env.ref("maintenance.group_equipment_manager").id)
        return list(group_ids)

    @api.model
    def _auto_create_user_values(self, validation):
        """Notifications "In Odoo" instead of Odoo's default "By e-mail".

        The "Olästa meddelanden" filter is restricted to
        mail.group_mail_notification_type_inbox, and the unread indicators
        only read inbox notifications — a user left on the default would see
        neither, unlike the users an admin sets up by hand.
        """
        parent = getattr(super(), "_auto_create_user_values", None)
        values = dict(parent(validation) if parent else {})
        values["notification_type"] = "inbox"
        return values
