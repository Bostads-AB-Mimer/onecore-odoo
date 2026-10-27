from odoo import models


class Base(models.AbstractModel):
    """Mimer extension of the Properties definition schema: ``required``
    (bool) on a question means it must be answered before the ticket is
    saved. Enforced by helpdesk.ticket and the patched widget. Odoo strips
    unknown keys from definitions, so the key is declared here through the
    hooks Odoo provides for that purpose."""

    _inherit = "base"

    def _additional_allowed_keys_properties_definition(self):
        return super()._additional_allowed_keys_properties_definition() + ("required",)

    def _validate_properties_definition(self, properties_definition, field):
        super()._validate_properties_definition(properties_definition, field)
        for prop in properties_definition:
            if "required" in prop and not isinstance(prop["required"], bool):
                raise ValueError(
                    f"Property {prop.get('name')!r}: 'required' must be a boolean."
                )
