/* @odoo-module */

import { CheckBox } from "@web/core/checkbox/checkbox";
import { Composer } from "@mail/core/common/composer";
import { patch } from "@web/core/utils/patch";
import { useState, onMounted } from "@odoo/owl";

patch(Composer, {
  components: { ...Composer.components, CheckBox },
});

patch(Composer.prototype, {
  setup() {
    super.setup();
    this.state = useState({
      sendSMS: false,
      sendEmail: false,
      tenantHasEmail: false,
      tenantHasPhoneNumber: false,
    });
    this.state.active = true;

    onMounted(async () => {
      const tenantResult = await this.threadService.getTenantContacts(
        this.thread.id
      );
      this.state.tenantHasEmail = tenantResult.has_email;
      this.state.tenantHasPhoneNumber = tenantResult.has_phone_number;
    });
  },
  onSMSCheckboxChange(checked) {
    this.state.sendSMS = checked;
  },
  onEMailCheckboxChange(checked) {
    this.state.sendEmail = checked;
  },

  get placeholder() {
    if (this.props.type === "message") {
      return "Skriv ett meddelande till hyresgäst";
    }
    return super.placeholder;
  },
  get isSendButtonDisabled() {
    if (
      this.props.type === "message" &&
      !this.state.sendSMS &&
      !this.state.sendEmail
    ) {
      return true;
    }
    return super.isSendButtonDisabled;
  },
  async sendMessage() {
    await this.processMessage(async (value) => {
      const postData = {
        attachments: this.props.composer.attachments,
        isNote: this.props.type === "note",
        mentionedChannels: this.props.composer.mentionedChannels,
        mentionedPartners: this.props.composer.mentionedPartners,
        cannedResponseIds: this.props.composer.cannedResponses.map((c) => c.id),
        parentId: this.props.messageToReplyTo?.message?.id,
        sendSMS: this.state.sendSMS,
        sendEmail: this.state.sendEmail,
      };
      await this._sendMessage(value, postData);
    });
  },
});
