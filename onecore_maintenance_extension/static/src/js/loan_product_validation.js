/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(StatusBarField.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.orm = useService("orm");
    },

    async selectItem(item) {
        const resModel = this.props.record.resModel;

        // Only apply to maintenance.request model
        if (resModel !== "maintenance.request") {
            return super.selectItem(item);
        }

        // Check if moving to "Avslutad" stage
        if (item.label === "Avslutad") {
            const has_loan_product = this.props.record.data.has_loan_product;
            const loan_product_details = this.props.record.data.loan_product_details || "";

            // If loan product is active, show confirmation dialog
            if (has_loan_product) {
                const confirmed = await this._showLoanProductDialog(loan_product_details);

                if (confirmed) {
                    // User chose "Återlämna och avsluta"
                    // Use proper update method to ensure field is in change set
                    await this.props.record.update({
                        has_loan_product: false
                    });

                    // Proceed with stage change
                    return super.selectItem(item);
                } else {
                    // User chose "Ångra" - do nothing
                    return;
                }
            }
        }

        // For all other cases, proceed normally
        return super.selectItem(item);
    },

    _showLoanProductDialog(productDetails) {
        return new Promise((resolve) => {
            const bodyMessage = productDetails
                ? `Det finns en låneprodukt (${productDetails}) i ärendet. Har kunden lämnat tillbaka låneprodukten?`
                : "Det finns en låneprodukt i ärendet. Har kunden lämnat tillbaka låneprodukten?";

            this.dialogService.add(ConfirmationDialog, {
                title: _t("Låneprodukt ej återlämnad"),
                body: _t(bodyMessage),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
                confirmLabel: _t("Återlämna och avsluta"),
                cancelLabel: _t("Ångra"),
            });
        });
    },
});
