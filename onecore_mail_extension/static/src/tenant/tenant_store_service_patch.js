/* @odoo-module */

import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    async getMessagePostParams({ body, postData, thread }) {
        const params = await super.getMessagePostParams({ body, postData, thread });
        if (postData.sendSMS || postData.sendEmail) {
            let messageType;
            if (postData.sendSMS && postData.sendEmail) {
                messageType = "tenant_mail_and_sms";
            } else if (postData.sendSMS) {
                messageType = "tenant_sms";
            } else {
                messageType = "tenant_mail";
            }
            params.post_data.message_type = messageType;
        }
        return params;
    },
});
