/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import ConfirmDialog from "./confirm_dialog";
import { askComponentQuestion } from "./component_question_dialog";
import { openComponentWizardDialog } from "./open_component_wizard_dialog";

/**
 * Records that answered "Ja" to the component question and are waiting for
 * their stage write to commit before the component wizard opens.
 * Module-level because the model hooks are reassigned per KanbanRecord
 * instance — per-instance state would be unsafe. Keyed by resId, value is
 * the target stage id (revalidated after save).
 *
 * Component question popup disabled — this Map is currently unused. Kept
 * commented for easy re-enabling alongside the component question.
 */
// const pendingComponentWizard = new Map();

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
    this.orm = useService("orm");
    this.actionService = useService("action");
    this.notificationService = useService("notification");
    this.uiService = useService("ui");

    const isMaintenanceRequest =
      this.props.record.model.config.resModel === "maintenance.request";

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

      if (targetStageName === "Utförd") {
        // user.hasGroup returns a Promise and MUST be awaited — the previous
        // unawaited call was always truthy, so the confirm fired for all
        // users, not just external contractors.
        const userIsExternalContractor = await user.hasGroup(
          "onecore_maintenance_extension.group_external_contractor"
        );

        // External contractors keep the plain irreversibility confirm —
        // component functionality is internal-only for now.
        if (userIsExternalContractor) {
          return await ConfirmDialog(
            this.dialogService,
            "Bekräfta ändring",
            "Är du säker på att du vill ändra statusen till Utförd? Om du gör detta kan du inte ändra tillbaka."
          );
        }

        // Component question popup disabled: internal users moving an
        // apartment ärende to Utförd no longer get the "Har du bytt ut eller
        // ändrat..." prompt, so the stage change just commits. The component
        // wizard is still reachable via the "Uppdatera/lägg till Komponent"
        // button on the ärende. To re-enable, uncomment the block below (and
        // the onRecordSaved wizard-opener further down).
        // // Internal users on apartment ärenden: ask the component question
        // if (record.data.space_caption === "Lägenhet" && record.resId) {
        //   const answer = await askComponentQuestion(this.dialogService);
        //   if (answer === "abort") {
        //     return false;
        //   }
        //   if (answer === "yes") {
        //     pendingComponentWizard.set(record.resId, changes.stage_id);
        //   }
        //   return true;
        // }
      }

      return true;
    };

    // Component question popup disabled (see onWillSaveRecord above), so this
    // wizard-opener is dead: pendingComponentWizard is never populated. Kept
    // commented for easy re-enabling alongside the component question.
    // // Opens the component wizard AFTER the stage write committed. NOTE:
    // // model hooks are single-slot — another patch assigning onRecordSaved
    // // would clobber this (nothing else in the repo does today).
    // this.props.record.model.hooks.onRecordSaved = async (record) => {
    //   if (!isMaintenanceRequest) {
    //     return;
    //   }
    //   const targetStageId = pendingComponentWizard.get(record.resId);
    //   if (targetStageId === undefined) {
    //     return;
    //   }
    //   // Consume before opening — guards against double-fire
    //   pendingComponentWizard.delete(record.resId);
    //   if (record.data.stage_id?.id === targetStageId) {
    //     await openComponentWizardDialog(
    //       this.orm,
    //       this.actionService,
    //       this.notificationService,
    //       record.resId,
    //       this.uiService
    //     );
    //   }
    // };
  },
});
