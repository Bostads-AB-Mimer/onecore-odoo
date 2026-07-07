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
