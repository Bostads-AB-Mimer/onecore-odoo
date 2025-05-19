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

    return super.beforeUnload(...arguments);
  },

  /**
   * Override to check for unsaved changes before leaving
   * @override
   */
  canLeave() {
    if (this.model.root.resModel === "maintenance.request") {
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
    }
    return super.beforeLeave(...arguments);
  },

  /**
   * Override to prevent auto-save for maintenance requests when clicking buttons
   * @override
   */
  async beforeExecuteActionButton(actionData) {
    // For maintenance requests, don't save automatically when clicking specific buttons
    if (this.model.root.resModel === "maintenance.request") {
      // Skip save but preserve form changes
      const orm = this.env.services.orm;
      const result = await orm.call(
        this.model.root.resModel,
        actionData.name,
        [[this.model.root.resId]],
        { ...actionData.context }
      );

      if (result && result.type) {
        if (result.type === "ir.actions.act_url") {
          window.open(result.url, result.target || "_self");
        } else {
          this.env.services.action.doAction(result);
        }
      }

      return false;
    }

    return super.beforeExecuteActionButton(...arguments);
  },

  /**
   * Override to intercept the 'create' button (new record) action
   * @override
   */
  async create() {
    // For maintenance requests with unsaved changes, show confirmation dialog
    if (
      this.model.root.resModel === "maintenance.request" &&
      this.model.root.dirty
    ) {
      const dialogService = this.env.services.dialog;

      const confirmed = await new Promise((resolve) => {
        dialogService.add(ConfirmationDialog, {
          title: _t("Warning"),
          body: _t(
            "Du har osparade ändringar. Är du säker på att du vill skapa ett nytt ärende utan att spara?"
          ),
          confirm: () => resolve(true),
          cancel: () => resolve(false),
          confirmLabel: _t("Skapa nytt utan att spara"),
          cancelLabel: _t("Avbryt"),
        });
      });

      if (!confirmed) {
        return;
      }

      await this.model.root.discard();
    }

    return super.create(...arguments);
  },
});
