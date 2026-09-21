"""Keycloak login hooks (MIM-2010, MIM-2011).

Lives here and not in onecore_base_extension because only a module that
depends on ``auth_oauth`` is guaranteed to load after it — and stock
``_auth_oauth_signin`` does not call super(), so an override that loads
first is silently dead.

One override, two jobs, in this order:

1. MIM-2010 — get a login for the Keycloak subject. Stock only knows users
   that already carry the subject as ``oauth_uid``; an employee who has never
   logged in via Keycloak is re-linked (existing account) or created (new
   employee) here instead of being turned away.
2. MIM-2011 — copy the AD department claim onto that user. Last on purpose,
   so a user created or re-linked a moment ago gets their department in the
   very same login.
"""

import logging
import re

from psycopg2 import errors as pg_errors

from odoo import SUPERUSER_ID, api, models
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tools import email_normalize
from odoo.tools.mail import email_domain_extract, email_escape_char

_logger = logging.getLogger(__name__)

# ir.config_parameter key naming the userinfo claim that carries the AD unit.
# Ops create the Keycloak protocol mapper by hand (the realm is not in git);
# if they pick another claim name it must not take a release to follow.
OFFICE_LOCATION_CLAIM_PARAM = "onecore_auth.office_location_claim"
OFFICE_LOCATION_CLAIM_DEFAULT = "office_location"

# ir.config_parameter key: comma-separated e-mail domains whose Keycloak
# accounts may be created or re-linked automatically. Everybody else — the
# external contractors first of all — is still set up by hand. The default
# ("mimer.nu") lives in data/ir_config_parameter.xml and nowhere else: not in
# the post_init_hook (the module is already installed in prod and the hook
# never runs on an upgrade), and not as a fallback in code — an emptied
# parameter has to switch the feature off, not quietly back on.
AUTO_CREATE_DOMAINS_PARAM = "onecore_auth.auto_create_email_domains"

# local@domain, both parts non-empty, nothing that could smuggle in a second
# address or a display name.
_PLAIN_ADDRESS = re.compile(r"^[^@\s<>,;:\"']+@[^@\s<>,;:\"']+$")

