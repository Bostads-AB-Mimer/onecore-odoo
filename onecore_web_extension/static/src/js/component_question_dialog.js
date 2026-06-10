/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * Three-outcome dialog asked when an internal user sets a maintenance
 * request to "Utförd" on an apartment ärende: has a property component been
 * replaced?
 *
 * Custom component (not ConfirmationDialog) so that Ja/Nej are explicit
 * labeled buttons while dismiss (X/Esc) is a distinct third outcome that
 * aborts the stage change.
 */
export class ComponentQuestionDialog extends Component {
  static template = "onecore_web_extension.ComponentQuestionDialog";
  static components = { Dialog };
  static props = {
    close: Function, // injected by the dialog service
    answer: Function, // callback("yes" | "no")
  };

  _answer(value) {
    this.props.answer(value);
    this.props.close();
  }

  onYes() {
    this._answer("yes");
  }

  onNo() {
    this._answer("no");
  }
}

/**
 * Shows the component question and resolves with the user's answer.
 *
 * - "yes": proceed with the stage change and open the component wizard
 * - "no": proceed with the stage change only
 * - "abort": cancel the stage change (X or Esc without answering)
 *
 * @param {Object} dialogService - the "dialog" service
 * @returns {Promise<"yes"|"no"|"abort">}
 */
export function askComponentQuestion(dialogService) {
  return new Promise((resolve) => {
    let resolved = false;
    const answer = (value) => {
      if (!resolved) {
        resolved = true;
        resolve(value);
      }
    };

    dialogService.add(
      ComponentQuestionDialog,
      { answer },
      {
        // X / Esc without picking a button → abort the stage change
        onClose: () => answer("abort"),
      }
    );
  });
}
