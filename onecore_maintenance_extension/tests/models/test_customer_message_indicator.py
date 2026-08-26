"""Tests for the "Meddelande från kund" signal (MIM-1960).

The tenant -> case channel is detected by message_type = 'from_tenant', the
value onecore's work-order service writes when it forwards a Mina-sidor
message. Acknowledgement is shared within each audience and split between them,
mirroring action_acknowledge_dialog.
"""

import importlib.util
import os

from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools.sql import column_exists

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


def _get_or_create_mimer_user(env):
    """The integration account the work-order service posts as."""
    user = env["res.users"].sudo().search([("login", "=", "odoo@mimer.nu")], limit=1)
    if not user:
        user = (
            env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Mimer Integration",
                    "login": "odoo@mimer.nu",
                    # message_post() writes a mail.message tied to the request,
                    # which needs write access on maintenance.request. Mirror
                    # the internal-handler groups so the team record rule lets
                    # the post through (base.group_user alone fails it).
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                env.ref("base.group_user").id,
                                env.ref("maintenance.group_equipment_manager").id,
                            ],
                        )
                    ],
                }
            )
        )
    return user


def _post_tenant_message(
    request, mimer_user, body="Hur går det?", message_type="from_tenant"
):
    """Post exactly as odoo-adapter.addMessageToWorkOrder does: message_post
    with message_type='from_tenant' and the default note subtype."""
    return request.with_user(mimer_user).message_post(
        body=body, message_type=message_type
    )


