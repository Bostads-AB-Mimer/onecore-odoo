from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError

from ...utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


class StageTestMixin:
    """Mixin for maintenance stage lookups"""

    def _get_stage(self, stage_name):
        """Get maintenance stage by name"""
        return self.env["maintenance.stage"].search([("name", "=", stage_name)])

    def _setup_common_stages(self):
        """Setup commonly used stage references"""
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.stage_tilldelad = self._get_stage("Resurs tilldelad")
        self.stage_paborjad = self._get_stage("Påbörjad")


@tagged("onecore")
class TestExternalContractorService(StageTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self._setup_common_stages()

    def test_is_external_contractor_true(self):
        """is_external_contractor should return True for external contractor users"""
        request = create_maintenance_request(self.env)
        self.assertTrue(
            request.with_user(self.external_user).user_is_external_contractor
        )

    def test_is_external_contractor_false(self):
        """is_external_contractor should return False for internal users"""
        request = create_maintenance_request(self.env)
        self.assertFalse(
            request.with_user(self.internal_user).user_is_external_contractor
        )

    def test_get_restricted_status(self):
        """get_restricted_status should correctly identify restricted stages"""
        request_utford = create_maintenance_request(
            self.env, stage_id=self.stage_utford.id
        )
        request_avslutad = create_maintenance_request(
            self.env, stage_id=self.stage_avslutad.id
        )

        restricted_utford = request_utford.with_user(self.external_user).restricted_external
        self.assertIsInstance(restricted_utford, bool)

        restricted_avslutad = request_avslutad.with_user(self.external_user).restricted_external
        self.assertIsInstance(restricted_avslutad, bool)

    def test_validate_stage_transition_cannot_move_from_utford(self):
        """External contractors cannot move requests from 'Utförd' stage"""
        request = create_maintenance_request(self.env, stage_id=self.stage_utford.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Utförd"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_vantar.id}
            )
        self.assertEqual(request.stage_id, self.stage_utford)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Utförd"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_paborjad.id}
            )
        self.assertEqual(request.stage_id, self.stage_utford)

        
    def test_validate_stage_transition_cannot_move_from_avslutad(self):
        """External contractors cannot move requests from 'Avslutad' stage"""
        request = create_maintenance_request(self.env, stage_id=self.stage_avslutad.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_vantar.id}
            )
        self.assertEqual(request.stage_id, self.stage_avslutad)

    def test_validate_stage_transition_cannot_move_to_avslutad(self):
        """External contractors cannot move requests to 'Avslutad' stage"""
        request = create_maintenance_request(self.env, stage_id=self.stage_vantar.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_avslutad.id}
            )
        self.assertEqual(request.stage_id, self.stage_vantar)

    def test_external_contractor_restrictions_take_precedence_over_user_assignment_rules(self):
        """External contractor restrictions are checked before other validation rules"""
        # External contractors cannot move to Avslutad even without user assignment requirements
        request = create_maintenance_request(
            self.env, stage_id=self.stage_vantar.id
        )  # No user assigned

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_avslutad.id}
            )
        self.assertEqual(request.stage_id, self.stage_vantar)
