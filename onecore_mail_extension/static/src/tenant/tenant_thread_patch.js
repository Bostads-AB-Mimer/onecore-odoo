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
// active would make it pop into a list it does not belong in. The two patches
// below are the second gate. They compare the category serialized onto each
// message by mail.message._to_store_defaults, so the classification rules stay
// in Python only.

// Base decides between the message list and the empty state on
// thread.isEmpty (mail/static/src/core/common/thread.xml, the name="content"
// t-if), and base's isEmpty reads thread.messages — NOT the filtered list.
// Without this, a leaked message yields thread.messages.length === 1, isEmpty
// false, the content block rendered, the message dropped again by
// orderedMessages below, and an empty log area with no empty-state text at
// all.
//
// Narrowing isEmpty here rather than overriding base's t-if is deliberate:
// base's condition then keeps working untouched for every thread in the app,
// and no stale copy of it lives in our templates. Patching isEmpty on the
// Thread model is base-sanctioned — see
// mail/static/src/discuss/core/public_web/thread_model_patch.js, which
// narrows it the same way with super.isEmpty.
patch(Thread.prototype, {
  get isEmpty() {
    const category = this.onecoreLogCategory;
    if (!category) {
      return super.isEmpty;
    }
    return !this.messages.some((m) => m.onecore_log_category === category);
  },
});

patch(ThreadComponent.prototype, {
  get orderedMessages() {
    const messages = super.orderedMessages;
    const category = this.props.thread?.onecoreLogCategory;
    if (!category) {
      return messages;
    }
    return messages.filter((msg) => msg.onecore_log_category === category);
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
