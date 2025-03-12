/** @odoo-module **/

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const ConfirmDialog = (dialogService, title, body) => {
  return new Promise((resolve) => {
    dialogService.add(ConfirmationDialog, {
      title,
      body,
      confirm: () => resolve(true),
      cancel: () => resolve(false),
      confirmLabel: "Ok",
      cancelLabel: "Avbryt",
    });
  });
};

export default ConfirmDialog;
