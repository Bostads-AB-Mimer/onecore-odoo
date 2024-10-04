# -*- coding: utf-8 -*-
def migrate(cr, version):
    """
    Restore phone_number data from temporary field to the original phone_number field
    Remove temporary field from the maintenance_tenant_option
    """
    cr.execute('UPDATE maintenance_tenant_option SET phone_number=temp_phone_number')
    cr.execute('ALTER TABLE maintenance_tenant_option DROP COLUMN temp_phone_number')

    """
    Restore phone_number data from temporary field to the original phone_number field
    Remove temporary field from the maintenance_tenant
    """
    cr.execute('UPDATE maintenance_tenant SET phone_number=temp_phone_number')
    cr.execute('ALTER TABLE maintenance_tenant DROP COLUMN temp_phone_number')
