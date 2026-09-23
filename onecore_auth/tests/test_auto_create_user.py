"""Tests for MIM-2010 — a Keycloak login no Odoo user carries the subject of.

_auth_oauth_signin is called directly, the way auth_oauth's controller does
after it has validated the token: ``validation`` is the merged
tokeninfo + userinfo dict with the subject already renamed to ``user_id``.
"""
import logging
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from ..models.res_users import AUTO_CREATE_DOMAINS_PARAM

LOGGER = "odoo.addons.onecore_auth.models.res_users"
# The int, not the name: Odoo registers a custom level 25 under the name
# "INFO", so assertLogs(..., "INFO") silently filters out every real
# logging.INFO (20) record.
INFO = logging.INFO


# post_install: the maintenance group and the ad_office_location field belong
# to other modules; with the whole registry loaded the tests do not depend on
# the module load order.
@tagged("onecore", "post_install", "-at_install")
class TestAutoCreateUser(TransactionCase):
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
        cls.Users = cls.env["res.users"].with_context(active_test=False)

    def _signin(self, subject, email=None, users=None, **claims):
        users = self.env["res.users"] if users is None else users
        # email_verified defaults to True: that is what Keycloak sends for a
        # brokered user when the identity provider has Trust Email on, and
        # what every create/re-link test assumes. The verification tests
        # override it.
        validation = {"user_id": subject, "email_verified": True}
        if email is not None:
            validation["email"] = email
        validation.update(claims)
        return users._auth_oauth_signin(
            self.provider.id, validation, {"access_token": "tok", "state": "{}"}
        )

    def _password_user(self, login, **vals):
        values = {
            "name": "Befintlig Person",
            "login": login,
            "email": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        }
        values.update(vals)
        return self.env["res.users"].with_context(no_reset_password=True).create(values)

    def _by_login(self, login):
        return self.Users.search([("login", "=", login)])

    # ------------------------------------------------------------------
    # Stock path
    # ------------------------------------------------------------------
    def test_known_subject_takes_the_stock_path(self):
        user = self._password_user(
            "kand@mimer.nu", oauth_provider_id=self.provider.id, oauth_uid="sub-kand"
        )
        count_before = self.Users.search_count([])

        login = self._signin("sub-kand", "kand@mimer.nu")

        self.assertEqual(login, "kand@mimer.nu")
        self.assertEqual(user.oauth_access_token, "tok")
        self.assertEqual(self.Users.search_count([]), count_before)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def test_unknown_subject_with_a_mimer_address_gets_an_internal_user(self):
        mails_before = (
            self.env["mail.mail"].sudo().search_count([]) if "mail.mail" in self.env else 0
        )

        login = self._signin("sub-ny", "  Ny.Person@Mimer.NU ", name="Ny Person")

        self.assertEqual(login, "ny.person@mimer.nu")
        user = self._by_login("ny.person@mimer.nu")
        self.assertEqual(len(user), 1)
        self.assertEqual(user.name, "Ny Person")
        self.assertEqual(user.email, "ny.person@mimer.nu")
        self.assertEqual(user.oauth_uid, "sub-ny")
        self.assertEqual(user.oauth_provider_id, self.provider)
        self.assertEqual(user.oauth_access_token, "tok")
        self.assertTrue(user.active)
        self.assertTrue(user._is_internal())
        self.assertEqual(user.tz, "Europe/Stockholm")
        # Admin Ärendehantering: without it the person sees no requests at all
        self.assertTrue(user.has_group("maintenance.group_equipment_manager"))
        contractor = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor",
            raise_if_not_found=False,
        )
        if contractor:
            self.assertNotIn(contractor, user.group_ids)
        # no_reset_password: no "set your password" invitation
        if "mail.mail" in self.env:
            self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails_before)

    def test_new_user_gets_the_default_access_groups_too(self):
        """Whatever is configured under Inställningar → Användare →
        Standardåtkomst applies, same as for a user created by hand."""
        self._signin("sub-default", "default@mimer.nu")

        user = self._by_login("default@mimer.nu")
        for group in self.env["res.users"]._default_groups():
            self.assertIn(group, user.all_group_ids)

    def test_new_user_gets_their_department_in_the_same_login(self):
        """MIM-2011's sync runs last, after the user exists. Beställande
        avdelning depends on it: a second login must not be needed."""
        self._signin(
            "sub-avd", "avdelning@mimer.nu", office_location="Kundcenter"
        )

        user = self._by_login("avdelning@mimer.nu")
        self.assertEqual(user.ad_office_location, "Kundcenter")

    def test_second_login_takes_the_stock_path(self):
        self._signin("sub-tva", "tva@mimer.nu")
        count_after_first = self.Users.search_count([])

        login = self._signin("sub-tva", "tva@mimer.nu")

        self.assertEqual(login, "tva@mimer.nu")
        self.assertEqual(self.Users.search_count([]), count_after_first)

    def test_hooks_from_both_modules_are_applied(self):
        """What a new user gets is decided by two modules that do not depend
        on each other, so their load order is undefined. Both contributions
        have to arrive whichever class ends up first in the MRO: this module's
        defaults (standard access, tz, lang) *and*
        onecore_maintenance_extension's (Admin Ärendehantering, notifications
        "In Odoo" — the unread filter and indicators only work for those)."""
        self._signin("sub-hooks", "hooks@mimer.nu")

        user = self._by_login("hooks@mimer.nu")
        for group in self.env["res.users"]._default_groups():
            self.assertIn(group, user.all_group_ids)
        self.assertTrue(user.has_group("maintenance.group_equipment_manager"))
        self.assertEqual(user.notification_type, "inbox")
        self.assertEqual(user.tz, "Europe/Stockholm")
        if "sv_SE" in dict(self.env["res.lang"].get_installed()):
            self.assertEqual(user.lang, "sv_SE")

    def test_empty_name_claim_falls_back_to_the_email(self):
        """A present-but-null name claim must not reach create() as None."""
        login = self._signin("sub-namnlos", "namnlos@mimer.nu", name=None)

        self.assertEqual(login, "namnlos@mimer.nu")
        self.assertEqual(self._by_login("namnlos@mimer.nu").name, "namnlos@mimer.nu")

    # ------------------------------------------------------------------
    # Refusals
    # ------------------------------------------------------------------
    def test_address_outside_the_domain_list_is_denied(self):
        """Contractors are still set up by hand."""
        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-extern", "nagon@entreprenor.se")

        self.assertIsNone(login)
        self.assertFalse(self._by_login("nagon@entreprenor.se"))
        self.assertIn("entreprenor.se", logs.output[0])

    def test_lookalike_domain_is_denied(self):
        """The domain is compared whole, not as a suffix."""
        with self.assertLogs(LOGGER, "WARNING"):
            self.assertIsNone(self._signin("sub-fake", "nagon@notmimer.nu"))
            self.assertIsNone(self._signin("sub-fake2", "nagon@mimer.nu.evil.se"))

        self.assertFalse(self._by_login("nagon@notmimer.nu"))
        self.assertFalse(self._by_login("nagon@mimer.nu.evil.se"))

    def test_missing_email_is_denied_with_a_reason(self):
        """The prod provider only asks for scope openid; if the Keycloak
        client lacks the email client scope every new user ends up here. The
        log has to say so — the person only ever sees oauth_error=3."""
        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-utan-mail")

        self.assertIsNone(login)
        self.assertIn("no usable email in Keycloak userinfo", logs.output[0])

    def test_malformed_email_claims_are_denied(self):
        """The claim has to *be* one address. A hand-rolled split read the
        claim "mimer.nu" as its own domain and let it through the allowlist,
        creating an internal user called "mimer.nu"."""
        count_before = self.Users.search_count([])
        claims = (
            "mimer.nu",
            # email_normalize accepts this one: an empty local part
            "@mimer.nu",
            "namn@",
            "a@b@mimer.nu",
            "Namn Namnsson <namn@mimer.nu>",
            "a@mimer.nu, b@mimer.nu",
            "a b@mimer.nu",
        )
        for index, claim in enumerate(claims):
            # A subject of its own per case: a claim that wrongly gets through
            # creates a user, and a shared subject would then make every later
            # case "succeed" through the stock path and hide which one leaked.
            with self.subTest(claim=claim), self.assertLogs(LOGGER, "WARNING"):
                self.assertIsNone(self._signin("sub-trasig-%s" % index, claim))

        self.assertEqual(self.Users.search_count([]), count_before)

    def test_emptied_domain_parameter_switches_the_feature_off(self):
        """Fail closed. get_param(key, default) returns the default for a
        blank value too, so a code-level default of "mimer.nu" would make the
        switch impossible to turn off."""
        existing = self._password_user("finns@mimer.nu")
        for value in ("", "  ,  "):
            self.env["ir.config_parameter"].sudo().set_param(
                AUTO_CREATE_DOMAINS_PARAM, value
            )
            with self.subTest(value=value), self.assertLogs(LOGGER, "WARNING") as logs:
                self.assertIsNone(self._signin("sub-av", "ny.av@mimer.nu"))
                self.assertIsNone(self._signin("sub-av2", "finns@mimer.nu"))
            self.assertIn("switched off", logs.output[0])

        self.assertFalse(self._by_login("ny.av@mimer.nu"))
        self.assertFalse(existing.oauth_uid)

    def test_disabled_provider_is_never_trusted(self):
        """Stock never checks ``enabled`` on the signin endpoint — the flag
        only hides the login button — so a disabled provider (Odoo.com,
        Google, Azure are all present and off in prod) is reachable through a
        hand-built URL. Its e-mail claim must not be able to claim an account."""
        existing = self._password_user("admin.person@mimer.nu")
        self.provider.enabled = False

        with self.assertLogs(LOGGER, "WARNING") as logs:
            relinked = self._signin("sub-attack", "admin.person@mimer.nu")
            created = self._signin("sub-attack2", "helt.ny@mimer.nu")

        self.assertIsNone(relinked)
        self.assertIsNone(created)
        self.assertFalse(existing.oauth_uid)
        self.assertFalse(self._by_login("helt.ny@mimer.nu"))
        self.assertIn("not enabled", logs.output[0])

    def test_account_linked_to_another_provider_is_not_relinked(self):
        """A stale subject from the same provider is the recreated AD account
        (test_stale_subject_is_overwritten). A link to a *different* provider
        is somebody's deliberate setup and is left alone."""
        other_provider = self.provider.copy({"name": "Annan leverantör"})
        existing = self._password_user(
            "annan.leverantor@mimer.nu",
            oauth_provider_id=other_provider.id,
            oauth_uid="sub-hos-annan",
        )

        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-keycloak", "annan.leverantor@mimer.nu")

        self.assertIsNone(login)
        self.assertEqual(existing.oauth_provider_id, other_provider)
        self.assertEqual(existing.oauth_uid, "sub-hos-annan")
        self.assertIn("another OAuth provider", logs.output[0])

    def test_domain_list_follows_the_system_parameter(self):
        self.env["ir.config_parameter"].sudo().set_param(
            AUTO_CREATE_DOMAINS_PARAM, "mimer.nu, @Bostad.Example "
        )

        login = self._signin("sub-annan-doman", "nagon@bostad.example")

        self.assertEqual(login, "nagon@bostad.example")
        self.assertTrue(self._by_login("nagon@bostad.example"))

    def test_default_domain_parameter_is_shipped_as_data(self):
        """The module is already installed in prod and post_init_hook never
        runs on an upgrade, so the default has to come from a data file."""
        param = self.env.ref("onecore_auth.param_auto_create_email_domains")

        self.assertEqual(param.key, AUTO_CREATE_DOMAINS_PARAM)
        self.assertEqual(param.value, "mimer.nu")

    def test_callers_no_user_creation_flag_is_respected(self):
        """Stock defines the flag as "a miss stays a miss" (the Odoo-account
        route sets it). Ours is only an internal means to reach the miss."""
        login = self._signin(
            "sub-flagga",
            "flagga@mimer.nu",
            users=self.env["res.users"].with_context(no_user_creation=True),
        )

        self.assertIsNone(login)
        self.assertFalse(self._by_login("flagga@mimer.nu"))

    # ------------------------------------------------------------------
    # Re-link
    # ------------------------------------------------------------------
    def test_existing_password_user_is_relinked_not_duplicated(self):
        """Gustav Pettersson's case (prod 2026-09-21): an active employee who
        has always logged in with a password. After this login they count as
        an SSO user — which is also what the ordering-department backfill
        looks at (oauth_uid) when deciding whether to wait for them."""
        user = self._password_user("gustav@mimer.nu")
        self.assertFalse(user.oauth_uid)
        count_before = self.Users.search_count([])

        with self.assertLogs(LOGGER, INFO) as logs:
            login = self._signin(
                "sub-gustav", "Gustav@mimer.nu", office_location="Distrikt Student"
            )

        self.assertEqual(login, "gustav@mimer.nu")
        self.assertEqual(self.Users.search_count([]), count_before)
        self.assertEqual(user.oauth_uid, "sub-gustav")
        self.assertEqual(user.oauth_provider_id, self.provider)
        self.assertEqual(user.oauth_access_token, "tok")
        self.assertEqual(user.ad_office_location, "Distrikt Student")
        self.assertTrue(any("re-linked" in line for line in logs.output))

    def test_relinked_employee_gets_request_admin_and_loses_nothing(self):
        """Every mimer.nu account needs Admin Ärendehantering — there is no
        other way to work in Odoo the way Mimer does (Sebastian 2026-09-21).
        Found by testing locally: a re-linked account with only the basic
        role landed in Discuss and could see no requests. Groups are only
        added; whatever the person already had stays."""
        extra = self.env.ref("base.group_partner_manager")
        user = self._password_user("begransad@mimer.nu")
        user.write({"group_ids": [(4, extra.id)]})
        self.assertFalse(user.has_group("maintenance.group_equipment_manager"))
        groups_before = user.group_ids

        with self.assertLogs(LOGGER, INFO) as logs:
            self._signin("sub-begransad", "begransad@mimer.nu")

        self.assertTrue(user.has_group("maintenance.group_equipment_manager"))
        self.assertLessEqual(groups_before, user.group_ids)
        self.assertTrue(any("added group ids" in line for line in logs.output))

    def test_relinked_employee_who_already_has_it_is_not_rewritten(self):
        user = self._password_user("harredan@mimer.nu")
        user.write(
            {"group_ids": [(4, self.env.ref("maintenance.group_equipment_manager").id)]}
        )
        groups_before = user.group_ids

        with self.assertLogs(LOGGER, INFO) as logs:
            self._signin("sub-harredan", "harredan@mimer.nu")

        self.assertEqual(user.group_ids, groups_before)
        self.assertFalse(any("added group ids" in line for line in logs.output))

    def test_relinked_contractor_is_not_promoted(self):
        """External contractors are the one group that works without Admin
        Ärendehantering. They normally never get here (the domain gate), but
        one with a mimer.nu address must stay a contractor."""
        contractor_group = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor"
        )
        user = self._password_user("entreprenor@mimer.nu")
        user.write({"group_ids": [(4, contractor_group.id)]})
        groups_before = user.group_ids

        login = self._signin("sub-entreprenor", "entreprenor@mimer.nu")

        self.assertEqual(login, "entreprenor@mimer.nu")
        self.assertEqual(user.oauth_uid, "sub-entreprenor")
        self.assertEqual(user.group_ids, groups_before)
        self.assertFalse(user.has_group("maintenance.group_equipment_manager"))

    def test_stale_subject_is_overwritten(self):
        """The AD account was recreated and Keycloak issued a new subject —
        what the oauth_uid runbook fixes with SQL today."""
        user = self._password_user(
            "aterskapad@mimer.nu",
            oauth_provider_id=self.provider.id,
            oauth_uid="sub-gammal",
        )

        login = self._signin("sub-ny-efter-aterskapande", "aterskapad@mimer.nu")

        self.assertEqual(login, "aterskapad@mimer.nu")
        self.assertEqual(user.oauth_uid, "sub-ny-efter-aterskapande")

    def test_relink_matches_the_contact_email_when_the_login_differs(self):
        user = self._password_user("kortnamn", email="Anna.Svensson@Mimer.nu")
        count_before = self.Users.search_count([])

        login = self._signin("sub-anna", " anna.svensson@mimer.nu ")

        self.assertEqual(login, "kortnamn")
        self.assertEqual(user.oauth_uid, "sub-anna")
        self.assertEqual(self.Users.search_count([]), count_before)

    def test_misspelt_login_is_not_guessed_at(self):
        """Gabriel's case (prod 2026-09-21): gabriel.davidson@ in Odoo,
        gabriel.davidsson@ in AD. Matching is exact on purpose — a fuzzy
        match could hand one person another person's account. The cost is a
        duplicate, so the creation is logged with name and e-mail, and the
        release checklist looks for these before go-live."""
        existing = self._password_user("gabriel.davidson@mimer.nu")

        with self.assertLogs(LOGGER, INFO) as logs:
            login = self._signin(
                "sub-gabriel", "gabriel.davidsson@mimer.nu", name="Gabriel Davidsson"
            )

        self.assertEqual(login, "gabriel.davidsson@mimer.nu")
        self.assertFalse(existing.oauth_uid)
        created = [line for line in logs.output if "auto-created" in line]
        self.assertTrue(created)
        self.assertIn("gabriel.davidsson@mimer.nu", created[0])
        self.assertIn("Gabriel Davidsson", created[0])

    def test_like_wildcards_in_the_address_match_nothing_else(self):
        """=ilike is a LIKE: unescaped, the "_" in anna_berg@ matches the "."
        in anna.berg@ and the newcomer would be logged in as somebody else,
        with their groups. Same for "%"."""
        dotted = self._password_user("kort1", email="anna.berg@mimer.nu")
        longer = self._password_user("kort2", email="annaXYZberg@mimer.nu")

        underscore_login = self._signin("sub-underscore", "anna_berg@mimer.nu")
        percent_login = self._signin("sub-percent", "anna%berg@mimer.nu")

        self.assertEqual(underscore_login, "anna_berg@mimer.nu")
        self.assertEqual(percent_login, "anna%berg@mimer.nu")
        self.assertFalse(dotted.oauth_uid)
        self.assertFalse(longer.oauth_uid)

    def test_archived_leftover_does_not_hide_the_active_account(self):
        """An archived account whose login is the address, and the person's
        real account under a short login with that contact e-mail. Searching
        login first found only the archived one and denied the login."""
        archived = self._password_user("dubbel@mimer.nu")
        archived.action_archive()
        active = self._password_user("kortlogin", email="dubbel@mimer.nu")

        login = self._signin("sub-dubbel", "dubbel@mimer.nu")

        self.assertEqual(login, "kortlogin")
        self.assertEqual(active.oauth_uid, "sub-dubbel")
        self.assertFalse(archived.oauth_uid)
        self.assertFalse(archived.active)

    def test_one_archived_and_one_active_sharing_the_email_picks_the_active(self):
        archived = self._password_user("gammal", email="delas@mimer.nu")
        archived.action_archive()
        active = self._password_user("aktuell", email="delas@mimer.nu")

        login = self._signin("sub-delas", "delas@mimer.nu")

        self.assertEqual(login, "aktuell")
        self.assertEqual(active.oauth_uid, "sub-delas")

    def test_two_users_sharing_the_email_are_left_alone(self):
        first = self._password_user("forsta", email="delad@mimer.nu")
        second = self._password_user("andra", email="delad@mimer.nu")

        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-delad", "delad@mimer.nu")

        self.assertIsNone(login)
        self.assertFalse(first.oauth_uid)
        self.assertFalse(second.oauth_uid)
        self.assertFalse(self._by_login("delad@mimer.nu"))
        self.assertIn("Not guessing", logs.output[0])

    def test_archived_user_is_denied_and_stays_archived(self):
        """Somebody who has left is not let back in because their AD account
        still exists — and no fresh account is created next to the old one."""
        user = self._password_user("slutat@mimer.nu")
        user.action_archive()
        count_before = self.Users.search_count([])

        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-slutat", "slutat@mimer.nu")

        self.assertIsNone(login)
        self.assertFalse(user.active)
        self.assertFalse(user.oauth_uid)
        self.assertEqual(self.Users.search_count([]), count_before)
        self.assertIn("archived", logs.output[0])

    # ------------------------------------------------------------------
    # Robustness
    # ------------------------------------------------------------------
    def test_database_error_leaves_the_transaction_usable(self):
        """A failed INSERT aborts the whole Postgres transaction. Without the
        savepoint the controller's next query would fail with
        InFailedSqlTransaction, from a place that points nowhere near here."""
        Users = self.env.registry["res.users"]
        original_create = Users.create

        def failing_create(records, vals_list):
            records.env.cr.execute("SELECT 1 / 0")
            return original_create(records, vals_list)

        with patch.object(Users, "create", autospec=True, side_effect=failing_create), \
                mute_logger("odoo.sql_db"), \
                self.assertLogs(LOGGER, "ERROR") as logs:
            login = self._signin("sub-dbfel", "dbfel@mimer.nu")

        self.assertIsNone(login)
        self.assertIn("could not re-link or create", logs.output[0])
        # The savepoint rolled back only our attempt: the cursor still works
        self.assertFalse(self._by_login("dbfel@mimer.nu"))

    def test_create_works_when_the_request_has_no_user(self):
        """Found by logging in for real (2026-09-21); no test or shell replay
        could see it. /auth_oauth/signin is auth='none', so the transaction's
        default environment has no user at all. create() leaves the avatar to
        be computed at the next flush; left to the savepoint's exit, that
        flush ran in the default environment, ir.attachment asked for the
        current user's groups, got an empty res.users() and raised — after
        "auto-created" had already been logged — and the login was denied.

        Tests and the shell always have a uid, so the default environment is
        swapped for a user-less one here to reproduce the request."""
        from odoo import api

        transaction = self.env.transaction
        original = transaction.default_env
        transaction.default_env = api.Environment(self.env.cr, None, {})
        try:
            with self.assertNoLogs(LOGGER, "ERROR"):
                login = self._signin("sub-utan-uid", "utan.uid@mimer.nu", name="Utan Uid")
        finally:
            transaction.default_env = original

        self.assertEqual(login, "utan.uid@mimer.nu")
        self.assertTrue(self._by_login("utan.uid@mimer.nu"))

    def test_concurrent_first_login_is_denied_honestly(self):
        """A double click, two tabs or two browsers on the very first login:
        the other request wins the INSERT (or the re-link write) and ours
        fails on unique(login) or a serialization failure. There is no
        fallback that works — the two requests carry different access
        tokens and there is one oauth_access_token column, and the winner's
        row is invisible to our REPEATABLE READ snapshot — so this request is
        denied with an INFO line saying why, no ERROR, and the person's next
        attempt takes the stock path (review of PR #292, finding 3)."""
        from psycopg2 import errors as pg_errors

        Users = self.env.registry["res.users"]
        for error in (pg_errors.UniqueViolation, pg_errors.SerializationFailure):
            with self.subTest(error=error.__name__), \
                    patch.object(Users, "create", autospec=True, side_effect=error("simulated")), \
                    self.assertNoLogs(LOGGER, "ERROR"), \
                    self.assertLogs(LOGGER, INFO) as logs:
                login = self._signin("sub-samtidig", "samtidig@mimer.nu")

            self.assertIsNone(login)
            self.assertFalse(self._by_login("samtidig@mimer.nu"))
            self.assertTrue(any("concurrent login" in line for line in logs.output))
            # The savepoint rolled back only our attempt: the cursor still works
            self.assertTrue(self.Users.search_count([]))

    # ------------------------------------------------------------------
    # email_verified (blocker in the review of PR #292)
    # ------------------------------------------------------------------
    def test_unverified_email_never_relinks(self):
        """The takeover the review describes: a user with a Keycloak session
        edits their own e-mail to a colleague's in the account console and
        logs in before the Microsoft sync resets it. The address is only
        acted on when the IdP vouches for it."""
        colleague = self._password_user("kollega@mimer.nu")
        for claim in (False, None, "true", 1):
            with self.subTest(email_verified=claim), self.assertLogs(LOGGER, "WARNING") as logs:
                login = self._signin("sub-angripare", "kollega@mimer.nu", email_verified=claim)

            self.assertIsNone(login)
            self.assertFalse(colleague.oauth_uid)
            self.assertIn("not verified by the identity provider", logs.output[0])

    def test_missing_email_verified_claim_is_denied(self):
        """Absent means unverified. The warning must not be the "no email"
        one: the scope is fine, it is Trust Email on the IdP that is off."""
        with self.assertLogs(LOGGER, "WARNING") as logs:
            login = self._signin("sub-utan-flagga", "ny.utan.flagga@mimer.nu", email_verified=None)

        self.assertIsNone(login)
        self.assertFalse(self._by_login("ny.utan.flagga@mimer.nu"))
        self.assertIn("Trust Email", logs.output[0])
        self.assertNotIn("client scope", logs.output[0])

    def test_unverified_email_never_creates(self):
        """Creating a user under an unverified address is impersonation of
        whoever will later own that address; denied on the create path too."""
        with self.assertLogs(LOGGER, "WARNING"):
            login = self._signin("sub-overifierad", "ny.overifierad@mimer.nu", email_verified=False)

        self.assertIsNone(login)
        self.assertFalse(self._by_login("ny.overifierad@mimer.nu"))

    # ------------------------------------------------------------------
    # Matching edge cases (review of PR #292, findings 4 and 5)
    # ------------------------------------------------------------------
    def test_mixed_case_legacy_login_is_relinked_not_duplicated(self):
        """onecore_base_extension lowercases logins on write, but rows from
        before it exist. With no contact e-mail, an exact login comparison
        matched nothing and the person got a duplicate at first login."""
        legacy = self._password_user("tmp.legacy@mimer.nu", email=False)
        self.env.cr.execute(
            "UPDATE res_users SET login = %s WHERE id = %s",
            ("Firstname.Lastname@mimer.nu", legacy.id),
        )
        legacy.invalidate_recordset(["login"])
        self.assertEqual(legacy.login, "Firstname.Lastname@mimer.nu")
        count_before = self.Users.search_count([])

        login = self._signin("sub-legacy", "firstname.lastname@mimer.nu")

        self.assertEqual(login, "Firstname.Lastname@mimer.nu")
        self.assertEqual(legacy.oauth_uid, "sub-legacy")
        self.assertEqual(self.Users.search_count([]), count_before)

    def test_non_ascii_local_part_is_accepted(self):
        """email_normalize keeps a non-ASCII local part as it is, so comparing
        it with a lowercased copy rejected every Å/Ä/Ö address with a warning
        pointing at the e-mail scope. Swedish names are not far-fetched."""
        with self.assertNoLogs(LOGGER, "WARNING"):
            login = self._signin("sub-asa", "Åsa.Öberg@Mimer.nu", name="Åsa Öberg")

        self.assertEqual(login, "åsa.öberg@mimer.nu")
        user = self._by_login("åsa.öberg@mimer.nu")
        self.assertEqual(len(user), 1)
        self.assertEqual(user.oauth_uid, "sub-asa")

        # Second login: stock path, no duplicate
        self.assertEqual(self._signin("sub-asa", "Åsa.Öberg@Mimer.nu"), "åsa.öberg@mimer.nu")
        self.assertEqual(len(self._by_login("åsa.öberg@mimer.nu")), 1)

    def test_non_ascii_address_relinks_an_existing_account(self):
        existing = self._password_user("kortnamn2", email="åsa.öberg@mimer.nu")

        login = self._signin("sub-asa2", "Åsa.Öberg@mimer.nu")

        self.assertEqual(login, "kortnamn2")
        self.assertEqual(existing.oauth_uid, "sub-asa2")

    # ------------------------------------------------------------------
    # Migration (review of PR #292, finding 2)
    # ------------------------------------------------------------------
    def test_migration_adopts_a_hand_made_parameter(self):
        """A parameter created under Systemparametrar has no xml id, so the
        noupdate data record would INSERT a second row and hit the unique
        key — inside the odoo-module-upgrade Job. The pre-migration registers
        the hand-made row under the data file's xml id first."""
        from importlib.machinery import SourceFileLoader
        from pathlib import Path

        migration = SourceFileLoader(
            "onecore_auth_pre_migration_19_0_1_2",
            str(Path(__file__).resolve().parents[1] / "migrations" / "19.0.1.2" / "pre-migration.py"),
        ).load_module()
        Params = self.env["ir.config_parameter"].sudo()
        xmlid = "onecore_auth.param_auto_create_email_domains"

        # Simulate the pre-upgrade database: no xml id, a hand-made value
        self.env.ref(xmlid).unlink() if self.env.ref(xmlid, raise_if_not_found=False) else None
        Params.search([("key", "=", AUTO_CREATE_DOMAINS_PARAM)]).unlink()
        Params.set_param(AUTO_CREATE_DOMAINS_PARAM, "mimer.nu,exempel.se")
        hand_made = Params.search([("key", "=", AUTO_CREATE_DOMAINS_PARAM)])
        self.assertTrue(hand_made)
        self.assertFalse(self.env.ref(xmlid, raise_if_not_found=False))

        migration.migrate(self.env.cr, "19.0.1.1")
        self.env.invalidate_all()

        adopted = self.env.ref(xmlid)
        self.assertEqual(adopted, hand_made)
        self.assertEqual(adopted.value, "mimer.nu,exempel.se")
        self.assertTrue(
            self.env["ir.model.data"].search([("module", "=", "onecore_auth"),
                                              ("name", "=", "param_auto_create_email_domains")]).noupdate
        )

        # Idempotent: a second run inserts nothing
        migration.migrate(self.env.cr, "19.0.1.1")
        self.assertEqual(
            self.env["ir.model.data"].search_count(
                [("module", "=", "onecore_auth"), ("name", "=", "param_auto_create_email_domains")]
            ),
            1,
        )

    def test_non_string_email_is_treated_as_missing(self):
        with self.assertLogs(LOGGER, "WARNING"):
            login = self._signin("sub-lista", ["nagon@mimer.nu"])

        self.assertIsNone(login)
