/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";

/**
 * Patch DateTimeField so that options="{'show_time': false}" also hides
 * the time picker in the popup (not just in the display formatting).
 *
 * The base implementation only uses showTime for formatting the input value.
 * The picker popup always shows the time section when field.type === "datetime".
 * By overriding the `field` getter to report type "date" when showTime is false,
 * the picker treats it as a date-only field: no time section, auto-close on select.
 */
patch(DateTimeField.prototype, {
  get field() {
    const field = super.field;
    if (this.props.showTime === false) {
      return { ...field, type: "date" };
    }
    return field;
  },
});