NEW_USER_LANG = "sv_SE"
NEW_USER_TZ = "Europe/Stockholm"


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        # no_user_creation: on a miss stock would otherwise fall back to
        # signup(), which needs the public b2c signup switched on and creates
        # *portal* users from the template — useless for employees. With the
        # flag it just returns None and the miss is ours to handle.
        login = super(
            ResUsers, self.with_context(no_user_creation=True)
        )._auth_oauth_signin(provider, validation, params)
        # The caller may have asked for "no creation" itself; then a miss
        # stays a miss, exactly as stock defines that flag.
        if not login and not self.env.context.get("no_user_creation"):
            login = self._signin_unknown_subject(provider, validation, params)
        if login:
            self._sync_ad_office_location(login, validation)
        return login

    # ------------------------------------------------------------------
    # MIM-2010: a Keycloak subject no user carries yet
    # ------------------------------------------------------------------
    @api.model
    def _auto_create_email_domains(self):
        """Allowed domains, lowercased. Empty when the parameter is missing
        or blank: fail closed, so clearing it is how an admin switches
        auto-creation and re-linking off."""
        raw = self.env["ir.config_parameter"].sudo().get_param(AUTO_CREATE_DOMAINS_PARAM, "")
        return {
            domain.strip().lower().lstrip("@")
            for domain in (raw or "").split(",")
            if domain.strip()
        }

    @api.model
    def _email_from_claim(self, claim):
        """The claim as a normalised address, or False.

        The claim has to *be* one address, not merely contain one. Neither
        check is enough alone: email_normalize happily digs "x@mimer.nu" out
        of "Namn <x@mimer.nu>" and accepts "@mimer.nu" with an empty local
        part, while a hand-rolled split reads the claim "mimer.nu" as a domain
        of its own and lets it through the allowlist.
        """
        if not isinstance(claim, str):
            return False
        raw = claim.strip()
        if not _PLAIN_ADDRESS.match(raw):
            return False
        normalized = email_normalize(raw)
        if not normalized or normalized != raw.lower():
            return False
        return normalized

    @api.model
    def _signin_unknown_subject(self, provider, validation, params):
        """Login for a subject stock could not find, or None to deny.

        Re-links an existing active account with the same e-mail (a password
        user logging in via Keycloak for the first time, or an AD account that
        was recreated and got a new subject — what used to take SQL), or
        creates a new internal user. Only for the e-mail domains in
        AUTO_CREATE_DOMAINS_PARAM, and only for an enabled provider.

        Every refusal is logged with its reason. To the person it looks the
        same as before (oauth_error=3), but the pod log now says why instead
        of nothing.

        Does not leave the transaction broken: a failed INSERT without a
        savepoint would fail the controller's next query with
        InFailedSqlTransaction, from somewhere that points nowhere near here.
        Same reasoning as _sync_ad_office_location.
        """
        subject = validation.get("user_id")
        # Stock never checks ``enabled`` on the signin endpoint — the flag
        # only hides the button on the login page, so a disabled provider is
        # still reachable through a hand-built URL. Harmless in stock, where a
        # miss is simply denied; not here, where a miss can end in a re-link
        # by e-mail. Only providers somebody deliberately switched on get to
        # vouch for an address (in prod: Keycloak, nothing else).
        oauth_provider = self.env["auth.oauth.provider"].sudo().browse(provider).exists()
        if not oauth_provider or not oauth_provider.enabled:
            _logger.warning(
                "MIM-2010: OAuth login denied for subject %s: provider %s is "
                "not enabled, so its e-mail claim is not trusted.",
                subject,
                provider,
            )
            return None

        email = self._email_from_claim(validation.get("email"))
        if not email:
            _logger.warning(
                "MIM-2010: Keycloak login denied for subject %s: no usable "
                "email in Keycloak userinfo (got %r). Check that the client "
                "has the 'email' client scope.",
                subject,
                validation.get("email"),
            )
            return None
        domains = self._auto_create_email_domains()
        domain = email_domain_extract(email)
        if not domain or domain not in domains:
            _logger.warning(
                "MIM-2010: Keycloak login denied for %s: domain %r is not in "
                "%s (currently: %s). Accounts outside it are created by hand.",
                email,
                domain,
                AUTO_CREATE_DOMAINS_PARAM,
                ", ".join(sorted(domains)) or "empty, the feature is switched off",
            )
            return None

        try:
            with self.env.cr.savepoint():
                login = self._relink_or_create(provider, validation, params, email)
                # Flush here, in *this* environment. /auth_oauth/signin is
                # auth='none': the transaction's default environment has no
                # user at all, and that is the one the savepoint's exit (and
                # the controller's commit) would flush in. create() leaves the
                # avatar pending; computing it there makes ir.attachment ask
                # for the groups of an empty res.users() and raise — after the
                # user was created, so the login was denied and rolled back.
                # self.env is the superuser the controller switched to.
                self.env.flush_all()
                return login
        except (pg_errors.UniqueViolation, *PG_CONCURRENCY_EXCEPTIONS_TO_RETRY):
            # Two requests for the same first login (a double click, two
            # tabs): the other one won. Re-raising for Odoo's request retry
            # is not an option — auth_oauth's controller catches every
            # exception itself and turns it into oauth_error=2.
            login = self._login_created_concurrently(provider, subject)
            if login:
                _logger.info(
                    "MIM-2010: %s was created or re-linked by a concurrent "
                    "login; using that user",
                    email,
                )
                return login
            _logger.exception(
                "MIM-2010: could not re-link or create a user for Keycloak login %s",
                email,
            )
            return None
        except Exception:
            _logger.exception(
                "MIM-2010: could not re-link or create a user for Keycloak login %s",
                email,
            )
            return None

    @api.model
    def _login_created_concurrently(self, provider, subject):
        """Login of the user another request just linked to ``subject``, or None.

        In a transaction of its own: Odoo runs REPEATABLE READ, so the row
        the other request committed is invisible to this request's snapshot
        no matter how often it looks. The controller commits and then
        authenticates in a fresh transaction too, so returning the login is
        enough — both requests carry the same access token.
        """
        with self.env.registry.cursor() as cr:
            users = api.Environment(cr, SUPERUSER_ID, {})["res.users"].search(
                [("oauth_uid", "=", subject), ("oauth_provider_id", "=", provider)]
            )
            return users.login if len(users) == 1 else None

    @api.model
    def _relink_or_create(self, provider, validation, params, email):
        Users = self.sudo().with_context(active_test=False)
        # login, or the contact e-mail for accounts whose login differs.
        # Exact matches only — a near miss (a misspelt login) must surface as
        # a new account in the log, not be guessed at. =ilike is a LIKE, so
        # the address is escaped ("_" would otherwise match the "." in
        # somebody else's address), and the hits are compared again in Python
        # because the ORM may also apply unaccent.
        candidates = Users.search(
            ["|", ("login", "=", email), ("email", "=ilike", email_escape_char(email))]
        ).filtered(
            lambda user: user.login == email or email_normalize(user.email) == email
        )
        # Active accounts first: an archived leftover with the same address
        # must not hide the account the person actually uses.
        active = candidates.filtered("active")
        if len(active) > 1:
            _logger.warning(
                "MIM-2010: Keycloak login denied for %s: %s active users share "
                "that e-mail (ids %s). Not guessing; fix the duplicates.",
                email,
                len(active),
                active.ids,
            )
            return None
        if not active and candidates:
            _logger.warning(
                "MIM-2010: Keycloak login denied for %s: user %s is "
                "archived and is not reactivated automatically.",
                email,
                candidates.ids,
            )
            return None
        if active:
            if active.oauth_provider_id and active.oauth_provider_id.id != provider:
                # A stale subject from the *same* provider is the recreated
                # AD account and is overwritten below. A link to another
                # provider is somebody's deliberate setup; moving it is not
                # this code's call.
                _logger.warning(
                    "MIM-2010: Keycloak login denied for %s: user %s is linked "
                    "to another OAuth provider (%s). Re-link it by hand.",
                    email,
                    active.id,
                    active.oauth_provider_id.display_name,
                )
                return None
            values = {
                "oauth_provider_id": provider,
                "oauth_uid": validation["user_id"],
                "oauth_access_token": params["access_token"],
            }
            # Groups are only ever added, never removed or replaced: whatever
            # an admin gave the person by hand stays.
            missing = set(self._auto_relink_group_ids(active)) - set(active.all_group_ids.ids)
            if missing:
                values["group_ids"] = [(4, group_id) for group_id in sorted(missing)]
            active.write(values)
            _logger.info(
                "MIM-2010: re-linked existing user %s (%s) to Keycloak subject %s%s",
                active.login,
                active.name,
                validation["user_id"],
                ", added group ids %s" % sorted(missing) if missing else "",
            )
            return active.login

        values = self._generate_signup_values(provider, validation, params)
        values.update(self._auto_create_user_values(validation))
        values.update(
            {
                # A present-but-empty name claim would reach create() as None
                "name": (validation.get("name") or "").strip() or email,
                "login": email,
                "email": email,
                "group_ids": [(6, 0, self._auto_create_group_ids())],
            }
        )
        # no_reset_password: auth_signup's create() would otherwise send a
        # "set your password" invitation to somebody who logs in via Keycloak.
        user = Users.with_context(no_reset_password=True).create(values)
        # Name and e-mail on purpose: an account that *should* have matched an
        # existing one but did not (a misspelt login) shows up here as a
        # duplicate somebody can spot.
        _logger.info(
            "MIM-2010: auto-created Odoo user %s (%s) from Keycloak login",
            user.login,
            user.name,
        )
        return user.login

    # Two hooks other modules add to. Cooperative on purpose — getattr(super())
    # instead of a plain super() call: the modules that contribute
    # (onecore_maintenance_extension today) and this one do not depend on each
    # other, so their load order, and with it the MRO, is undefined. With a
    # plain override, whichever class happened to load *first* would be
    # shadowed by the other and silently skipped. Written this way every
    # definition runs, in either order.
    @api.model
    def _auto_create_group_ids(self):
        """Group ids for an auto-created user: Odoo's default access, i.e.
        what a user created by hand gets under Standardåtkomst."""
        parent = getattr(super(), "_auto_create_group_ids", None)
        group_ids = set(parent() if parent else [])
        return list(group_ids | set(self._default_groups().ids))

    @api.model
    def _auto_relink_group_ids(self, user):
        """Group ids an existing ``user`` must end up with when re-linked.

        Nothing from this module: a re-link is about the Keycloak link, and
        the account already has whatever access it was given. Other modules
        add what no employee can work without (cooperative, same as above).
        """
        parent = getattr(super(), "_auto_relink_group_ids", None)
        return list(parent(user) if parent else [])

    @api.model
    def _auto_create_user_values(self, validation):
        """Extra create() values for an auto-created user."""
        parent = getattr(super(), "_auto_create_user_values", None)
        values = dict(parent(validation) if parent else {})
        values.setdefault("tz", NEW_USER_TZ)
        if NEW_USER_LANG in dict(self.env["res.lang"].get_installed()):
            values.setdefault("lang", NEW_USER_LANG)
        return values

    # ------------------------------------------------------------------
    # MIM-2011: the AD department claim
    # ------------------------------------------------------------------
    @api.model
    def _sync_ad_office_location(self, login, validation):
        """Copy the AD department claim onto the user, when there is one.

        Stored stripped but otherwise as AD has it: AD is kept to one
        spelling per unit, and OrderingDepartmentService
        (onecore_maintenance_extension) copies the value onto requests
        verbatim, so the SSO path and the seed import must yield identical data.

        Never raises. The OAuth controller turns any exception here into a
        failed login (oauth_error=2), and a malformed claim must not lock
        anyone out.

        The savepoint is what makes that true for *database* errors, not just
        Python ones: a serialization failure, a deadlock or a
        constraint from another res.users override aborts the whole Postgres
        transaction, and swallowing the exception would then only move the
        failure to the controller's next query as InFailedSqlTransaction —
        locking the user out anyway, from somewhere that points nowhere near
        here. Same pattern as direct_lookup_service._safe_update_form_options.
        """
        # Soft dependency: the field belongs to onecore_maintenance_extension.
        # This module must stay installable without it.
        if "ad_office_location" not in self._fields:
            return
        try:
            claim = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(OFFICE_LOCATION_CLAIM_PARAM, OFFICE_LOCATION_CLAIM_DEFAULT)
            )
            if claim not in validation:
                return
            value = validation[claim]
            if value is None:
                return
            if not isinstance(value, str):
                # A multivalued protocol mapper delivers a list, and str()
                # would happily store "['Kundcenterenheten']" — no exception,
                # so the except below never fires, and every request the user
                # orders would then carry that literal as its department with
                # nothing in the log to explain why. The mapper is created by
                # hand in Keycloak and the spec says multivalued OFF, so this
                # is a configuration mistake worth shouting about.
                _logger.warning(
                    "MIM-2011: Keycloak claim %r for %s is %s, expected a "
                    "string. Check that the protocol mapper has multivalued "
                    "OFF. The AD unit was not written.",
                    claim,
                    login,
                    type(value).__name__,
                )
                return
            value = value.strip()
            if not value:
                return
            # savepoint: a database-level failure here (serialization,
            # deadlock, a constraint from another res.users override) aborts
            # the whole transaction. Swallowing it below without rolling back
            # would just move the failure to the controller's next query.
            with self.env.cr.savepoint():
                user = self.sudo().search([("login", "=", login)], limit=1)
                if user and user.ad_office_location != value:
                    user.write({"ad_office_location": value})
        except Exception:
            _logger.exception(
                "MIM-2011: could not sync AD unit from Keycloak for %s", login
            )
