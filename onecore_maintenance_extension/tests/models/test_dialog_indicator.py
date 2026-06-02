"""Tests for the bidirectional log-note dialog indicator (orange chip)."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


@tagged("onecore")
class TestDialogIndicator(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.request = create_maintenance_request(self.env)

    def _post_log_note(self, user, body="hej"):
        return self.request.with_user(user).message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(
            [
                "has_unread_supplier_dialog",
                "has_unread_internal_dialog",
            ]
        )
        return record

    def test_internal_user_sees_supplier_log_note(self):
        self._post_log_note(self.external_user)
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_supplier_dialog)
        self.assertFalse(record.has_unread_internal_dialog)

    def test_external_user_sees_internal_log_note(self):
        self._post_log_note(self.internal_user)
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_internal_dialog)
        self.assertFalse(record.has_unread_supplier_dialog)

    def test_internal_user_does_not_see_own_log_note(self):
        self._post_log_note(self.internal_user)
        record = self._refresh(self.internal_user)
        self.assertFalse(record.has_unread_supplier_dialog)

    def test_external_user_does_not_see_own_log_note(self):
        self._post_log_note(self.external_user)
        record = self._refresh(self.external_user)
        self.assertFalse(record.has_unread_internal_dialog)

    def test_acknowledge_clears_supplier_dialog_for_internal(self):
        self._post_log_note(self.external_user)
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_supplier_dialog)

        record.action_acknowledge_dialog()
        record = self._refresh(self.internal_user)
        self.assertFalse(record.has_unread_supplier_dialog)
        self.assertTrue(self.request.supplier_dialog_ack_at)

    def test_acknowledge_clears_internal_dialog_for_external(self):
        self._post_log_note(self.internal_user)
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_internal_dialog)

        record.action_acknowledge_dialog()
        record = self._refresh(self.external_user)
        self.assertFalse(record.has_unread_internal_dialog)
        self.assertTrue(self.request.internal_dialog_ack_at)

    def test_new_log_note_after_acknowledge_reappears(self):
        self._post_log_note(self.external_user)
        self._refresh(self.internal_user).action_acknowledge_dialog()
        self.assertFalse(
            self._refresh(self.internal_user).has_unread_supplier_dialog
        )

        self._post_log_note(self.external_user)
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_supplier_dialog)

    def test_tracking_notification_does_not_trigger_chip(self):
        # Status / field tracking produces message_type='notification', not 'comment'.
        # Simulate by writing a tracked field as the external user.
        stage = self.env["maintenance.stage"].search([], limit=1)
        if stage:
            self.request.with_user(self.external_user).write({"stage_id": stage.id})
        record = self._refresh(self.internal_user)
        self.assertFalse(record.has_unread_supplier_dialog)

    def test_send_message_subtype_does_not_trigger_chip(self):
        # 'Send message' uses mt_comment, not mt_note — only log notes count.
        self.request.with_user(self.external_user).message_post(
            body="public message",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        record = self._refresh(self.internal_user)
        self.assertFalse(record.has_unread_supplier_dialog)

    def test_acknowledge_invalidates_indicator_without_manual_refresh(self):
        # The action must invalidate the non-stored compute so the button's
        # invisible attribute re-evaluates immediately in the UI.
        self._post_log_note(self.external_user)
        record = self.request.with_user(self.internal_user)
        self.assertTrue(record.has_unread_supplier_dialog)

        record.action_acknowledge_dialog()
        # No manual invalidate_recordset between action and read.
        self.assertFalse(record.has_unread_supplier_dialog)


@tagged("onecore")
class TestMailMessageDialogUnread(TransactionCase):
    """Tests the orange-background flag exposed on mail.message."""

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.request = create_maintenance_request(self.env)

    def _post_log_note(self, user, body="hej"):
        return self.request.with_user(user).message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def test_internal_user_flags_supplier_log_note(self):
        msg = self._post_log_note(self.external_user)
        msg.invalidate_recordset(["is_dialog_unread_for_user"])
        self.assertTrue(msg.with_user(self.internal_user).is_dialog_unread_for_user)

    def test_external_user_flags_internal_log_note(self):
        msg = self._post_log_note(self.internal_user)
        msg.invalidate_recordset(["is_dialog_unread_for_user"])
        self.assertTrue(msg.with_user(self.external_user).is_dialog_unread_for_user)

    def test_own_log_note_is_not_flagged(self):
        msg = self._post_log_note(self.internal_user)
        msg.invalidate_recordset(["is_dialog_unread_for_user"])
        self.assertFalse(msg.with_user(self.internal_user).is_dialog_unread_for_user)

    def test_acknowledge_clears_flag(self):
        msg = self._post_log_note(self.external_user)
        msg.invalidate_recordset(["is_dialog_unread_for_user"])
        self.assertTrue(msg.with_user(self.internal_user).is_dialog_unread_for_user)

        self.request.with_user(self.internal_user).action_acknowledge_dialog()
        self.assertFalse(msg.with_user(self.internal_user).is_dialog_unread_for_user)

    def test_send_message_subtype_is_not_flagged(self):
        msg = self.request.with_user(self.external_user).message_post(
            body="public",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        msg.invalidate_recordset(["is_dialog_unread_for_user"])
        self.assertFalse(msg.with_user(self.internal_user).is_dialog_unread_for_user)
