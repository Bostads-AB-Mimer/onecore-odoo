/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Message } from "@mail/core/common/message";
import { browser } from "@web/core/browser/browser";
import { useRef, useExternalListener, onMounted } from "@odoo/owl";

patch(Message.prototype, {
  setup() {
    super.setup();
    this.messageRef = useRef("messageRef");
    this.isCollapsible = true;
    this.isCollapsed = true;

    useExternalListener(browser, "resize", this.setIsCollapsible);

    onMounted(() => {
      this.setIsCollapsible();
      this.isCollapsed = this.isCollapsible;
    });
  },
  setIsCollapsible() {
    this.isCollapsible = this.messageRef.el.clientHeight > 100;
  },
  toggleIsCollapsed() {
    this.isCollapsed = !this.isCollapsed;
  },
  get attClass() {
    return {
      ...super.attClass,
      collapsed: this.isCollapsed,
      "mimer-dialog-unread": this.message.is_dialog_unread_for_side,
      "mimer-pinned": Boolean(this.message.pinned_at),
    };
  },
  get canPin() {
    return this.message.can_pin;
  },
  async togglePin() {
    const result = await this.env.services.orm.call(
      "mail.message",
      "action_toggle_pin",
      [[this.message.id]],
    );
    // Update the store record directly from the returned pin state. This
    // reactively updates the inline styling and the Chatter's pinnedMessages
    // getter. thread.fetchMessages() alone would not refresh a message pinned
    // before the chatter's 30-message window, so unpinning such a message from
    // the "Fästa" section would leave it stuck there until reload (MIM-1301).
    this.message.store["mail.message"].insert({
      id: this.message.id,
      pinned_at: result.pinned_at,
      pinned_by_name: result.pinned_by_name,
    });
  },
  isSendFailure() {
    const type = this.message.message_type;
    return type && type.startsWith("failed_tenant");
  },
  getSentAsString() {
    switch (this.message.message_type) {
      case "tenant_sms":
      case "tenant_mail_failed_and_sms_ok":
        return " (via sms)";
      case "tenant_mail":
      case "tenant_mail_ok_and_sms_failed":
        return " (via mejl)";
      case "tenant_mail_and_sms":
        return " (via sms och mejl)";
      case "failed_tenant_sms":
        return " (sms misslyckades)";
      case "failed_tenant_mail":
        return " (mejl misslyckades)";
      case "failed_tenant_mail_and_sms":
        return " (sms och mejl misslyckades)";
      default:
        return "";
    }
  },
});
