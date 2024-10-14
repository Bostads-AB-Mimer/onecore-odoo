# -*- coding: utf-8 -*-

{
    'name': 'ONECore Maintenance Extension',
    'version': '1.0',
    'sequence': 100,
    'category': 'Manufacturing/Maintenance',
    'description': 'Extends the maintenance module with ONECore features.',
    'depends': ['maintenance', 'onecore_auth', 'onecore_ui'],
    'summary': 'Extends the maintenance module with ONECore features.',
    'website': 'https://www.odoo.com/app/maintenance',
    'data': [
      'security/maintenance.xml',
      'security/ir.model.access.csv',
      'views/maintenance_views.xml',
      'views/mobile_view.xml',

      # Load initial Data
      'data/maintenance.team.csv'

    ],
    'assets': {
        'web.assets_backend': [
            'onecore_maintenance_extension/static/src/views/chatter.xml',
            'onecore_maintenance_extension/static/src/views/maintenance_request_item.xml',
        ],
    },
    'post_init_hook': '_post_init_hook',
    'auto_install': True,
    'license': 'LGPL-3',
}
