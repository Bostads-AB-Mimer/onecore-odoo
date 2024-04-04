# -*- coding: utf-8 -*-

{
    'name': 'ONECore Maintenance Extension',
    'version': '1.0',
    'sequence': 100,
    'category': 'Manufacturing/Maintenance',
    'description': 'Extends the maintenance module with ONECore features.',
    'depends': ['maintenance'],
    'summary': 'Extends the maintenance module with ONECore features.',
    'website': 'https://www.odoo.com/app/maintenance',
    'data': [
      'security/maintenance.xml',
      'security/ir.model.access.csv',
      'views/maintenance_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
}
