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

  async onClickAcknowledgeDialog() {
    const record = this.props.record;
    if (!record?.resId) {
      return;
    }
    // The button is shared by two independent unread signals: the
    // bidirectional supplier/internal dialog and the one-directional
    // master-key change shared by all viewers. One click clears both.
    // The dialog RPC is a no-op when no log-note dialog is unread for the
    // caller's side, so calling both unconditionally is safe.
    await Promise.all([
      this.env.services.orm.call(
        "maintenance.request",
        "action_acknowledge_dialog",
        [[record.resId]],
      ),
      this.env.services.orm.call(
        "maintenance.request",
        "action_acknowledge_master_key_change",
        [[record.resId]],
      ),
    ]);
    // Reload the form record so has_unread_* refreshes -> the button hides.
    await record.load();
    // Re-fetch the chatter messages so is_dialog_unread_for_side is
    // re-serialized and the orange background clears. Acknowledging only
    // changes a computed flag on existing messages, so fetchNewMessages()
    // (which pulls messages newer than the latest) would not refresh them.
    await this.state?.thread?.fetchMessages();
  },
});
