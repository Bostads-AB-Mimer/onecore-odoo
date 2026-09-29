"""MIM-2010 — adopt a hand-made ``onecore_auth.auto_create_email_domains``.

data/ir_config_parameter.xml ships the parameter as a noupdate record. A plain
record with a fresh xml id is an INSERT, and ir.config_parameter has a unique
constraint on ``key``: if somebody has already created the parameter under
Inställningar → Teknik → Systemparametrar — plausible, it is the feature's
on/off switch — the data load fails with "Key must be unique". That failure
lands in the odoo-module-upgrade Job, the step that has to succeed before the
rollout restart (review of PR #292).

So, before the data is loaded: when such a row exists and nothing in
ir_model_data points at it yet, register it under the xml id the data file
uses. The load then finds the record by xml id, sees noupdate, and leaves the
hand-made value alone. Idempotent; a database without the row or with the xml
id already in place is untouched.
"""

PARAM_KEY = "onecore_auth.auto_create_email_domains"
XML_MODULE = "onecore_auth"
XML_NAME = "param_auto_create_email_domains"


def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
        SELECT %s, %s, 'ir.config_parameter', p.id, true
          FROM ir_config_parameter p
         WHERE p.key = %s
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data d
                WHERE d.module = %s AND d.name = %s
           )
        """,
        (XML_MODULE, XML_NAME, PARAM_KEY, XML_MODULE, XML_NAME),
    )
