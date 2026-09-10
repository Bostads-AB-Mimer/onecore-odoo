"""Tests for MIM-2011 — the AD unit (officeLocation) claim at Keycloak login.

_auth_oauth_signin is called directly, the way auth_oauth's controller does
after it has validated the token: ``validation`` is the merged
tokeninfo + userinfo dict with the subject already renamed to ``user_id``.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.res_users import OFFICE_LOCATION_CLAIM_PARAM

# The field is defined by onecore_maintenance_extension. post_install: the
# whole registry is loaded, so the test does not depend on the module load
# order (a graph-depth accident today, not a declared dependency).
@tagged("onecore", "post_install", "-at_install")
class TestAdOfficeLocationSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["auth.oauth.provider"].create(
            {
                "name": "Test Keycloak",
                "auth_endpoint": "https://auth.example/auth",
                "validation_endpoint": "https://auth.example/token",
                "data_endpoint": "https://auth.example/userinfo",
                "body": "Test login",
                "enabled": True,
            }
        )
        cls.user = cls.env["res.users"].create(
            {
                "name": "AD Testperson",
                "login": "ad.test@example.com",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
                "oauth_provider_id": cls.provider.id,
                "oauth_uid": "sub-ad-test",
            }
        )

    def setUp(self):
        super().setUp()
        self.assertIn("ad_office_location", self.env["res.users"]._fields)

    def _signin(self, claims, users=None, subject="sub-ad-test"):
        # `users if users is not None`, not `users or ...`: an empty recordset
        # is falsy, and `or` would silently drop a with_context() env.
        users = self.env["res.users"] if users is None else users
        validation = {"user_id": subject, "email": "ad.test@example.com"}
        validation.update(claims)
        return users._auth_oauth_signin(
            self.provider.id, validation, {"access_token": "tok", "state": "{}"}
        )

    def test_claim_is_written_raw_at_login(self):
        login = self._signin({"office_location": "Kundcenterenheten"})

        self.assertEqual(login, "ad.test@example.com")
        # Raw, not normalised: the reader normalises, so import and SSO agree
        self.assertEqual(self.user.ad_office_location, "Kundcenterenheten")

    def test_claim_replaces_a_stale_value(self):
        """AD is the truth, Keycloak a mirror (syncMode FORCE): a department
        change shows up at the next login."""
        self.user.write({"ad_office_location": "Distrikt Öst"})

        self._signin({"office_location": "Fastighetsserviceenheten"})

        self.assertEqual(self.user.ad_office_location, "Fastighetsserviceenheten")

    def test_claim_value_is_stripped(self):
        self._signin({"office_location": "  IT-enheten  "})

        self.assertEqual(self.user.ad_office_location, "IT-enheten")

    def test_missing_claim_leaves_the_value_alone(self):
        """No mapper in Keycloak yet, or a user without officeLocation
        (service accounts, consultants): whatever the import put there stays."""
        self.user.write({"ad_office_location": "Distrikt Öst"})

        login = self._signin({})

        self.assertEqual(login, "ad.test@example.com")
        self.assertEqual(self.user.ad_office_location, "Distrikt Öst")

    def test_empty_claim_leaves_the_value_alone(self):
        self.user.write({"ad_office_location": "Distrikt Öst"})

        self._signin({"office_location": ""})
        self._signin({"office_location": None})

        self.assertEqual(self.user.ad_office_location, "Distrikt Öst")

    def test_unchanged_claim_does_not_write(self):
        self.user.write({"ad_office_location": "Kundcenter"})
        Users = self.env.registry["res.users"]
        original_write = Users.write

        with patch.object(Users, "write", autospec=True, side_effect=original_write) as write:
            self._signin({"office_location": "Kundcenter"})

        written = [call.args[1] for call in write.call_args_list]
        self.assertFalse(any("ad_office_location" in vals for vals in written))

    def test_claim_name_is_a_system_parameter(self):
        """Ops create the protocol mapper by hand; another claim name must not
        need a release."""
        self.env["ir.config_parameter"].sudo().set_param(
            OFFICE_LOCATION_CLAIM_PARAM, "ad_unit"
        )

        self._signin({"office_location": "Fel claim", "ad_unit": "Rätt claim"})

        self.assertEqual(self.user.ad_office_location, "Rätt claim")

    def test_multivalued_claim_is_refused_and_logged(self):
        """PR #286 review. "Multivalued" is a checkbox on the hand-made
        Keycloak mapper; with it on, the claim arrives as a list. str() would
        store the literal "['Kundcenterenheten']" — no exception, so the
        except branch never fires, and normalize_ad_unit would then match no
        mapping row with nothing in the log to explain why."""
        self.user.write({"ad_office_location": "Kundcenter"})

        with self.assertLogs(
            "odoo.addons.onecore_auth.models.res_users", "WARNING"
        ) as logs:
            login = self._signin({"office_location": ["Kundcenterenheten"]})

        self.assertEqual(login, "ad.test@example.com")
        # The good value from the import is left alone, not overwritten
        self.assertEqual(self.user.ad_office_location, "Kundcenter")
        self.assertIn("multivalued", logs.output[0])

    def test_unknown_subject_writes_nothing(self):
        """Stock denies the login; the sync must not run for a user that was
        never resolved."""
        login = self._signin(
            {"office_location": "Kundcenter"},
            users=self.env["res.users"].with_context(no_user_creation=True),
            subject="sub-nobody",
        )

        self.assertIsNone(login)
        self.assertFalse(self.user.ad_office_location)

    def test_missing_field_is_tolerated(self):
        """onecore_auth must stay installable without
        onecore_maintenance_extension: no field, no write, no error."""
        Users = self.env.registry["res.users"]
        model = self.env["res.users"]
        # _fields is a mappingproxy — replace it wholesale rather than
        # mutating it.
        without_field = {
            name: field
            for name, field in Users._fields.items()
            if name != "ad_office_location"
        }
        with patch.object(Users, "_fields", without_field):
            model._sync_ad_office_location(
                "ad.test@example.com", {"office_location": "Kundcenter"}
            )

        self.assertFalse(self.user.ad_office_location)

    def test_write_failure_never_blocks_the_login(self):
        """auth_oauth's controller turns any exception here into
        oauth_error=2. A bad claim must be logged, not lock anyone out."""
        Users = self.env.registry["res.users"]
        original_write = Users.write

        def failing_write(records, vals):
            if "ad_office_location" in vals:
                raise ValueError("boom")
            return original_write(records, vals)

        with patch.object(Users, "write", autospec=True, side_effect=failing_write), \
                self.assertLogs("odoo.addons.onecore_auth.models.res_users", "ERROR") as logs:
            login = self._signin({"office_location": "Kundcenter"})

        self.assertEqual(login, "ad.test@example.com")
        self.assertFalse(self.user.ad_office_location)
        self.assertIn("could not sync AD unit", logs.output[0])
