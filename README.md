# onecore-odoo

## Enabling SSO with Azure

https://www.odoo.com/documentation/17.0/applications/general/users/azure.html

## Restore backup db
IMPORTANT! When restoring a backup db the owner of the db needs to be `bn_odoo` for Odoo to recognize it. 

## Migrations
Whenever you need to make a change to an existing model you need to create a migration to prevent data in that model to be lost. Roughly what you do is this:

- Create a `migrations` folder unless one exists already.
  
- Increase the version in the manifest file of your module and create a folder inside the migrations folder named {odoo-version}.{module-version}. Eg. if Odoo 17.0 and module version 1.1 the migration folder should be named `17.0.1.1`.
  
- Inside the migration folder you create your pre-, post- and/or end-scripts. The order of execution if you have several scripts of the same kind is lexical, like this:
  1. `pre-10-do_something.py`
  2. `pre-20-something_else.py`
  3. `post-do_something.py`
  4. `post-something.py`
  5. `end-01-migrate.py`
  6. `end-migrate.py`

- Upgrade your module.

Here's a complete [example](https://github.com/Bostads-AB-Mimer/onecore-odoo/tree/johanneskarlsson/mim-99-testa-migration-manager) of a migration that stores and restores the data of the `phone_number` field in the `maintenance_tenant_option` and `maintenance_tenant` models as the `phone_number` field type is converted from Char to Integer. 

### Rollback migrations
I have yet to find a way to rollback migrations so for now I guess we need to create another commit that reverts the changes to the model and create another migration that reverts the changes to the data. 
