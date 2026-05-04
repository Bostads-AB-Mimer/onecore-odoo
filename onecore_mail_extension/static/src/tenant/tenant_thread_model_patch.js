/* @odoo-module */

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    async post(body, postData = {}, extraData = {}) {
        const message = await super.post(body, postData, extraData);
        if (message) {
            const notificationService = this.store.env.services.notification;
            switch (message.message_type) {
                case "tenant_sms":
                case "tenant_mail_failed_and_sms_ok":
                    notificationService.add("SMS skickades till hyresgästen.", {
                        title: "Skickat!",
                        type: "info",
                        sticky: true,
                    });
                    break;
                case "tenant_mail":
                case "tenant_mail_ok_and_sms_failed":
                    notificationService.add("E-post skickades till hyresgästen.", {
                        title: "Skickat!",
                        type: "info",
                        sticky: true,
                    });
                    break;
                case "tenant_mail_and_sms":
                    notificationService.add(
                        "E-post och SMS skickades till hyresgästen.",
                        {
                            title: "Skickat!",
                            type: "info",
                            sticky: true,
                        }
                    );
                    break;
                case "failed_tenant_sms":
                    notificationService.add(
                        "Kunde inte skicka SMS till hyresgästen. Kontrollera så att telefonnumret stämmer.",
                        {
                            title: "Misslyckades",
                            type: "warning",
                            sticky: true,
                        }
                    );
                    break;
                case "failed_tenant_mail":
                    notificationService.add(
                        "Kunde inte skicka e-post till hyresgästen. Kontrollera så att e-postadressen stämmer.",
                        {
                            title: "Misslyckades",
                            type: "warning",
                            sticky: true,
                        }
                    );
                    break;
                case "failed_tenant_mail_and_sms":
                    notificationService.add(
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
        }
        return message;
    },
});
