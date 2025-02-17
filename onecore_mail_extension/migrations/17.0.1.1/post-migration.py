# -*- coding: utf-8 -*-
def migrate(cr, version):
    """
    This migration sets the default value of internal mail message subtypes to true.
    This is done to ensure that followers gets notified on notes and activities by default.
    """
    cr.execute(
        'UPDATE mail_message_subtype SET "default" = true WHERE "internal" = true'
    )
