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

  // Unread acknowledge signals for the current viewer, in display order.
  // supplier/internal dialog collapse into one "Meddelande" signal (only one
  // is ever set for a given viewer). Labels/names are Swedish.
  _unreadAckSignals() {
    const data = this.props.record?.data ?? {};
    const signals = [];
    if (data.has_unread_supplier_dialog || data.has_unread_internal_dialog) {
      signals.push({
        name: _t("Meddelande"),
        buttonLabel: _t("Markera meddelande som läst"),
        method: "action_acknowledge_dialog",
      });
    }
    if (data.has_unread_master_key_change) {
      signals.push({
        name: _t("Huvudnyckeländring"),
        buttonLabel: _t("Markera huvudnyckeländring som läst"),
        method: "action_acknowledge_master_key_change",
      });
    }
    if (data.has_unread_new_customer_info) {
      signals.push({
        name: _t("Ny kundinfo"),
        buttonLabel: _t("Markera ny kundinfo som läst"),
        method: "action_acknowledge_new_customer_info",
      });
    }
    return signals;
  },

  showAckButton() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      this._unreadAckSignals().length > 0
    );
  },

  ackButtonLabel() {
    const signals = this._unreadAckSignals();
    return signals.length === 1 ? signals[0].buttonLabel : _t("Markera som läst");
  },

  async _acknowledgeSignals(signals) {
    const record = this.props.record;
    await Promise.all(
      signals.map((s) =>
        this.env.services.orm.call("maintenance.request", s.method, [
          [record.resId],
        ]),
      ),
    );
    // Reload so has_unread_* refresh -> the button relabels/hides.
    await record.load();
    // Re-fetch messages so is_dialog_unread_for_side re-serializes and the
    // orange highlight clears (acknowledging only changes computed flags on
    // existing messages, so fetchNewMessages() would not refresh them).
    await this.state?.thread?.fetchMessages();
  },

  async onClickAcknowledge() {
    const record = this.props.record;
    if (!record?.resId) {
      return;
    }
    const signals = this._unreadAckSignals();
    if (signals.length === 0) {
      return;
    }
    if (signals.length === 1) {
      await this._acknowledgeSignals(signals);
      return;
    }
    // Two or more unread signals: confirm acknowledging all of them.
    const names = signals.map((s) => s.name).join(", ");
    this.dialogService.add(ConfirmationDialog, {
      title: _t("Markera som läst"),
      body: _t("Vill du markera följande som läst?") + " " + names,
      confirmLabel: _t("Markera som läst"),
      cancelLabel: _t("Avbryt"),
      confirm: () => this._acknowledgeSignals(signals),
      // ConfirmationDialog renders the cancel button on t-if="props.cancel",
      // not on cancelLabel — without a callback there is no Avbryt at all and
      // the only way out is the X / Escape.
      cancel: () => {},
    });
  },
});
