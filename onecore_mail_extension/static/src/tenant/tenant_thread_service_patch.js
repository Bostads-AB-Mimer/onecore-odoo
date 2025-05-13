/* @odoo-module */

import { ThreadService } from "@mail/core/common/thread_service";
import { prettifyMessageContent } from "@mail/utils/common/format";

import { patch } from "@web/core/utils/patch";

patch(ThreadService.prototype, {
  setup(env, services) {
    super.setup(env, services);
    this.notificationService = services["notification"];
  },
  async getIsHiddenFromMyPages(threadId) {
    try {
      const result = await this.rpc("/web/dataset/call_kw", {
        model: "maintenance.request",
        method: "fetch_is_hidden_from_my_pages",
        args: [threadId],
        kwargs: {},
      });
      return result;
    } catch (error) {
      console.error("Error fetching data:", error);
      return null;
    }
  },
  async getTenantContacts(threadId) {
    try {
      const result = await this.rpc("/web/dataset/call_kw", {
        model: "maintenance.request",
        method: "fetch_tenant_contact_data",
        args: [threadId],
        kwargs: {},
      });
      return result;
    } catch (error) {
      console.error("Error fetching tenant data:", error);
      return null;
    }
  },
  /**
   * Get the parameters to pass to the message post route.
   */
  async getMessagePostParams({ body, isNote, thread, sendSMS, sendEmail }) {
    let messageType;
    if (sendSMS && sendEmail) {
      messageType = "tenant_mail_and_sms";
    } else if (sendSMS && !sendEmail) {
      messageType = "tenant_sms";
    } else if (!sendSMS && sendEmail) {
      messageType = "tenant_mail";
    } else {
      messageType = "comment";
    }

    return {
      context: {
        mail_post_autofollow: !isNote && thread.hasWriteAccess,
      },
      post_data: {
        body: await prettifyMessageContent(body, []),
        attachment_ids: [],
        attachment_tokens: [],
        canned_response_ids: [],
        message_type: messageType,
        partner_ids: [],
        subtype_xmlid: "mail.mt_comment",
        partner_emails: [],
        partner_additional_values: {},
      },
      thread_id: thread.id,
      thread_model: thread.model,
    };
  },

  /**
   * @param {import("models").Thread} thread
   * @param {string} body
   */
  async post(thread, body, { isNote = false, sendSMS, sendEmail } = {}) {
    const params = await this.getMessagePostParams({
      body,
      isNote,
      thread,
      sendSMS,
      sendEmail,
    });

    const data = await this.rpc("/mail/message/post", params);
    const message = this.store.Message.insert(data, { html: true });

    switch (data.message_type) {
      case "tenant_sms" || "tenant_mail_failed_and_sms_ok":
        this.notificationService.add("SMS skickades till hyresgästen.", {
          title: "Skickat!",
          type: "info",
          sticky: true,
        });
        break;
      case "tenant_mail" || "tenant_mail_ok_and_sms_failed":
        this.notificationService.add("E-post skickades till hyresgästen.", {
          title: "Skickat!",
          type: "info",
          sticky: true,
        });
        break;
      case "tenant_mail_and_sms":
        this.notificationService.add(
          "E-post och SMS skickades till hyresgästen.",
          {
            title: "Skickat!",
            type: "info",
            sticky: true,
          }
        );
        break;
      case "failed_tenant_sms" || "tenant_mail_ok_and_sms_failed":
        this.notificationService.add(
          "Kunde inte skicka SMS till hyresgästen. Kontrollera så att telefonnumret stämmer.",
          {
            title: "Misslyckades",
            type: "warning",
            sticky: true,
          }
        );
        break;
      case "failed_tenant_mail" || "tenant_mail_failed_and_sms_ok":
        this.notificationService.add(
          "Kunde inte skicka e-post till hyresgästen. Kontrollera så att e-postadressen stämmer.",
          {
            title: "Misslyckades",
            type: "warning",
            sticky: true,
          }
        );
        break;
      case "failed_tenant_mail_and_sms":
        this.notificationService.add(
          "Kunde inte skicka e-post och SMS till hyresgästen. Kontrollera så att telefonnummer och e-postadress stämmer.",
          {
            title: "Misslyckades",
            type: "warning",
            sticky: true,
          }
        );
        break;

      default:
        break;
    }

    return message;
  },
});
