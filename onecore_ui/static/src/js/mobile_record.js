/** @odoo-module **/

import { _t } from '@web/core/l10n/translation';
import { Component, useRef, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { isRelational } from '@web/model/relational_model/utils';
import { useRecordObserver } from '@web/model/relational_model/utils';
import { isNull } from '@web/views/utils';

const formatters = registry.category('formatters');

/**
 * Returns a "raw" version of the field value on a given record.
 *
 * @param {Record} record
 * @param {string} fieldName
 * @returns {any}
 */
export function getRawValue(record, fieldName) {
  const field = record.fields[fieldName];
  const value = record.data[fieldName];
  switch (field.type) {
    case 'one2many':
    case 'many2many': {
      return value.count ? value.currentIds : [];
    }
    case 'many2one': {
      return (value && value[0]) || false;
    }
    case 'date':
    case 'datetime': {
      return value && value.toISO();
    }
    default: {
      return value;
    }
  }
}

/**
 * Returns a formatted version of the field value on a given record.
 *
 * @param {Record} record
 * @param {string} fieldName
 * @returns {string}
 */
function getValue(record, fieldName) {
  const field = record.fields[fieldName];
  const value = record.data[fieldName];
  const formatter = formatters.get(field.type, String);
  return formatter(value, { field, data: record.data });
}

export function getFormattedRecord(record) {
  const formattedRecord = {
    id: {
      value: record.resId,
      raw_value: record.resId,
    },
  };

  for (const fieldName of record.fieldNames) {
    formattedRecord[fieldName] = {
      value: getValue(record, fieldName),
      raw_value: getRawValue(record, fieldName),
    };
  }
  return formattedRecord;
}
export class MobileRecord extends Component {
  static template = "onecore_ui.MobileRecord";

  setup() {
    this.state = useState({ record: {}, widget: {} });
    useRecordObserver((record) =>
      Object.assign(this.state.record, getFormattedRecord(record))
    );
  }

  get record() {
    return this.state.record;
  }

  /**
   * @param {MouseEvent} ev
   */
  onRecordClick(props) {
    const { openRecord, record, selectedGroup } = props;
    sessionStorage.setItem("selectedGroupName", selectedGroup.displayName);
    openRecord(record);
  }
}

MobileRecord.defaultProps = {
  openRecord: () => {},
};
MobileRecord.props = [
  'archInfo?',
  'canResequence?',
  'colors?',
  'Compiler?',
  'forceGlobalClick?',
  'group?',
  'list',
  'deleteRecord?',
  'openRecord?',
  'readonly?',
  'record',
  'templates?',
  'progressBarState?',
];
