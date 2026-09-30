from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tools.discuss import Store


@tagged("onecore", "post_install", "-at_install")
class TestFromTenantSender(TransactionCase):
    """MIM-2040 (extra): who wrote a Mina sidor message, as Odoo users see it.

    Mina sidor messages reach Odoo through work-order's XML-RPC login, so their
    author_id is that integration account. Which account that is depends on the
    setup, so nothing here may assume odoo@mimer.nu — every test posts as an
    integration user with an invented login.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category_id = cls.env.ref("onecore_maintenance_extension.category_1").id
        cls.integration_groups = [
            cls.env.ref("base.group_user").id,
            # Base maintenance rules limit a plain internal user to requests
            # they own or follow; the real integration account is a manager.
            cls.env.ref("maintenance.group_equipment_manager").id,
        ]
        cls.integration_user = cls._integration_user("rpc_integration_a")
        cls.tenant = cls.env["maintenance.tenant"].create(
            {
                "name": "Anna Andersson",
                "contact_code": "P900001",
                "contact_key": "_TESTKEY01",
            }
        )
        cls.request = cls.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "tenant_id": cls.tenant.id,
            }
        )

    @classmethod
    def _integration_user(cls, login):
        return cls.env["res.users"].create(
            {
                "name": f"Integration {login}",
                "login": login,
                "group_ids": [(6, 0, cls.integration_groups)],
            }
        )

    def _post_as_mina_sidor(self, user, record=None):
        """Post the way work-order's addMessageToWorkOrder does over XML-RPC."""
        record = self.request if record is None else record
        return record.with_user(user).message_post(
            body="Kranen droppar fortfarande.",
            message_type="from_tenant",
            body_is_html=True,
        )

    def test_from_tenant_names_the_request_tenant(self):
        message = self._post_as_mina_sidor(self.integration_user)
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_does_not_depend_on_the_integration_login(self):
        other = self._integration_user("some_other_setup_integration")
        message = self._post_as_mina_sidor(other)
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_superuser_post_is_labelled_the_same_way(self):
        # A setup could post as the superuser; the raw test env is user_root.
        message = self.request.message_post(
            body="Hej", message_type="from_tenant", body_is_html=True
        )
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_author_id_is_left_alone(self):
        # work-order's messageAuthor reads author_id[1] on from_tenant, so the
        # author must stay the posting partner.
        message = self._post_as_mina_sidor(self.integration_user)
        self.assertEqual(message.author_id, self.integration_user.partner_id)

    def test_name_survives_tenant_change(self):
        message = self._post_as_mina_sidor(self.integration_user)
        self.request.tenant_id = self.env["maintenance.tenant"].create(
            {
                "name": "Bertil Bengtsson",
                "contact_code": "P900002",
                "contact_key": "_TESTKEY02",
            }
        )
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")
        self.request.tenant_id = False
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_request_without_tenant_stores_nothing(self):
        vacant = self.env["maintenance.request"].create(
            {
                "name": "Ledig lägenhet",
                "maintenance_request_category_id": self.request.maintenance_request_category_id.id,
                "space_caption": "Lägenhet",
            }
        )
        message = self._post_as_mina_sidor(self.integration_user, vacant)
        self.assertFalse(message.onecore_from_tenant_name)

    def test_only_from_tenant_messages_get_a_name(self):
        note = self.request.with_user(self.integration_user).message_post(
            body="Intern notering",
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.assertFalse(note.onecore_from_tenant_name)

    def test_other_model_does_not_borrow_a_request_tenant(self):
        # Same res_id as the request, different model: must not pick up
        # Anna Andersson from an unrelated maintenance.request. reply_to is
        # given so base mail does not browse a res.partner with that id, which
        # need not exist.
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.request.id,
                "body": "Hej",
                "message_type": "from_tenant",
                "reply_to": "noreply@example.com",
            }
        )
        self.assertFalse(message.onecore_from_tenant_name)

    def test_name_reaches_the_chatter_store(self):
        # Store.Target() rather than None: see
        # test_log_category.test_category_is_serialized_to_the_store.
        self.assertIn(
            "onecore_from_tenant_name",
            self.env["mail.message"]._to_store_defaults(Store.Target()),
        )
