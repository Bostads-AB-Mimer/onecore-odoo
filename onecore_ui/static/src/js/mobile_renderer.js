/** @odoo-module **/
import { Component, useState, onMounted } from '@odoo/owl';
import { View } from '@web/views/view';
import { Field } from '@web/views/fields/field';
import { isNull } from '@web/views/utils';
import { Record } from '@web/model/record';
import { isRelational } from '@web/model/relational_model/utils';
import { ViewScaleSelector } from '@web/views/view_components/view_scale_selector';
import { MobileGroup } from './mobile_group';
import { MobileRecord } from './mobile_record';
export class MobileRenderer extends Component {
  static props = ['archInfo', 'list', 'openRecord'];
  setup() {
    this.state = useState({
      selectedGroup: false,
    });

    onMounted(() => {
      const storedSelectedGroupName = sessionStorage.getItem('selectedGroupName');
      if (storedSelectedGroupName) {
        this.state.selectedGroup = this.props.list.groups.find(
          (group) => group.displayName === storedSelectedGroupName
        ) || false;
      }
    })
  }

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

  onGroupClick(group) {
    this.state.selectedGroup = group;
  }

  onBackClick() {
    sessionStorage.removeItem("selectedGroupName");
    this.state.selectedGroup = false;
  }

  // ------------------------------------------------------------------------
  // Getters, can be used as variables from xml-file, i.e get groupName() {...} will be available as groupName in xml
  // ------------------------------------------------------------------------

  _getEmptyGroupLabel(fieldName) {
    return _t('None');
  }

  get groupName() {
    const { groupByField, displayName } = this.state.selectedGroup;
    let name = displayName;
    if (groupByField.type === 'boolean') {
      name = name ? _t('Yes') : _t('No');
    } else if (!name) {
      if (
        isRelational(groupByField) ||
        groupByField.type === 'date' ||
        groupByField.type === 'datetime' ||
        isNull(name)
      ) {
        name = this._getEmptyGroupLabel(groupByField.name);
      }
    }
    return name;
  }
}
MobileRenderer.template = 'onecore_ui.MobileRenderer';
MobileRenderer.components = {
  View,
  Field,
  Record,
  ViewScaleSelector,
  MobileGroup,
  MobileRecord,
};
