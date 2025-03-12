/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { useService } from "@web/core/utils/hooks";
import ConfirmDialog from "./confirm_dialog";

patch(StatusBarField.prototype, {
  setup() {
    super.setup();
    this.dialogService = useService("dialog");
    this.userIsExternalContractor =
      this.props.record.model.config.resModel === "maintenance.request" &&
      this.props.record.data.user_is_external_contractor;
  },

  getAllItems() {
    const { foldField, name, record } = this.props;
    const currentValue = record.data[name];

    if (this.field.type === "many2one") {
      // Many2one
      const currentStageName = record.data.stage_id[1];

      return this.specialData.data.map((option) => ({
        value: option.id,
        label: option.display_name,
        isFolded: option[foldField],
        isSelected: Boolean(currentValue && option.id === currentValue[0]),
        isDisabled:
          (currentStageName === "Väntar på handläggning" &&
            !record.data.user_id) ||
          (this.userIsExternalContractor &&
            (option.display_name === "Avslutad" ||
              currentStageName === "Avslutad" ||
              currentStageName === "Utförd")),
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

  async selectItem(item) {
    if (this.userIsExternalContractor && item.label === "Utförd") {
      const confirmed = await ConfirmDialog(
        this.dialogService,
        "Hej",
        "Om du gör detta kan du inte ändra tillbaka"
      );
      if (confirmed) {
        super.selectItem(item);
      }
    } else {
      super.selectItem(item);
    }
  },
});
