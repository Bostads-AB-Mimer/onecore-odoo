/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Message } from '@mail/core/common/message';
import { browser } from "@web/core/browser/browser";
import { useRef, useExternalListener, onMounted } from '@odoo/owl'

patch(Message.prototype, {
    setup() {
        super.setup();
        this.messageRef = useRef('messageRef');
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
});
