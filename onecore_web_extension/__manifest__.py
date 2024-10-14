# -*- coding: utf-8 -*-

{
    'name': 'ONECore Web Extension',
    'version': '1.0',
    'sequence': 100,
    'category': 'Hidden',
    'description': 'Extends the web module with ONECore features.',
    'depends': ['base', 'web'],
    'summary': 'Extends the web module with ONECore features.',
    'assets': {
        'web.assets_backend': [
            'onecore_web_extension/static/src/views/*.xml',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
}
