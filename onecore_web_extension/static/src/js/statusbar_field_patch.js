/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { useService } from "@web/core/utils/hooks";
import ConfirmDialog from "./confirm_dialog";
import { askComponentQuestion } from "./component_question_dialog";
import { openComponentWizardDialog } from "./open_component_wizard_dialog";

patch(StatusBarField.prototype, {
  setup() {
    super.setup();
    this.dialogService = useService("dialog");
    this.orm = useService("orm");
    this.actionService = useService("action");
    this.notificationService = useService("notification");
    this.uiService = useService("ui");
    this.userIsExternalContractor =
      this.props.record.model.config.resModel === "maintenance.request" &&
      this.props.record.data.user_is_external_contractor;
  },

  getAllItems() {
    const { foldField, name, record } = this.props;
    const currentValue = record.data[name];

    if (this.field.type === "many2one") {
      // Many2one
      const currentStageName = record.data.stage_id.display_name;

      return this.specialData.data.map((option) => ({
        value: option.id,
        label: option.display_name,
        isFolded: option[foldField],
        isSelected: Boolean(currentValue && option.id === currentValue.id),
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
    const record = this.props.record;
    const isMaintenanceRequest =
      record.model.config.resModel === "maintenance.request";
    const goingToUtford =
      isMaintenanceRequest && item.label === "Utförd" && !item.isSelected;

    if (!goingToUtford) {
      return super.selectItem(item);
    }

    // External contractors keep the plain irreversibility confirm —
    // component functionality is internal-only for now.
    if (this.userIsExternalContractor) {
      const confirmed = await ConfirmDialog(
        this.dialogService,
        "Bekräfta ändring",
        "Är du säker på att du vill ändra statusen till Utförd? Om du gör detta kan du inte ändra tillbaka."
      );
      if (!confirmed) {
        return;
      }
      return super.selectItem(item);
    }

    // Component question popup disabled: internal users moving an apartment
    // ärende to Utförd no longer get the "Har du bytt ut eller ändrat..."
    // prompt. The component wizard is still reachable via the
    // "Uppdatera/lägg till Komponent" button on the ärende. To re-enable the
    // popup, uncomment the two blocks below.
    // // Internal users on apartment ärenden: ask the component question
    // const isApartment =
    //   record.data.space_caption === "Lägenhet" && !!record.resId;
    // let answer = null;
    //
    // if (isApartment) {
    //   answer = await askComponentQuestion(this.dialogService);
    //   if (answer === "abort") {
    //     return;
    //   }
    // }

    // Odoo 19's selectItem awaits record.update() + record.save(); awaiting
    // here guarantees the stage write committed before the wizard opens.
    await super.selectItem(item);

    // if (
    //   answer === "yes" &&
    //   record.resId &&
    //   !record.dirty &&
    //   record.data.stage_id?.id === item.value
    // ) {
    //   await openComponentWizardDialog(
    //     this.orm,
    //     this.actionService,
    //     this.notificationService,
    //     record.resId,
    //     this.uiService
    //   );
    // }
  },
});
