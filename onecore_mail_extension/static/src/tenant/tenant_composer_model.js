/* @odoo-module */

import { OR, Record } from "@mail/core/common/record";
import { Composer as ComposerModel } from "@mail/core/common/composer_model";

export class TenantComposerModel extends ComposerModel {
    static id = OR("thread", "message");
    /** @returns {import("models").TenantComposerModel} */
    static get(data) {
        return super.get(data);
    }
    /** @returns {import("models").TenantComposerModel|import("models").TenantComposerModel[]} */
    static insert(data) {
        return super.insert(...arguments);
    }

    attachments = Record.many("Attachment");
    message = Record.one("Message");
    mentionedPartners = Record.many("Persona");
    mentionedChannels = Record.many("Thread");
    cannedResponses = Record.many("CannedResponse");
    textInputContent = "";
    thread = Record.one("Thread");
    /** @type {{ start: number, end: number, direction: "forward" | "backward" | "none"}}*/
    selection = {
        start: 0,
        end: 0,
        direction: "none",
    };
    /** @type {boolean} */
    forceCursorMove;
    isFocused = false;
    autofocus = 0;
}

TenantComposerModel.register();
