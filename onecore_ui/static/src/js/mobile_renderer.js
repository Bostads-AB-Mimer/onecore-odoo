/** @odoo-module **/
import { Component } from '@odoo/owl';
import { View } from '@web/views/view';
import { Field } from '@web/views/fields/field';
import { isNull } from '@web/views/utils';
import { Record } from '@web/model/record';
import { ViewScaleSelector } from '@web/views/view_components/view_scale_selector';
import { MobileGroup } from './mobile_group';
export class MobileRenderer extends Component {
  static props = ['archInfo', 'list'];
  async setup() {}

  getGroupsOrRecords() {
    const { list } = this.props;
    if (list.isGrouped) {
      return [...list.groups]
        .sort((a, b) =>
          a.value && !b.value ? 1 : !a.value && b.value ? -1 : 0
        )
        .map((group, i) => ({
          group,
          key: isNull(group.value)
            ? `group_key_${i}`
            : String(group.value),
        }));
    } else {
      return list.records.map((record) => ({
        record,
        key: record.id,
      }));
    }
  }
}
MobileRenderer.template = 'onecore_ui.MobileRenderer';
MobileRenderer.components = {
  View,
  Field,
  Record,
  ViewScaleSelector,
  MobileGroup,
};
