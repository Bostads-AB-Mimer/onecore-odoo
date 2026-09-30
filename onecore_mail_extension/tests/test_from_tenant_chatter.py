import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

# Runs in the browser against the rendered chatter, because the part of
# MIM-2040 the tenant-message label is about lives in OWL patches: a mail
# upgrade that renames o-mail-Message-author, authorAvatarUrl or
# hasAuthorClickable would silently bring "Odoo" back as the sender while every
# Python test stayed green. Odoo skips browser tests where no Chrome is found.
CHATTER_CHECK = r"""
(async () => {
  const expected = %(expected)s;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const find = (body) =>
    [...document.querySelectorAll(".o-mail-Message")].find((m) =>
      (m.querySelector(".o-mail-Message-body") || {}).innerText?.includes(body)
    );
  for (let i = 0; i < 60 && !expected.every((e) => find(e.body)); i++) {
    await sleep(250);
  }
  const problems = [];
  for (const e of expected) {
    const m = find(e.body);
    if (!m) {
      problems.push(`message "${e.body}" not rendered`);
      continue;
    }
    const author = m.querySelector(".o-mail-Message-author")?.innerText.trim();
    const badge = Boolean(m.querySelector(".o-mimer-tenant-badge"));
    const header = m.querySelector(".o-mail-Message-header")?.innerText || "";
    const avatar = m.querySelector(".o-mail-Message-avatar")?.getAttribute("src") || "";
    const clickable = m
      .querySelector(".o-mail-Message-avatarContainer")
      ?.classList.contains("cursor-pointer");
    const actual = {
      author,
      badge,
      viaMyPages: header.includes("(via Mina sidor)"),
      defaultAvatar: avatar.endsWith("/mail/static/src/img/smiley/avatar.jpg"),
      clickable: Boolean(clickable),
    };
    for (const key of Object.keys(e.want)) {
      if (actual[key] !== e.want[key]) {
        problems.push(`"${e.body}": ${key} is ${actual[key]}, expected ${e.want[key]}`);
      }
    }
  }
  if (problems.length) {
    console.error(problems.join("; "));
  } else {
    console.log("test successful");
  }
})();
"""


@tagged("onecore", "post_install", "-at_install")
class TestFromTenantChatter(HttpCase):
    """MIM-2040 (extra): a Mina sidor message shows the tenant, never "Odoo",
    and is always visibly marked as the tenant's."""

    def setUp(self):
        super().setUp()
        groups = [
            self.env.ref("base.group_user").id,
            self.env.ref("maintenance.group_equipment_manager").id,
        ]
        # An invented login: nothing may depend on which account integrates.
        self.integration_user = self.env["res.users"].create(
            {
                "name": "Some Integration",
                "login": "chatter_test_integration",
                "group_ids": [(6, 0, groups)],
            }
        )
        self.admin = self.env.ref("base.user_admin")
        self.admin.tour_enabled = False
        self.category_id = self.env.ref("onecore_maintenance_extension.category_1").id

    def _request(self, tenant_name=None):
        values = {
            "name": "Trasig kran",
            "maintenance_request_category_id": self.category_id,
            "space_caption": "Lägenhet",
            "hidden_from_my_pages": False,
        }
        if tenant_name:
            values["tenant_id"] = (
                self.env["maintenance.tenant"]
                .create(
                    {
                        "name": tenant_name,
                        "contact_code": "P900010",
                        "contact_key": "_CHATTERKEY",
                    }
                )
                .id
            )
        return self.env["maintenance.request"].create(values)

    def _post_as_mina_sidor(self, request, body):
        request.with_user(self.integration_user).message_post(
            body=body, message_type="from_tenant", body_is_html=True
        )

    def _check(self, request, expected):
        self.browser_js(
            f"/odoo/maintenance.request/{request.id}",
            CHATTER_CHECK % {"expected": json.dumps(expected)},
            login="admin",
            timeout=90,
        )

    def test_tenant_message_shows_the_tenant_marked_as_tenant(self):
        request = self._request("Anna Andersson")
        self._post_as_mina_sidor(request, "Kranen droppar")
        request.with_user(self.admin).message_post(
            body="Intern notering", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        with patch.object(
            type(self.env["mail.message"]), "_log_my_pages_message", autospec=True
        ):
            request.with_user(self.admin).message_post(
                body="Svar till hyresgast", message_type="tenant_my_pages"
            )
        self._check(
            request,
            [
                {
                    "body": "Kranen droppar",
                    "want": {
                        "author": "Anna Andersson",
                        "badge": True,
                        "viaMyPages": True,
                        "defaultAvatar": True,
                        "clickable": False,
                    },
                },
                {
                    "body": "Intern notering",
                    "want": {
                        "author": self.admin.name,
                        "badge": False,
                        "defaultAvatar": False,
                        "clickable": True,
                    },
                },
                {
                    "body": "Svar till hyresgast",
                    "want": {"author": self.admin.name, "badge": False, "clickable": True},
                },
            ],
        )

    def test_tenant_message_without_a_name_reads_hyresgast(self):
        request = self._request()
        self._post_as_mina_sidor(request, "Utan namn")
        self._check(
            request,
            [
                {
                    "body": "Utan namn",
                    "want": {
                        "author": "Hyresgäst",
                        "badge": False,
                        "viaMyPages": True,
                        "defaultAvatar": True,
                        "clickable": False,
                    },
                }
            ],
        )
