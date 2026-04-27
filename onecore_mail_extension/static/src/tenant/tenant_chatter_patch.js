/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Odoo's Chatter auto-saves the underlying record when Send message / Log note /
// Activity is clicked on an unsaved record. For maintenance.request this triggers
// the creation SMS to the tenant (HG = hyresgäst) before the user has confirmed —
// see MIM-1701. Gate these actions behind an explicit confirmation dialog.
patch(Chatter.prototype, {
  setup() {
    super.setup();
    this.dialogService = this.env.services.dialog;
  },

  _isUnsavedMaintenanceRequest() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      !this.state.thread.id
    );
  },

  _confirmSaveBeforeChatterAction() {
    return new Promise((resolve) => {
      this.dialogService.add(ConfirmationDialog, {
        title: _t("Spara ärendet först"),
        body: _t(
          "Ärendet är inte sparat ännu. Om du fortsätter skapas ärendet och ett SMS kan skickas till hyresgästen om att vi mottagit ärendet. Vill du spara ärendet nu?",
        ),
        confirm: () => resolve(true),
        cancel: () => resolve(false),
        confirmLabel: _t("Spara ärendet"),
        cancelLabel: _t("Avbryt"),
      });
    });
  },

  async toggleComposer(mode = false, options = {}) {
    if (mode && this._isUnsavedMaintenanceRequest()) {
      const confirmed = await this._confirmSaveBeforeChatterAction();
      if (!confirmed) {
        return;
      }
    }
    return super.toggleComposer(mode, options);
  },

  async scheduleActivity() {
    if (this._isUnsavedMaintenanceRequest()) {
      const confirmed = await this._confirmSaveBeforeChatterAction();
      if (!confirmed) {
        return;
      }
    }
    return super.scheduleActivity();
  },
});
