/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, useRef } from "@odoo/owl";
import { isRelational } from "@web/model/relational_model/utils";
import { isNull } from "@web/views/utils";

export class MobileGroup extends Component {
  static template = "onecore_ui.MobileGroup";
  static props = {
    group: { type: Object },
    list: { type: Object },
  };

  // ------------------------------------------------------------------------
  // Getters, can be used as variables from xml-file, i.e get groupName() {...} will be available as groupName in xml
  // ------------------------------------------------------------------------

  get group() {
    return this.props.group;
  }

  _getEmptyGroupLabel(fieldName) {
    return _t("None");
  }

  get groupName() {
    const { groupByField, displayName } = this.group;
    let name = displayName;
    if (groupByField.type === "boolean") {
      name = name ? _t("Yes") : _t("No");
    } else if (!name) {
      if (
        isRelational(groupByField) ||
        groupByField.type === "date" ||
        groupByField.type === "datetime" ||
        isNull(name)
      ) {
        name = this._getEmptyGroupLabel(groupByField.name);
      }
    }
    return name;
  }
}
