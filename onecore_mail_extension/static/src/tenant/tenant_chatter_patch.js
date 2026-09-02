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
    // MIM-1956 — guards the pill row against a second click landing while a
    // filter-triggered fetch is already in flight (see onClickLogFilter).
    this.state.onecoreLogFilterBusy = false;
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

  // Every record opens on "Alla" (MIM-1956). The Thread record is a store
  // singleton that outlives this component, so a stale category would
  // otherwise survive navigation between ärenden.
  //
  // changeThread — not load — is the hook for that reset. Base calls load()
  // after EVERY post and after the full composer closes as well
  // (mail/static/src/chatter/web_portal/chatter.js: onPostCallback,
  // onCloseFullComposerCallback), so resetting in load() threw the user's
  // filter away mid-session: logging an intern notering under Kommunikation
  // snapped the pills back to "Alla" while the log still held only the
  // previous category's page. changeThread runs exactly on chatter mount and
  // on a record switch, which is what "opens on Alla" means.
  changeThread(threadModel, threadId) {
    super.changeThread(threadModel, threadId);
    const thread = this.state.thread;
    if (thread?.onecoreLogCategory) {
      // Drop the filtered window together with the filter. Without it the
      // reopened log renders the previous category's page under an active
      // "Alla" pill. No refetch here — base load() runs right after
      // changeThread and does it.
      this._onecoreSetLogCategory(thread, undefined);
    }
  },

  // The one place that switches händelselogg category (MIM-1956). Setting the
  // category alone is not enough: the loaded window belongs to the OLD
  // category, so fetchNewMessages would ask for messages after an id from it.
  // Three callers — onClickLogFilter, changeThread and onClickSearch — so this
  // lives in one method rather than three copies of the same five lines.
  // Deliberately does NOT fetch: changeThread must not, since base load()
  // follows immediately.
  _onecoreSetLogCategory(thread, categoryId) {
    thread.onecoreLogCategory = categoryId;
    thread.messages = [];
    thread.isLoaded = false;
    thread.loadOlder = false;
    thread.loadNewer = false;
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

  // MIM-1956 — händelselogg filter. Single-select, reset to "Alla" on every
  // record open: the filter is component state only, deliberately not
  // persisted, so nobody comes back tomorrow to a log that looks truncated.
  get onecoreLogFilters() {
    return [
      { id: undefined, label: _t("Alla") },
      { id: "event", label: _t("Händelser") },
      { id: "internal_note", label: _t("Interna noteringar") },
      { id: "communication", label: _t("Kommunikation") },
    ];
  },

  showLogFilter() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      !!this.state.thread?.id &&
      !this.state.isSearchOpen
    );
  },

  isActiveLogFilter(categoryId) {
    return (this.state.thread?.onecoreLogCategory ?? undefined) === categoryId;
  },

  async onClickLogFilter(categoryId) {
    const thread = this.state.thread;
    if (
      !thread ||
      this.isActiveLogFilter(categoryId) ||
      this.state.onecoreLogFilterBusy
    ) {
      return;
    }
    // Busy-guard against rapid pill-switching (MIM-1956 review): base
    // fetchNewMessages silently no-ops while thread.status === "loading", so
    // a second click landing mid-fetch would set onecoreLogCategory to the
    // new pill without ever sending its RPC — leaving the active pill and
    // thread.messages out of sync. Disabling the row for the duration of the
    // fetch (see the template's t-att-disabled) makes that click impossible
    // rather than racing it.
    this.state.onecoreLogFilterBusy = true;
    try {
      this._onecoreSetLogCategory(thread, categoryId);
      await thread.fetchNewMessages();
    } finally {
      this.state.onecoreLogFilterBusy = false;
    }
  },

  // Opening search clears the filter (MIM-1956). Search is NOT composed with
  // the pills: store.searchMessagesInThread builds its RPC from
  // thread.getFetchRoute() + thread.getFetchParams() (core/common/
  // store_service.js), both of which our Thread patches hook, so an active
  // category would silently scope the search to it — while showLogFilter()
  // hides the pills, leaving the user no way to see why their term is not
  // found. Composing the two is a deliberate follow-up, not this ticket.
  // Consequence: closing search returns the pills to "Alla".
  async onClickSearch() {
    super.onClickSearch();
    const thread = this.state.thread;
    if (this.state.isSearchOpen && thread?.onecoreLogCategory) {
      this._onecoreSetLogCategory(thread, undefined);
      await thread.fetchNewMessages();
    }
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
    if (data.has_unread_customer_message) {
      signals.push({
        name: _t("Meddelande från kund"),
        buttonLabel: _t("Markera meddelande från kund som läst"),
        method: "action_acknowledge_customer_message",
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
