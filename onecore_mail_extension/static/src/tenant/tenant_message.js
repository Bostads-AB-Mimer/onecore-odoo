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
    };
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
