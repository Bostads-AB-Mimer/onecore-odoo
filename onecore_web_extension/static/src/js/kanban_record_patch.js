/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import ConfirmDialog from "./confirm_dialog";

/**
 * Shows a dialog asking if the loan product has been returned.
 * @param {Object} dialogService - The dialog service
 * @param {string} productDetails - Details about the loan product
 * @returns {Promise<boolean>} - true if user confirms, false otherwise
 */
const showLoanProductDialog = (dialogService, productDetails) => {
  return new Promise((resolve) => {
    const bodyMessage = productDetails
      ? `Det finns en låneprodukt (${productDetails}) i ärendet. Har kunden lämnat tillbaka låneprodukten?`
      : "Det finns en låneprodukt i ärendet. Har kunden lämnat tillbaka låneprodukten?";

    dialogService.add(ConfirmationDialog, {
      title: _t("Låneprodukt ej återlämnad"),
      body: _t(bodyMessage),
      confirm: () => resolve(true),
      cancel: () => resolve(false),
      confirmLabel: _t("Återlämna och avsluta"),
      cancelLabel: _t("Ångra"),
    });
  });
};

/**
 * Gets the stage name for a given stage ID by looking up the groups.
 * @param {Object} record - The kanban record
 * @param {number} stageId - The stage ID to look up
 * @returns {string|null} - The stage name or null if not found
 */
const getStageName = (record, stageId) => {
  const groups = record.model.root.groups;
  if (!groups) return null;
  const targetGroup = groups.find((g) => g.value === stageId);
  return targetGroup?.displayName || null;
};

patch(KanbanRecord.prototype, {
  setup() {
    super.setup();
    this.dialogService = useService("dialog");

    const isMaintenanceRequest =
      this.props.record.model.config.resModel === "maintenance.request";

    const userIsExternalContractor =
      isMaintenanceRequest &&
      this.props.record.model.user.hasGroup(
        "onecore_maintenance_extension.group_external_contractor"
      );

    this.props.record.model.hooks.onWillSaveRecord = async (
      record,
      changes
    ) => {
      // Only apply validation for maintenance requests with stage changes
      if (!isMaintenanceRequest || changes.stage_id === undefined) {
        return true;
      }

      const targetStageName = getStageName(record, changes.stage_id);

      // Check for loan product when moving to "Avslutad"
      if (targetStageName === "Avslutad" && record.data.has_loan_product) {
        const confirmed = await showLoanProductDialog(
          this.dialogService,
          record.data.loan_product_details || ""
        );

        if (confirmed) {
          // User confirmed - mark loan product as returned
          changes.has_loan_product = false;
          return true;
        }
        // User cancelled - abort the stage change
        return false;
      }

      // Existing external contractor validation for "Utförd" stage
      if (
        userIsExternalContractor &&
        record.data.stage_id[1] === "Utförd"
      ) {
        const confirmed = await ConfirmDialog(
          this.dialogService,
          "Bekräfta ändring",
          "Är du säker på att du vill ändra statusen till Utförd? Om du gör detta kan du inte ändra tillbaka."
        );

        return confirmed;
      }

      return true;
    };
  },
});
