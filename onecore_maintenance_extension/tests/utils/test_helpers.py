# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from .test_utils import create_lease_option


@tagged("onecore")
class TestSelectActiveLease(TransactionCase):
    """Tests for select_active_lease helper function."""

    def setUp(self):
        super().setUp()
        from ...models.utils.helpers import select_active_lease

        self.select_active_lease = select_active_lease

    def test_selects_current_lease(self):
        """Current (status=0) should be selected first."""
        lease_current = create_lease_option(self.env, lease_status=0, lease_number="100")
        lease_upcoming = create_lease_option(self.env, lease_status=1, lease_number="200")
        lease_ended = create_lease_option(self.env, lease_status=3, lease_number="300")

        records = lease_current | lease_upcoming | lease_ended
        result = self.select_active_lease(records)
        self.assertEqual(result, lease_current)

    def test_selects_about_to_end_over_upcoming(self):
        """AboutToEnd (status=2) should be preferred over Upcoming (status=1)."""
        lease_upcoming = create_lease_option(self.env, lease_status=1, lease_number="100")
        lease_about_to_end = create_lease_option(self.env, lease_status=2, lease_number="200")

        records = lease_upcoming | lease_about_to_end
        result = self.select_active_lease(records)
        self.assertEqual(result, lease_about_to_end)

    def test_selects_upcoming_over_ended(self):
        """Upcoming (status=1) should be preferred over Ended (status=3)."""
        lease_ended = create_lease_option(self.env, lease_status=3, lease_number="300")
        lease_upcoming = create_lease_option(self.env, lease_status=1, lease_number="100")

        records = lease_ended | lease_upcoming
        result = self.select_active_lease(records)
        self.assertEqual(result, lease_upcoming)

    def test_falls_back_to_highest_lease_number(self):
        """When all leases have an unrecognized status, falls back to highest lease_number."""
        lease_low = create_lease_option(self.env, lease_status=99, lease_number="100")
        lease_high = create_lease_option(self.env, lease_status=99, lease_number="900")
        lease_mid = create_lease_option(self.env, lease_status=99, lease_number="500")

        records = lease_low | lease_high | lease_mid
        result = self.select_active_lease(records)
        self.assertEqual(result, lease_high)

    def test_single_lease_returns_it(self):
        """A single lease is always returned."""
        lease = create_lease_option(self.env, lease_status=3)

        records = lease
        result = self.select_active_lease(records)
        self.assertEqual(result, lease)
