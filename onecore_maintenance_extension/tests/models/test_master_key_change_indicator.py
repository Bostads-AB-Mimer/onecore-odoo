"""Tests for the master-key-change notification (MIM-1846)."""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


@tagged("onecore")
class TestMasterKeyChangeTimestamp(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.request = create_maintenance_request(self.env, master_key=False)

    def test_write_sets_timestamp_when_master_key_changes(self):
        self.assertFalse(self.request.master_key_changed_at)
        self.request.with_user(self.internal_user).write({"master_key": True})
        self.assertTrue(self.request.master_key_changed_at)

    def test_write_does_not_set_timestamp_when_master_key_unchanged(self):
        # Writing the same value must not bump the timestamp.
        self.request.with_user(self.internal_user).write({"master_key": False})
        self.assertFalse(self.request.master_key_changed_at)

    def test_write_does_not_set_timestamp_for_other_fields(self):
        self.request.with_user(self.internal_user).write({"name": "Ny titel"})
        self.assertFalse(self.request.master_key_changed_at)

    def test_create_does_not_set_timestamp(self):
        fresh = create_maintenance_request(self.env, master_key=True)
        self.assertFalse(fresh.master_key_changed_at)
