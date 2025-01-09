/* @odoo-module */

import { Store } from "@mail/core/common/store_service";
import { prettifyMessageContent } from '@mail/utils/common/format'
import { rpc } from "@web/core/network/rpc";

import { patch } from '@web/core/utils/patch'

patch(Store.prototype, {
  setup(env, services) {
    super.setup(env, services)
    this.rpc = rpc;

  },
  async getTenantContacts(threadId) {
    try {
      const result = await this.rpc('/web/dataset/call_kw', {
        model: 'maintenance.request',
        method: 'fetch_tenant_contact_data',
        args: [threadId],
        kwargs: {},
      })
      return result
    } catch (error) {
      console.error('Error fetching tenant data:', error)
      return null
    }
  },
  /**
   * Get the parameters to pass to the message post route.
   */
  async getMessagePostParams({ body, isNote, thread, sendSMS, sendEmail }) {
    let messageType
    if (sendSMS && sendEmail) {
      messageType = 'tenant_mail_and_sms'
    } else if (sendSMS && !sendEmail) {
      messageType = 'tenant_sms'
    } else if (!sendSMS && sendEmail) {
      messageType = 'tenant_mail'
    } else {
      messageType = 'comment'
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
        subtype_xmlid: 'mail.mt_comment',
        partner_emails: [],
        partner_additional_values: {},
      },
      thread_id: thread.id,
      thread_model: thread.model,
    }
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
    })

    const data = await this.rpc('/mail/message/post', params)
    const message = this.store.Message.insert(data, { html: true })


    return message
  },
})
