/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

patch(StatusBarField.prototype, {
  getAllItems() {
    const { foldField, name, record } = this.props;
    const currentValue = record.data[name];

    if (this.field.type === "many2one") {
      // Many2one
      const currentStageName = record.data.stage_id[1];
      const shouldDisable =
        record.model.config.resModel === "maintenance.request" &&
        record.data.user_is_external_contractor;

      return this.specialData.data.map((option) => ({
        value: option.id,
        label: option.display_name,
        isFolded: option[foldField],
        isSelected: Boolean(currentValue && option.id === currentValue[0]),
        isDisabled:
          shouldDisable &&
          (option.display_name === "Avslutad" ||
            currentStageName === "Avslutad" ||
            currentStageName === "Utförd"),
      }));
    } else {
      // Selection
      let { selection } = this.field;
      const { visibleSelection } = this.props;
      if (visibleSelection?.length) {
        selection = selection.filter(
          ([value]) =>
            value === currentValue || visibleSelection.includes(value)
        );
      }
      return selection.map(([value, label]) => ({
        value,
        label,
        isFolded: false,
        isSelected: value === currentValue,
      }));
    }
  },
});
