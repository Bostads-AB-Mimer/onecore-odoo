from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("onecore")
class TestComponentButtonHidden(TransactionCase):
    def test_component_wizard_button_is_not_in_the_request_form(self):
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_form_extension"
        )
        self.assertNotIn('name="open_component_wizard"', view.arch_db)