def _load_ack_rename_migration():
    """Load migrations/19.0.1.0.6/pre-migration.py by path.

    The migration lives outside the importable package tree (the directory
    name is not a valid Python identifier), so it has to be loaded from its
    file location. Mirrors the idiom test_new_customer_info_indicator.py used
    for the 19.0.1.0.5 post-migration.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.6", "pre-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1960_pre_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CustomerMessageCase(TransactionCase):
    """Shared fixture: an internal user, a contractor on the request's team.

    The external-contractor record rule (security/maintenance.xml) only grants
    access to requests on the contractor's own team.
    """

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )


@tagged("onecore")
class TestLastCustomerMessageAt(CustomerMessageCase):
    def test_from_tenant_message_sets_the_timestamp(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self.assertEqual(self.request.last_customer_message_at, message.date)

    def test_newer_message_moves_the_timestamp_forward(self):
        _post_tenant_message(self.request, self.mimer_user)
        second = _post_tenant_message(self.request, self.mimer_user, body="Igen")
        self.assertEqual(self.request.last_customer_message_at, second.date)

    def test_other_message_types_are_ignored(self):
        _post_tenant_message(self.request, self.mimer_user, message_type="comment")
        self.assertFalse(self.request.last_customer_message_at)

    def test_no_message_means_no_timestamp(self):
        self.assertFalse(self.request.last_customer_message_at)

    def test_the_write_logs_no_audit_note(self):
        # The request is written on every inbound tenant message. Without a
        # SKIP_FIELDS entry, FieldChangeTracker posts a chatter note about the
        # field change on top of the tenant's own message.
        #
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_new_customer_info_indicator.py, test_master_key_change_indicator.py
        # and test_maintenance_workflow_service.py do.
        request = self.request.with_context(creating_records=False)
        before = set(request.message_ids.ids)
        _post_tenant_message(request, self.mimer_user)
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it must
        # be explicitly invalidated to see the note just posted.
        request.invalidate_recordset(["message_ids"])
        new_bodies = " ".join(
            request.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        # Assert on the field LABEL: FieldChangeTracker logs labels, never
        # field names. Asserting on the name would pass even with the
        # SKIP_FIELDS entry removed.
        self.assertNotIn("Senaste meddelande från kund", new_bodies)


@tagged("onecore")
class TestAckColumnRename(CustomerMessageCase):
    """The MIM-1844 ack pair is renamed, not duplicated: it only ever served
    the Mina-sidor channel, so its values carry over verbatim and MIM-1844's
    cutover baseline stays valid."""

    def test_new_names_exist(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("customer_message_ack_at", fields_)
        self.assertIn("customer_message_external_ack_at", fields_)

    def test_old_names_are_gone(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertNotIn("new_customer_info_ack_at", fields_)
        self.assertNotIn("new_customer_info_external_ack_at", fields_)

    def test_labels_are_swedish_so_acks_reach_the_audit_log(self):
        # FieldChangeTracker logs by field label; a missing/English label would
        # silently drop the acknowledgement from the chatter.
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("kund", fields_["customer_message_ack_at"].string.lower())
        self.assertIn(
            "entreprenör",
            fields_["customer_message_external_ack_at"].string.lower(),
        )


@tagged("onecore")
class TestAckRenameMigration(CustomerMessageCase):
    """Covers migrations/19.0.1.0.6/pre-migration.py directly. The suite
    installs modules fresh and never upgrades, so nothing else in the run
    exercises this script — see its own docstring for why it must be a
    pre-migration and why a rename resets both acks to NULL.

    TransactionCase rolls back and Postgres DDL is transactional, so
    renaming maintenance_request's columns inside a test is safe; each test
    ends with the columns back the way the ORM expects them (either the
    migration renamed them back, or it never touched them).
    """

    def setUp(self):
        super().setUp()
        self.migration = _load_ack_rename_migration()

    def test_path_b_renames_and_resets_stale_narrow_acks(self):
        # Simulate a test/dev database still on the unreleased MIM-1844
        # build: the old columns exist, and one carries a non-NULL ack
        # written under the old narrow discriminator.
        cr = self.env.cr
        cr.execute(
            "ALTER TABLE maintenance_request "
            'RENAME COLUMN "customer_message_ack_at" TO "new_customer_info_ack_at"'
        )
        cr.execute(
            "ALTER TABLE maintenance_request "
            'RENAME COLUMN "customer_message_external_ack_at" '
            'TO "new_customer_info_external_ack_at"'
        )
        stale_ack = fields.Datetime.now()
        cr.execute(
            "UPDATE maintenance_request SET new_customer_info_ack_at = %s "
            "WHERE id = %s",
            (stale_ack, self.request.id),
        )
        self.env.invalidate_all()

        self.migration.migrate(cr, "19.0.1.0.5")
        self.env.invalidate_all()

        # column_exists(), not a hand-rolled information_schema query: the
        # same false-positive class (missing table_schema = current_schema)
        # that review had removed from the migration itself (MIM-1960 F3).
        self.assertTrue(
            column_exists(cr, "maintenance_request", "customer_message_ack_at")
        )
        self.assertTrue(
            column_exists(cr, "maintenance_request", "customer_message_external_ack_at")
        )
        self.assertFalse(
            column_exists(cr, "maintenance_request", "new_customer_info_ack_at")
        )
        self.assertFalse(
            column_exists(
                cr, "maintenance_request", "new_customer_info_external_ack_at"
            )
        )
        self.assertFalse(self.request.customer_message_ack_at)
        self.assertFalse(self.request.customer_message_external_ack_at)

    def test_path_a_is_a_no_op_on_the_natural_test_schema(self):
        # The test database's schema already matches post-upgrade production:
        # only the new columns exist. This is also the shape of a real
        # 1.0.4 -> 1.0.6 production upgrade at the point this script runs
        # (see its docstring) — neither old nor new columns exist there
        # either, so the loop finds nothing on both counts, but asserting
        # against a seeded ack on the natural test schema is the closest
        # this suite can get to that without fabricating a third schema
        # shape.
        #
        # Stored-field writes through the ORM only dirty the cache
        # (odoo/orm/fields.py ~1503-1521) — nothing flushes it to the
        # database on its own, and the request was created under
        # creating_records=True, which skips FieldChangeTracker but not the
        # underlying deferral. flush_all() is required *before* migrate() so
        # the column genuinely holds the seeded value while the migration
        # runs, mirroring what a real ack write followed by a real upgrade
        # looks like.
        seeded_ack = fields.Datetime.now()
        self.request.customer_message_ack_at = seeded_ack
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.4")

        # Assert on the raw column, not through the ORM: env.invalidate_all()
        # defaults to flush=True (odoo/orm/environments.py ~357-366), which
        # would push the cached value back into the database *after*
        # migrate() ran and mask a real unconditional wipe. Reading straight
        # from Postgres is the only way this test can actually fail if the
        # reset guard regresses.
        self.env.cr.execute(
            "SELECT customer_message_ack_at FROM maintenance_request WHERE id = %s",
            (self.request.id,),
        )
        (stored_ack,) = self.env.cr.fetchone()
        self.assertEqual(stored_ack, seeded_ack)


@tagged("onecore")
class TestHasUnreadCustomerMessage(CustomerMessageCase):
    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record

    def test_from_tenant_message_raises_it_for_both_audiences(self):
        # "Statusen ska vara synlig för alla" — no group guard anywhere.
        _post_tenant_message(self.request, self.mimer_user)
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)
        self.assertTrue(self._refresh(self.external_user).has_unread_customer_message)

    def test_no_inbox_notification_needed(self):
        # The old MIM-1844 heuristic required one. The work-order service does
        # not create one, so requiring it missed real tenant messages.
        _post_tenant_message(self.request, self.mimer_user)
        self.env["mail.notification"].sudo().search(
            [
                ("mail_message_id.model", "=", "maintenance.request"),
                ("mail_message_id.res_id", "=", self.request.id),
            ]
        ).unlink()
        self.request.invalidate_recordset(["has_unread_customer_message"])
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)

    def test_comment_from_the_integration_user_does_not_raise_it(self):
        # The old heuristic matched any odoo@mimer.nu message with an inbox
        # notification, including plain comments.
        _post_tenant_message(self.request, self.mimer_user, message_type="comment")
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)

    def test_no_message_means_not_unread(self):
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)

    def test_reading_the_record_does_not_clear_it(self):
        _post_tenant_message(self.request, self.mimer_user)
        record = self._refresh(self.internal_user)
        _ = record.name  # simulate opening the form
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)


@tagged("onecore")
class TestAcknowledgeCustomerMessage(CustomerMessageCase):
    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record

    def test_internal_ack_clears_only_the_internal_side(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(
            self.internal_user
        ).action_acknowledge_customer_message()

        self.assertTrue(self.request.customer_message_ack_at)
        self.assertFalse(self.request.customer_message_external_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)
        self.assertTrue(self._refresh(self.external_user).has_unread_customer_message)

    def test_contractor_ack_clears_only_the_contractor_side(self):
        # A contractor's ack must never suppress the tenant's message for Mimer.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(
            self.external_user
        ).action_acknowledge_customer_message()

        self.assertTrue(self.request.customer_message_external_ack_at)
        self.assertFalse(self.request.customer_message_ack_at)
        self.assertFalse(self._refresh(self.external_user).has_unread_customer_message)
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)

    def test_ack_is_shared_within_an_audience(self):
        other_internal = create_internal_user(self.env)
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(
            self.internal_user
        ).action_acknowledge_customer_message()
        self.assertFalse(self._refresh(other_internal).has_unread_customer_message)

    def test_newer_message_re_raises_it_after_ack(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(
            self.internal_user
        ).action_acknowledge_customer_message()

        later = _post_tenant_message(self.request, self.mimer_user, body="Mer")
        later.date = self.request.customer_message_ack_at + timedelta(seconds=1)
        self.request.sudo().write({"last_customer_message_at": later.date})
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)

    def test_ack_with_nothing_unread_is_a_no_op(self):
        self.request.with_user(
            self.internal_user
        ).action_acknowledge_customer_message()
        self.assertFalse(self.request.customer_message_ack_at)

    def test_ack_is_written_to_the_audit_log(self):
        _post_tenant_message(self.request, self.mimer_user)
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_new_customer_info_indicator.py and
        # test_master_key_change_indicator.py do.
        request = self.request.with_context(creating_records=False)
        before = set(request.message_ids.ids)
        request.with_user(
            self.internal_user
        ).action_acknowledge_customer_message()
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it must
        # be explicitly invalidated to see the note just posted.
        request.invalidate_recordset(["message_ids"])
        bodies = " ".join(
            request.message_ids.filtered(
                lambda m: m.id not in before
            ).mapped("body")
        )
        self.assertIn("Meddelande från kund kvitterat", bodies)
