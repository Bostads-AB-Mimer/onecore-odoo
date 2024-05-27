/** @odoo-module **/
import { Component, useState, reactive } from '@odoo/owl'
import { Layout } from '@web/search/layout'
import { useModelWithSampleData } from '@web/model/model'
import { CogMenu } from '@web/search/cog_menu/cog_menu'
import { SearchBar } from '@web/search/search_bar/search_bar'
import { ViewButton } from '@web/views/view_button/view_button'
import { Dropdown } from '@web/core/dropdown/dropdown'
import { DropdownItem } from '@web/core/dropdown/dropdown_item'
import { extractFieldsFromArchInfo } from '@web/model/relational_model/utils'
import { session } from '@web/session'
import { useBus, useService } from '@web/core/utils/hooks'
import { useSearchBarToggler } from '@web/search/search_bar/search_bar_toggler'
import { useSetupView } from '@web/views/view_hook'
import { MobileRenderer } from './mobile_renderer'
import { standardViewProps } from '@web/views/standard_view_props'

const QUICK_CREATE_FIELD_TYPES = [
  'char',
  'boolean',
  'many2one',
  'selection',
  'many2many',
]

export class MobileController extends Component {
  static components = {
    Layout,
    MobileRenderer,
    Dropdown,
    DropdownItem,
    ViewButton,
    CogMenu,
    SearchBar,
  }
  async setup() {
    this.viewService = useService('view')
    this.dataSearch = []
    this.ui = useService('ui')
    useBus(this.ui.bus, 'resize', this.render)
    this.archInfo = this.props.archInfo
    const fields = this.props.fields
    this.model = useState(
      useModelWithSampleData(this.props.Model, this.modelParams)
    )
    this.searchBarToggler = useSearchBarToggler()
    const self = this
    this.quickCreateState = reactive({
      get groupId() {
        return this._groupId || false
      },
      set groupId(groupId) {
        if (self.model.useSampleModel) {
          self.model.removeSampleDataInGroups()
          self.model.useSampleModel = false
        }
        this._groupId = groupId
      },
      view: this.archInfo.quickCreateView,
    })

    useSetupView({
      rootRef: this.rootRef,
      beforeLeave: async () => {
        return this.model.root.leaveEditMode()
      },
      beforeUnload: async (ev) => {
        const editedRecord = this.model.root.editedRecord
        if (editedRecord) {
          const isValid = await editedRecord.urgentSave()
          if (!isValid) {
            ev.preventDefault()
            ev.returnValue = 'Unsaved changes'
          }
        }
      },
      getOrderBy: () => {
        return this.model.root.orderBy
      },
    })
  }

  get modelParams() {
    const { defaultGroupBy, rawExpand } = this.archInfo
    const { activeFields, fields } = extractFieldsFromArchInfo(
      this.archInfo,
      this.props.fields
    )
    const groupByInfo = {}
    for (const fieldName in this.archInfo.groupBy.fields) {
      const fieldNodes = this.archInfo.groupBy.fields[fieldName].fieldNodes
      const fields = this.archInfo.groupBy.fields[fieldName].fields
      groupByInfo[fieldName] = extractFieldsFromArchInfo({ fieldNodes }, fields)
    }
    const modelConfig = this.props.state?.modelState?.config || {
      resModel: this.props.resModel,
      fields,
      activeFields,
      openGroupsByDefault: true,
    }
    return {
      config: modelConfig,
      state: this.props.state?.modelState,
      groupByInfo,
      limit: null,
      countLimit: this.archInfo.countLimit,
      defaultOrderBy: this.archInfo.defaultOrder,
      defaultGroupBy: this.props.searchMenuTypes.includes('groupBy')
        ? defaultGroupBy
        : false,
      groupsLimit: this.archInfo.groupsLimit,
      multiEdit: this.archInfo.multiEdit,
      activeIdsLimit: session.active_ids_limit,
    }
  }
  async createRecord() {
    const { onCreate } = this.archInfo
    const { root } = this.model
    if (this.canQuickCreate && onCreate === 'quick_create') {
      const firstGroup = root.groups[0]
      if (firstGroup.isFolded) {
        await firstGroup.toggle()
      }
      this.quickCreateState.groupId = firstGroup.id
    } else if (onCreate && onCreate !== 'quick_create') {
      const options = {
        additionalContext: root.context,
        onClose: async () => {
          await root.load()
          this.model.useSampleModel = false
          this.render(true) // FIXME WOWL reactivity
        },
      }
      await this.actionService.doAction(onCreate, options)
    } else {
      await this.props.createRecord()
    }
  }

  get canCreate() {
    const { create, createGroup } = this.archInfo.activeActions
    const list = this.model.root
    if (!create) {
      return false
    }
    if (list.isGrouped) {
      if (list.groupByField.type !== 'many2one') {
        return true
      }
      return list.groups.length || !createGroup
    }
    return true
  }

  get canQuickCreate() {
    const { activeActions } = this.props.archInfo
    if (!activeActions.quickCreate) {
      return false
    }

    const list = this.model.root
    if (list.groups && !list.groups.length) {
      return false
    }

    return this.isQuickCreateField(list.groupByField)
  }
  isQuickCreateField(field) {
    return field && QUICK_CREATE_FIELD_TYPES.includes(field.type)
  }

  async openRecord(record, mode) {
    const activeIds = this.model.root.records.map(
      (datapoint) => datapoint.resId
    );
    this.props.selectRecord(record.resId, { activeIds, mode });
  }
}
MobileController.template = 'onecore_ui.MobileView'
MobileController.props = {
  ...standardViewProps,
  defaultGroupBy: {
    validate: (dgb) => !dgb || typeof dgb === 'string',
    optional: true,
  },
  showButtons: { type: Boolean, optional: true },

  Compiler: { type: Function, optional: true }, // optional in stable for backward compatibility
  Model: Function,
  Renderer: Function,
  archInfo: Object,
}

MobileController.defaultProps = {
  createRecord: () => {},
  showButtons: true,
}
