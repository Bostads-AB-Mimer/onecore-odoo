from odoo import http
from odoo.http import request
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.mail.controllers.thread import ThreadController


class OneCoreThreadController(ThreadController):
    @http.route(
        "/mail/thread/pinned_messages", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_pinned_messages(self, thread_model, thread_id):
        # Loads every pinned message on the thread for the chatter "Fästa"
        # section, independent of the 30-message pagination window used by
        # /mail/thread/messages (MIM-1301 review). Mirrors that route's access
        # check and Store serialization; the fetch itself lives in
        # mail.message._fetch_pinned_messages.
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        messages = request.env["mail.message"]._fetch_pinned_messages(thread)
        return {
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }

    @http.route(
        "/onecore/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user"
    )
    def onecore_mail_thread_messages(
        self, thread_model, thread_id, fetch_params=None, onecore_log_category=None
    ):
        # The händelselogg filter (MIM-1956) needs the category to reach
        # _message_fetch, but there is no clean OWL hook that adds a key INSIDE
        # fetch_params, and Thread.rpcParams cannot be used — it is also spread
        # into /mail/message/update_content, where an unknown kwarg raises. So
        # the category travels top-level to this route, which otherwise mirrors
        # base /mail/thread/messages (mail/controllers/thread.py) exactly: same
        # access check, same set_message_done, same Store serialization. Keep it
        # in step with base on Odoo upgrades.
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        MailMessage = request.env["mail.message"]
        res = MailMessage._message_fetch(
            domain=None,
            thread=thread,
            # onecore_log_category comes straight from the browser, so it is
            # validated against the field's selection here rather than letting
            # _onecore_log_category_domain's ValueError become a 500 plus a
            # traceback. Unknown values are dropped -> unfiltered log.
            onecore_log_category=MailMessage._onecore_sanitize_log_category(
                onecore_log_category
            ),
            **(fetch_params or {}),
        )
        messages = res.pop("messages")
        if not request.env.user._is_public():
            # Marks only the FETCHED subset as read, so under an active filter
            # the needs-action counter drops by the messages of that category
            # only. Base /mail/thread/messages has the same property with
            # pagination (it only ever marks the current 30), so this is a
            # difference in degree, not in kind — noted so nobody debugs a
            # stubborn unread counter cold.
            messages.set_message_done()
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }
