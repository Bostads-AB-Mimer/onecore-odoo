/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Message } from "@mail/core/common/message";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

patch(Chatter, {
  components: { ...Chatter.components, Message },
});

// Odoo's Chatter auto-saves the underlying record when Send message / Log note /
// Activity is clicked on an unsaved record. For maintenance.request this triggers
// the creation SMS to the tenant (HG = hyresgäst) before the user has confirmed —
// see MIM-1701. Gate these actions behind an explicit confirmation dialog.
patch(Chatter.prototype, {
  setup() {
    super.setup();
    this.dialogService = this.env.services.dialog;
  },

  get pinnedMessages() {
    const thread = this.state.thread;
    if (!thread?.allMessages) {
      return [];
    }
    // Read allMessages (the full store-backed set), not the paginated
    // thread.messages: the chatter only loads the 30 most recent messages, so a
    // message pinned before that window is absent from thread.messages until
    // scrolled into view. _fetchPinnedMessages loads every pinned message into
    // the store so it is present in allMessages here (MIM-1301 review).
    // Newest first (descending id), matching the log's order="desc" display.
    return thread.allMessages
      .filter((m) => m.pinned_at)
      .sort((a, b) => b.id - a.id);
  },

  async load(thread, requestList) {
    await super.load(thread, requestList);
    await this._fetchPinnedMessages(thread);
  },

  async _fetchPinnedMessages(thread) {
    // Loads all pinned messages for the thread into the store, independent of
    // the chatter's 30-message pagination, so pinnedMessages (reading
    // allMessages) always renders the complete "Fästa" section on first paint.
    // Mirrors the current-thread guard in the base Chatter.load.
    if (!thread?.id || !this.state.thread?.eq(thread)) {
      return;
    }
    const result = await rpc("/mail/thread/pinned_messages", {
      thread_model: thread.model,
      thread_id: thread.id,
    });
    this.store.insert(result.data);
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
