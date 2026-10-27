from odoo import models


class Base(models.AbstractModel):
    """Allow a ``required`` flag on property definitions.

    Odoo's Properties have no notion of a mandatory answer. These two hooks are
    the supported way to extend the definition schema; the ticket enforces the
    flag server side and ``static/src`` teaches the editor and the widget about
    it. The hooks are global to every Properties field, which is harmless: the
    key is only ever set from the helpdesk form editor.
    """

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
