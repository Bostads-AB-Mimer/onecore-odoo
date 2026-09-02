/** @odoo-module **/

import { Thread } from "@mail/core/common/thread_model";
import { Thread as ThreadComponent } from "@mail/core/common/thread";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// MIM-1956 — the händelselogg filter. `thread.onecoreLogCategory` is set by the
// pill row in the chatter (see tenant_chatter_patch.js) and is undefined
// everywhere else, so every patch below delegates straight to super() when it
// is unset. Discuss and all other chatters therefore take untouched code paths.

// --- Gate 1: fetching -------------------------------------------------------
// Routing the fetch through our own route is what makes "Load More" respect the
// filter: both hooks feed fetchMessagesData, which every fetch path uses
// (initial load, fetchMoreMessages, fetchNewMessages). So paging fetches 30
// more OF THAT CATEGORY rather than 30 messages that are then thinned out.
patch(Thread.prototype, {
  get fetchRouteChatter() {
    if (!this.onecoreLogCategory) {
      return super.fetchRouteChatter;
    }
    return "/onecore/mail/thread/messages";
  },

  getFetchParams() {
    const params = super.getFetchParams();
    if (this.onecoreLogCategory) {
      params.onecore_log_category = this.onecoreLogCategory;
    }
    return params;
  },
});

// --- Gate 2: rendering ------------------------------------------------------
// Thread.post ends at addOrReplaceMessage, which pushes a newly posted message
// straight into thread.messages without consulting any domain; bus-delivered
// messages do the same. So logging an intern notering while Kommunikation is
// active would make it pop into a list it does not belong in. The predicate
// below is the second gate. It compares the category serialized onto each
// message by mail.message._to_store_defaults, so the classification rules stay
// in Python only.
patch(ThreadComponent.prototype, {
  get orderedMessages() {
    const messages = super.orderedMessages;
    const category = this.props.thread?.onecoreLogCategory;
    if (!category) {
      return messages;
    }
    return messages.filter((msg) => msg.onecore_log_category === category);
  },

  // Base decides between the message list and the empty state on
  // props.thread.isEmpty, which reads thread.messages — NOT the filtered list.
  // Without this, the leak above yields thread.messages.length === 1, isEmpty
  // false, the content block rendered, the message filtered out by
  // orderedMessages, and an empty area with no empty-state text at all.
  //
  // This is AND-ed onto base's own condition by tenant_thread.xml, so it only
  // ever narrows: returning true outside ärende leaves base untouched, and no
  // copy of base's expression lives here to go stale.
  get onecoreShowContent() {
    const thread = this.props.thread;
    if (!thread?.onecoreLogCategory) {
      return true;
    }
    // loadOlder is deliberately dropped here: the server filters by category,
    // so an empty page means there are no older messages of this category and
    // loadOlder is already false.
    return this.orderedMessages.length > 0 || thread.hasLoadingFailed;
  },

  get onecoreEmptyText() {
    switch (this.props.thread?.onecoreLogCategory) {
      case "event":
        return _t("Inga händelser att visa.");
      case "internal_note":
        return _t("Inga interna noteringar att visa.");
      case "communication":
        return _t("Ingen kommunikation att visa.");
      default:
        return _t("Inga meddelanden av den här typen.");
    }
  },
});
