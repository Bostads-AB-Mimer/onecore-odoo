-- ===========================================================================
-- Neutralize a local copy of the production Odoo database.
--
--   psql -d odoo_prod -v ON_ERROR_STOP=1 -f scripts/neutralize-prod-copy.sql
--
-- Guarantees that nothing in the copy can reach a real tenant or Mimer staff:
-- no SMTP, no web push, no cron, no queued mail, and no real phone numbers or
-- e-mail addresses left for the OneCore SMS/e-post path to send to.
--
-- Idempotent. Run it:
--   * after every fresh import of a production dump, AND
--   * after every `./run-local-odoo.sh` run -- `-u` reloads module data, which
--     reactivates the onecore ir.cron records (they ship with active=True).
--
-- Odoo's own `--neutralize` covers sections 1-4 (base + mail neutralize.sql).
-- Section 5 is the part Odoo knows nothing about: the tenant SMS/e-post path
-- runs over the OneCore API (POST /work-orders/send-sms, /work-orders/send-email),
-- and core's sendWorkOrderSms/sendWorkOrderEmail have no non-production
-- recipient redirect -- unlike the rest of communication-adapter, they pass the
-- recipient straight through to Infobip. Redacting the recipients is therefore
-- the only thing standing between a local test click and a real tenant's phone.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. SMTP: only the dummy invalid:1025 server stays active, and real
--    credentials are stripped so re-activating a row cannot send either.
-- ---------------------------------------------------------------------------
UPDATE ir_mail_server
   SET active = false,
       smtp_host = 'invalid',
       smtp_port = 1025,
       smtp_encryption = 'none',
       smtp_user = NULL,
       smtp_pass = NULL,
       google_gmail_refresh_token = NULL,
       google_gmail_access_token = NULL,
       microsoft_outlook_refresh_token = NULL,
       microsoft_outlook_access_token = NULL
 WHERE name <> 'neutralization - disable emails';

INSERT INTO ir_mail_server (name, smtp_port, smtp_host, smtp_encryption, active, smtp_authentication)
SELECT 'neutralization - disable emails', 1025, 'invalid', 'none', true, 'login'
 WHERE NOT EXISTS (SELECT 1 FROM ir_mail_server WHERE name = 'neutralization - disable emails');

-- ---------------------------------------------------------------------------
-- 2. mail/data/neutralize.sql
--    Web push is the one that surprises people: it reaches a real staff
--    browser through FCM without any SMTP server being involved at all.
-- ---------------------------------------------------------------------------
UPDATE mail_template SET mail_server_id = NULL;
UPDATE fetchmail_server SET active = false;

DELETE FROM ir_config_parameter
 WHERE key IN ('mail.web_push_vapid_private_key',
               'mail.web_push_vapid_public_key',
               'mail.sfu_server_key');
TRUNCATE mail_push;
DELETE FROM mail_push_device;

-- ---------------------------------------------------------------------------
-- 3. base/data/neutralize.sql: crons and webhooks
-- ---------------------------------------------------------------------------
UPDATE ir_cron
   SET active = false
 WHERE active;

UPDATE ir_act_server
   SET webhook_url = 'neutralization - disable webhook'
 WHERE state = 'webhook'
   AND coalesce(webhook_url, '') <> 'neutralization - disable webhook';

INSERT INTO ir_config_parameter (key, value)
VALUES ('database.is_neutralized', 'true')
    ON CONFLICT (key) DO UPDATE SET value = 'true';

-- ---------------------------------------------------------------------------
-- 4. Drain the outbound queues so nothing can be retried in bulk from the UI.
-- ---------------------------------------------------------------------------
UPDATE mail_mail SET state = 'cancel' WHERE state IN ('outgoing', 'exception');
UPDATE sms_sms SET state = 'canceled' WHERE state NOT IN ('sent', 'canceled');
UPDATE snailmail_letter SET state = 'canceled' WHERE state NOT IN ('sent', 'canceled');

-- ---------------------------------------------------------------------------
-- 5. OneCore SMS/e-post recipients.
--    'redacted' rather than NULL on purpose: the composer keeps its SMS and
--    e-post checkboxes enabled (they key off tenantHasPhoneNumber /
--    tenantHasEmail), so the flow stays visible while the value itself is
--    undeliverable and obvious to whoever is looking at the record.
-- ---------------------------------------------------------------------------
UPDATE maintenance_tenant
   SET phone_number = 'redacted'
 WHERE phone_number IS DISTINCT FROM 'redacted';
UPDATE maintenance_tenant
   SET email_address = 'redacted'
 WHERE email_address IS DISTINCT FROM 'redacted';

UPDATE maintenance_tenant_option
   SET phone_number = 'redacted'
 WHERE phone_number IS DISTINCT FROM 'redacted';
UPDATE maintenance_tenant_option
   SET email_address = 'redacted'
 WHERE email_address IS DISTINCT FROM 'redacted';

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification: every row below must read 0 (except is_neutralized = true).
-- ---------------------------------------------------------------------------
SELECT 'active mail servers other than the dummy' AS check, count(*)::text AS value
  FROM ir_mail_server WHERE active AND name <> 'neutralization - disable emails'
UNION ALL SELECT 'mail servers still holding credentials', count(*)::text
  FROM ir_mail_server WHERE coalesce(smtp_user, '') <> '' OR coalesce(smtp_pass, '') <> ''
UNION ALL SELECT 'active crons', count(*)::text FROM ir_cron WHERE active
UNION ALL SELECT 'mail queued for delivery', count(*)::text
  FROM mail_mail WHERE state IN ('outgoing', 'exception')
UNION ALL SELECT 'web push devices', count(*)::text FROM mail_push_device
UNION ALL SELECT 'web push keys', count(*)::text FROM ir_config_parameter
  WHERE key IN ('mail.web_push_vapid_private_key', 'mail.web_push_vapid_public_key', 'mail.sfu_server_key')
UNION ALL SELECT 'active fetchmail servers', count(*)::text FROM fetchmail_server WHERE active
UNION ALL SELECT 'templates bound to a mail server', count(*)::text
  FROM mail_template WHERE mail_server_id IS NOT NULL
UNION ALL SELECT 'tenants with a real phone or e-mail', count(*)::text
  FROM maintenance_tenant WHERE phone_number <> 'redacted' OR email_address <> 'redacted'
UNION ALL SELECT 'tenant options with a real phone or e-mail', count(*)::text
  FROM maintenance_tenant_option WHERE phone_number <> 'redacted' OR email_address <> 'redacted'
UNION ALL SELECT 'database.is_neutralized', value
  FROM ir_config_parameter WHERE key = 'database.is_neutralized';
