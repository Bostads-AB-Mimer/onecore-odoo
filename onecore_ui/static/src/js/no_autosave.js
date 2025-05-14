/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(FormController.prototype, {
  /**
   * Override to prevent autosave specifically for maintenance requests
   * when leaving the form
   * @override
   */
  beforeUnload() {
    // For maintenance requests, show native browser warning if there are changes
    if (
      this.model.root.resModel === "maintenance.request" &&
      this.model.root.dirty
    ) {
      return _t("You have unsaved changes. Are you sure you want to leave?");
    }
    // Normal behavior for other models
    return super.beforeUnload(...arguments);
  },

  /**
   * Override to check for unsaved changes before leaving
   * @override
   */
  canLeave() {
    if (this.model.root.resModel === "maintenance.request") {
      // We'll handle the warning in beforeLeave
      return true;
    }
    return super.canLeave(...arguments);
  },

  /**
   * Override to show warning dialog for maintenance requests when navigating away
   * @override
   */
  async beforeLeave() {
    if (
      this.model.root.resModel === "maintenance.request" &&
      this.model.root.dirty
    ) {
      try {
        // Show confirmation dialog for unsaved changes
        const dialogService = this.env.services.dialog;
        if (dialogService) {
          return new Promise((resolve) => {
            dialogService.add(ConfirmationDialog, {
              title: _t("Warning"),
              body: _t(
                "Du har osparade ändringar. Är du säker på att du vill lämna sidan utan att spara?"
              ),
              confirm: () => resolve(true),
              cancel: () => resolve(false),
              confirmLabel: _t("Lämna sidan utan att spara"),
              cancelLabel: _t("Avbryt"),
            });
          });
        }
      } catch (error) {
        console.error("Error showing dialog:", error);
      }
    }
    // No changes or not a maintenance request, proceed normally
    return super.beforeLeave(...arguments);
  },
});
