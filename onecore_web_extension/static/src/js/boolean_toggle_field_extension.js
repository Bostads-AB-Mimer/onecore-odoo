/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BooleanToggleField } from "@web/views/fields/boolean_toggle/boolean_toggle_field";

patch(BooleanToggleField.prototype, {
  /**
   * Override the onChange method to add your custom logic
   *
   * @override
   */
  async onChange(newValue) {
    const record = this.props.record;
    const fieldName = this.props.name;

    if (
      record &&
      record.model &&
      record.model.root.resModel === "maintenance.request"
    ) {

      // Just update the field value without saving
      this.state.value = newValue;
      await record.update({ [fieldName]: newValue }, { save: false });
      return;
    }
    return super.onChange(...arguments);
  },
});
