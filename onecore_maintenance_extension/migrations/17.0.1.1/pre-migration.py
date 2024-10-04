# -*- coding: utf-8 -*-
def migrate(cr, version):
    """
    Creating a temporary field in maintenance_tenant_option to store the phone_number data
    """
    cr.execute('ALTER TABLE maintenance_tenant_option ADD COLUMN temp_phone_number integer')
    cr.execute('UPDATE maintenance_tenant_option SET temp_phone_number = CAST(phone_number AS integer)')

    """
    Creating a temporary field in maintenance_tenant to store the phone_number data
    """

    cr.execute('ALTER TABLE maintenance_tenant ADD COLUMN temp_phone_number integer')
    cr.execute('UPDATE maintenance_tenant SET temp_phone_number = CAST(phone_number AS integer)')
