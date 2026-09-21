from odoo import fields, models


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
