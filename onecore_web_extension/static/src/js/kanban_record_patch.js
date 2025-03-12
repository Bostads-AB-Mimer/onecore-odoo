/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import ConfirmDialog from "./confirm_dialog";

patch(KanbanRecord.prototype, {
  setup() {
    super.setup();
    this.dialogService = useService("dialog");

    const userIsExternalContractor =
      this.props.record.model.config.resModel === "maintenance.request" &&
      this.props.record.model.user.hasGroup(
        "onecore_maintenance_extension.group_external_contractor"
      );

    this.props.record.model.hooks.onWillSaveRecord = async (
      record,
      changes
    ) => {
      if (
        userIsExternalContractor &&
        changes.stage_id !== undefined &&
        record.data.stage_id[1] === "Utförd"
      ) {
        const confirmed = await ConfirmDialog(
          this.dialogService,
          "Hej",
          "Om du gör detta kan du inte ändra tillbaka"
        );

        return confirmed;
      } else {
        return true;
      }
    };
  },
});
