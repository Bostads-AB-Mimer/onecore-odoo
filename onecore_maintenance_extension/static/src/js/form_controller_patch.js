/** @odoo-module **/

import { FormController } from '@web/views/form/form_controller';
import { onWillStart } from '@odoo/owl'
import { useService } from '@web/core/utils/hooks'
import { patch } from '@web/core/utils/patch'

// This patch is used to prevent external contractors from creating maintenance requests 
// using the button in the request details view.

patch(FormController.prototype, {
    setup(env, services) {
      super.setup(env, services)
      this.rpc = useService('rpc')
  
      onWillStart(async () => {
          const isExternalContractor = await this.rpc('/web/dataset/call_kw', {
            model: 'maintenance.request',
            method: 'is_user_external_contractor',
            args: [],
            kwargs: {},
          })
    
          this.canCreate = !isExternalContractor
        })
    },
  })