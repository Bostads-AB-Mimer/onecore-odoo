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


@tagged("onecore")
class TestHasUnreadMasterKeyChange(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.request = create_maintenance_request(self.env, master_key=False)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_master_key_change"])
        return record

    def test_internal_user_sees_unread_after_change(self):
        self.request.with_user(self.internal_user).write({"master_key": True})
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_master_key_change)

    def test_external_user_sees_unread_after_change(self):
        self.request.with_user(self.internal_user).write({"master_key": True})
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_master_key_change)

    def test_no_change_means_no_unread(self):
        record = self._refresh(self.external_user)
        self.assertFalse(record.has_unread_master_key_change)
        record = self._refresh(self.internal_user)
        self.assertFalse(record.has_unread_master_key_change)

    def test_ack_clears_unread_for_everyone(self):
        # The ack is one shared timestamp — clearing it on the request must
        # clear the chip for every viewer, regardless of role.
        self.request.with_user(self.internal_user).write({"master_key": True})
        self.request.master_key_ack_at = (
            self.request.master_key_changed_at + timedelta(seconds=1)
        )
        self.assertFalse(self._refresh(self.external_user).has_unread_master_key_change)
        self.assertFalse(self._refresh(self.internal_user).has_unread_master_key_change)

    def test_new_change_after_ack_reappears(self):
        self.request.with_user(self.internal_user).write({"master_key": True})
        self.request.master_key_ack_at = (
            self.request.master_key_changed_at + timedelta(seconds=1)
        )
        self.assertFalse(self._refresh(self.external_user).has_unread_master_key_change)

        # Toggle back off — change again.
        self.request.with_user(self.internal_user).write({"master_key": False})
        # Push the new change one second past the ack so the second-resolution
        # comparison resolves as "after".
        self.request.master_key_changed_at = (
            self.request.master_key_ack_at + timedelta(seconds=1)
        )
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_master_key_change)
