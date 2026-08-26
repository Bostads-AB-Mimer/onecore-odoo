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
      sendMyPages: true,
      informOpposite: false,
      userIsExternalContractor: false,
      tenantHasEmail: false,
      tenantHasPhoneNumber: false,
      isHiddenFromMyPages: false,
      // Guards the send button while the async onMounted fetches are in
      // flight: sendMyPages defaults to true, so without this a handler
      // could publish to a hidden errand in the first few hundred ms.
      tenantStateLoaded: false,
    });

    onMounted(async () => {
      if (this.thread?.model !== "maintenance.request") {
        return;
      }
      try {
        const isHiddenResult = await this.orm.call(
          "maintenance.request",
          "fetch_is_hidden_from_my_pages",
          [this.thread.id],
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
          [this.thread.id],
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
          [],
        );
      } catch (error) {
        console.error("Error fetching external contractor state:", error);
      }
      this.tenantState.tenantStateLoaded = true;
    });
  },

  onSMSCheckboxChange(checked) {
    this.tenantState.sendSMS = checked;
  },
  onEMailCheckboxChange(checked) {
    this.tenantState.sendEmail = checked;
  },
  onMyPagesCheckboxChange(checked) {
    this.tenantState.sendMyPages = checked;
  },
  onInformOppositeChange(checked) {
    this.tenantState.informOpposite = checked;
  },

  // SMS and e-post messages are already published on Mina sidor, so those
  // channels are notifications layered on top of a Mina sidor publication —
  // never alternatives to it. Selecting either forces this box on.
  get myPagesLocked() {
    return this.tenantState.sendSMS || this.tenantState.sendEmail;
  },
  get myPagesChecked() {
    return this.myPagesLocked || this.tenantState.sendMyPages;
  },

  // "Inform the opposite party" only applies to the internal Mimer <-> external
  // contractor log-note dialog, so the checkbox is shown in Log note mode only.
  get showInformOpposite() {
    return (
      this.props.type === "note" && this.thread?.model === "maintenance.request"
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
      this.thread?.model === "maintenance.request"
    ) {
      if (
        !this.tenantState.tenantStateLoaded ||
        this.tenantState.isHiddenFromMyPages
      ) {
        return true;
      }
      if (!this.myPagesChecked) {
        return true;
      }
    }
    return super.isSendButtonDisabled;
  },

  get postData() {
    const data = super.postData;
    if (this.thread?.model === "maintenance.request") {
      data.sendSMS = this.tenantState.sendSMS;
      data.sendEmail = this.tenantState.sendEmail;
      data.sendMyPages = this.myPagesChecked;
      data.informOpposite = this.tenantState.informOpposite;
    }
    return data;
  },
});
