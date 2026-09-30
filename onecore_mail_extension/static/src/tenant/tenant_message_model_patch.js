/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

// MIM-2040 (extra). A Mina sidor message is posted through work-order's
// integration account, so its author is that account ("Odoo") rather than the
// tenant. Keyed on the type, not the author: the integration account differs
// between setups. Patched on the model so every place that prints authorName
// (chatter, previews, notifications) agrees.
patch(Message.prototype, {
    get isFromTenant() {
        return this.message_type === "from_tenant";
    },
    // The badge is shown only when a real name is printed; without one the
    // author already reads "Hyresgäst".
    get showsTenantBadge() {
        return this.isFromTenant && Boolean(this.onecore_from_tenant_name);
    },
    get authorName() {
        if (this.isFromTenant) {
            // Messages written before this change carry no name.
            return this.onecore_from_tenant_name || "Hyresgäst";
        }
        return super.authorName;
    },
});
