/* @odoo-module */

import { CheckBox } from "@web/core/checkbox/checkbox";
import { Composer } from "@mail/core/common/composer";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useState, onMounted } from "@odoo/owl";

patch(Composer, {
    components: { ...Composer.components, CheckBox },
});

patch(Composer.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.tenantState = useState({
            sendSMS: false,
            sendEmail: false,
            informOpposite: false,
            userIsExternalContractor: false,
            tenantHasEmail: false,
            tenantHasPhoneNumber: false,
            isHiddenFromMyPages: false,
        });

        onMounted(async () => {
            if (this.thread?.model !== "maintenance.request") {
                return;
            }
            try {
                const isHiddenResult = await this.orm.call(
                    "maintenance.request",
                    "fetch_is_hidden_from_my_pages",
                    [this.thread.id]
                );
                this.tenantState.isHiddenFromMyPages =
                    isHiddenResult?.hidden_from_my_pages || false;
            } catch (error) {
                console.error("Error fetching hidden state:", error);
            }
            try {
                const tenantResult = await this.orm.call(
                    "maintenance.request",
                    "fetch_tenant_contact_data",
                    [this.thread.id]
                );
                this.tenantState.tenantHasEmail = tenantResult?.has_email || false;
                this.tenantState.tenantHasPhoneNumber =
                    tenantResult?.has_phone_number || false;
            } catch (error) {
                console.error("Error fetching tenant data:", error);
            }
            try {
                this.tenantState.userIsExternalContractor = await this.orm.call(
                    "maintenance.request",
                    "is_user_external_contractor",
                    []
                );
            } catch (error) {
                console.error("Error fetching external contractor state:", error);
            }
        });
    },

    onSMSCheckboxChange(checked) {
        this.tenantState.sendSMS = checked;
    },
    onEMailCheckboxChange(checked) {
        this.tenantState.sendEmail = checked;
    },
    onInformOppositeChange(checked) {
        this.tenantState.informOpposite = checked;
    },

    // "Inform the opposite party" only applies to the internal Mimer <-> external
    // contractor log-note dialog, so the checkbox is shown in Log note mode only.
    get showInformOpposite() {
        return (
            this.props.type === "note" &&
            this.thread?.model === "maintenance.request"
        );
    },

    // Name the actual recipient side: a contractor informs Mimer, a Mimer
    // handler informs the contractor.
    get informOppositeLabel() {
        return this.tenantState.userIsExternalContractor
            ? "Informera Mimer"
            : "Informera leverantör";
    },

    get placeholder() {
        if (
            this.props.type === "message" &&
            this.thread?.model === "maintenance.request"
        ) {
            return "Skriv ett meddelande till hyresgäst";
        }
        return super.placeholder;
    },

    get isSendButtonDisabled() {
        if (
            this.props.type === "message" &&
            this.thread?.model === "maintenance.request" &&
            !this.tenantState.sendSMS &&
            !this.tenantState.sendEmail
        ) {
            return true;
        }
        return super.isSendButtonDisabled;
    },

    get postData() {
        const data = super.postData;
        if (this.thread?.model === "maintenance.request") {
            data.sendSMS = this.tenantState.sendSMS;
            data.sendEmail = this.tenantState.sendEmail;
            data.informOpposite = this.tenantState.informOpposite;
        }
        return data;
    },
});
