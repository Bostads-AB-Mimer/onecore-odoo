"""Tests for MIM-1970/2011 — "Beställande avdelning" on maintenance requests.

Covers the create() stamp (including the Mina sidor case, where create_uid is
a technical integration user with no department), the backfill cron and its
guess stamp, and the search facet that makes the follow-up views
MIM-1975/1976/1977 pure configuration.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services.ordering_department_service import (
    MIMER_NU_DEPARTMENT_PARAM,
)

from ...utils.test_utils import (
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)


@tagged("onecore")
class TestOrderingDepartmentService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.district_user = create_internal_user(
            self.env, ad_office_location="Distrikt Öst"
        )
        self.other_user = create_internal_user(
            self.env, ad_office_location="Fastighetsserviceenheten"
        )
        # No department: a service account, a consultant, or someone who has
        # not logged in since the Keycloak mapper was added.
        self.blank_user = create_internal_user(self.env)

    def _clear_ordering(self, *requests):
        """Make a request look like it predates the field."""
        for request in requests:
            request.sudo().write(
                {"ordering_department": False, "ordering_backfilled_at": False}
            )

    def _backfill(self):
        return self.env["maintenance.request"]._cron_backfill_ordering_department()

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def test_create_stamps_the_creators_department(self):
        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_department, "Distrikt Öst")
        # Not a guess: it was recorded while we knew
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_prefers_owner_over_creator(self):
        """owner_user_id is the orderer when it is set; create_uid is a fallback."""
        request = create_maintenance_request(
            self.env(user=self.district_user), owner_user_id=self.other_user.id
        )

        self.assertEqual(request.create_uid, self.district_user)
        self.assertEqual(request.ordering_department, "Fastighetsserviceenheten")

    def test_create_does_not_depend_on_resource_group_membership(self):
        """The whole point of the redesign: the department is an attribute of
        the person, read off the user, never derived from which resource
        groups they happen to be a member of."""
        team = create_maintenance_team(
            self.env, name="Driftenheten", member_ids=[(4, self.district_user.id)]
        )
        self.assertIn(self.district_user, team.member_ids)

        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_department, "Distrikt Öst")

    def test_create_strips_the_value(self):
        self.blank_user.write({"ad_office_location": "  IT-enheten  "})

        request = create_maintenance_request(self.env(user=self.blank_user))

        self.assertEqual(request.ordering_department, "IT-enheten")

    def test_create_leaves_the_field_empty_and_unstamped_without_a_department(self):
        """An orderer without an AD value: empty is the truthful answer, and
        the request is left *unstamped* so the backfill can come back for it
        once the value has arrived (first SSO login, seed import). See
        test_backfill_picks_up_a_department_that_arrived_late."""
        request = create_maintenance_request(self.env(user=self.blank_user))

        self.assertFalse(request.ordering_department)
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_whitespace_only_value_counts_as_no_department(self):
        self.blank_user.write({"ad_office_location": "   "})

        request = create_maintenance_request(self.env(user=self.blank_user))

        self.assertFalse(request.ordering_department)

    def test_create_stamps_mimer_nu_requests_with_kundcenter(self):
        """Tenant reports have no department. Kundcenter receives, categorises
        and distributes them, so in business terms they are the orderer."""
        request = create_maintenance_request(
            self.env(user=self.blank_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.ordering_department, "Kundcenter")
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_from_mimer_nu_ignores_the_integration_users_own_department(self):
        """MIM-1970's decisive case. Mina sidor-ärenden arrive over XML-RPC
        with a technical integration user as create_uid. Whatever that
        account's AD value is says nothing about who ordered."""
        integration_user = create_internal_user(
            self.env, ad_office_location="IT-enheten"
        )

        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.create_uid, integration_user)
        self.assertEqual(request.ordering_department, "Kundcenter")

    def test_mimer_nu_department_follows_the_system_parameter(self):
        """The AD spelling of the Kundcenter unit is the business's to decide;
        following it must not take a release."""
        self.env["ir.config_parameter"].sudo().set_param(
            MIMER_NU_DEPARTMENT_PARAM, " Kundcenterenheten "
        )

        request = create_maintenance_request(
            self.env(user=self.blank_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.ordering_department, "Kundcenterenheten")

    def test_create_keeps_a_department_stamped_by_the_caller(self):
        """core over XML-RPC (and later MIM-1971) wins over the derivation."""
        request = create_maintenance_request(
            self.env(user=self.district_user), ordering_department="Uthyrningsenheten"
        )

        self.assertEqual(request.ordering_department, "Uthyrningsenheten")

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------
    def test_backfill_stamps_old_requests_and_marks_them_as_guessed(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        processed = self._backfill()

        self.assertGreaterEqual(processed, 1)
        self.assertEqual(request.ordering_department, "Distrikt Öst")
        # The stamp is what separates a guess from a recorded fact
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_prefers_owner_over_creator(self):
        request = create_maintenance_request(
            self.env(user=self.district_user), owner_user_id=self.other_user.id
        )
        self._clear_ordering(request)

        self._backfill()

        self.assertEqual(request.ordering_department, "Fastighetsserviceenheten")

    def test_backfill_never_touches_team_resource_or_stage(self):
        """Display only: the backfill must not reroute anything."""
        team = create_maintenance_team(self.env, member_ids=[(4, self.other_user.id)])
        request = create_maintenance_request(
            self.env(user=self.district_user),
            maintenance_team_id=team.id,
            user_id=self.other_user.id,
        )
        self._clear_ordering(request)
        team_before = request.maintenance_team_id
        user_before = request.user_id
        stage_before = request.stage_id

        self._backfill()

        self.assertEqual(request.maintenance_team_id, team_before)
        self.assertEqual(request.user_id, user_before)
        self.assertEqual(request.stage_id, stage_before)

    def test_backfill_is_self_consuming(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        first = self._backfill()
        second = self._backfill()

        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)

    def test_backfill_resolves_mimer_nu_to_kundcenter(self):
        integration_user = create_internal_user(
            self.env, ad_office_location="IT-enheten"
        )
        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )
        self._clear_ordering(request)

        self._backfill()

        self.assertEqual(request.ordering_department, "Kundcenter")

    def test_backfill_gives_up_on_an_orderer_who_can_never_get_a_value(self):
        """No OAuth link (service accounts, contractors): nothing will ever
        write a department for them. The field stays empty, but the timestamp
        is written — otherwise the domain stops being self-consuming and
        those rows come back every hour, forever."""
        self.assertFalse(self.blank_user.oauth_uid)
        request = create_maintenance_request(self.env(user=self.blank_user))
        self.assertFalse(request.ordering_backfilled_at)

        first = self._backfill()

        self.assertGreaterEqual(first, 1)
        self.assertFalse(request.ordering_department)
        # "Looked at it, could not tell" — that is what makes it drop out
        self.assertTrue(request.ordering_backfilled_at)

        second = self._backfill()
        self.assertEqual(second, 0)

    def test_backfill_gives_up_on_an_archived_orderer_without_a_value(self):
        """Left the company before the mapper went live: no login will ever
        come, so waiting is pointless."""
        sso_user = create_internal_user(self.env, oauth_uid="sub-archived")
        request = create_maintenance_request(self.env(user=sso_user))
        sso_user.action_archive()

        self._backfill()

        self.assertFalse(request.ordering_department)
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_waits_for_an_sso_user_who_has_not_logged_in_yet(self):
        """The rollout case. The department is written at each person's next
        SSO login after the Keycloak mapper went live, so an active SSO user
        without a value is simply early. Their requests are left alone —
        unstamped — and resolved by a later run once the value is there.
        Giving up here would strand every legacy request in the weeks after
        release, and reopening them is a manual job nobody should need."""
        sso_user = create_internal_user(self.env, oauth_uid="sub-not-yet")
        request = create_maintenance_request(self.env(user=sso_user))
        self.assertFalse(request.ordering_department)

        self._backfill()
        self.assertFalse(request.ordering_department)
        self.assertFalse(request.ordering_backfilled_at)

        # The user logs in; onecore_auth writes the claim
        sso_user.write({"ad_office_location": "Projektenheten"})
        self._backfill()

        self.assertEqual(request.ordering_department, "Projektenheten")
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_does_not_revisit_a_request_it_gave_up_on(self):
        """The flip side: once the backfill has stamped "could not tell", a
        value that arrives after that is not applied — the domain is
        self-consuming. Reopening such rows is a one-off job (clear
        ordering_backfilled_at where ordering_department is empty), and a
        harmless one: a row that still cannot be resolved is just stamped
        again."""
        request = create_maintenance_request(self.env(user=self.blank_user))
        self._backfill()
        self.assertTrue(request.ordering_backfilled_at)

        self.blank_user.write({"ad_office_location": "Projektenheten"})
        processed = self._backfill()

        self.assertEqual(processed, 0)
        self.assertFalse(request.ordering_department)

        request.sudo().write({"ordering_backfilled_at": False})
        self._backfill()
        self.assertEqual(request.ordering_department, "Projektenheten")

    def test_backfill_counts_the_department_of_an_archived_creator(self):
        """Old requests were often created by people who have since left. An
        archived user's department is still the truthful answer for what they
        ordered back then — the user map must not be active-filtered."""
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)
        self.district_user.action_archive()

        self._backfill()

        self.assertEqual(request.ordering_department, "Distrikt Öst")

    def test_backfill_strips_the_value(self):
        self.blank_user.write({"ad_office_location": "  IT-enheten  "})
        request = create_maintenance_request(self.env(user=self.blank_user))
        self._clear_ordering(request)

        self._backfill()

        self.assertEqual(request.ordering_department, "IT-enheten")

    def test_backfill_leaves_no_chatter_note(self):
        """SKIP_FIELDS: the backfill writes outside the creating_records
        context, so without it every stamped request would get a note."""
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)
        messages_before = len(request.message_ids)

        self._backfill()

        self.assertEqual(len(request.message_ids), messages_before)

    def test_create_and_backfill_agree(self):
        """Two write paths, one answer: whatever create stamps, the backfill
        must reproduce for the same orderer."""
        integration_user = create_internal_user(
            self.env, ad_office_location="IT-enheten"
        )
        cases = [
            (self.district_user, {}),
            (self.district_user, {"owner_user_id": self.other_user.id}),
            (integration_user, {"creation_origin": "mimer-nu"}),
        ]
        for user, extra in cases:
            with self.subTest(user=user.login, extra=extra):
                stamped = create_maintenance_request(self.env(user=user), **extra)
                guessed = create_maintenance_request(self.env(user=user), **extra)
                self._clear_ordering(guessed)

                self._backfill()

                self.assertTrue(stamped.ordering_department)
                self.assertEqual(guessed.ordering_department, stamped.ordering_department)

    # ------------------------------------------------------------------
    # Cron record / views
    # ------------------------------------------------------------------
    def test_backfill_cron_ships_inactive(self):
        """The cron must NOT run on deploy.

        Departments reach res.users through the login hook and the one-off
        seed import. Run before the seed, the backfill would stamp every
        legacy request "looked, could not tell" — permanently, because the
        domain is self-consuming. Someone flipping this to True has to change
        this test and read why first.
        """
        cron = self.env.ref(
            "onecore_maintenance_extension.ir_cron_backfill_ordering_department"
        )

        self.assertEqual(cron.model_id.model, "maintenance.request")
        self.assertFalse(cron.active)
        self.assertIn("_cron_backfill_ordering_department", cron.code)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "hours"))

    def test_search_view_exposes_the_facet_and_grouping(self):
        """What makes MIM-1975/1976/1977 configuration instead of development."""
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_search_extension"
        )

        self.assertIn('name="ordering_department"', view.arch_db)
        self.assertIn("'group_by': 'ordering_department'", view.arch_db)
        # The district click-filters pair on the stamped department string
        for district in ("Distrikt Mitt", "Distrikt Norr", "Distrikt Öst", "Distrikt Väst"):
            self.assertIn(
                "('ordering_department', '=', '%s')" % district, view.arch_db
            )

    def test_form_view_does_not_show_the_department(self):
        """A follow-up facet, not something the handler needs on the form."""
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_form_extension"
        )

        self.assertNotIn("ordering_department", view.arch_db)

    def test_list_view_offers_the_department_as_optional_column(self):
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_tree_extension"
        )

        self.assertIn('name="ordering_department" optional="hide"', view.arch_db)

    def test_no_ad_unit_mapping_is_left(self):
        """MIM-2011's mapping table, menu and category tie-break are gone:
        the department is stamped verbatim, nothing translates it."""
        self.assertNotIn("maintenance.ad.unit", self.env.registry)
        self.assertNotIn(
            "preferred_ordering_team_id",
            self.env["maintenance.request.category"]._fields,
        )
        self.assertNotIn("ordering_team_id", self.env["maintenance.request"]._fields)
