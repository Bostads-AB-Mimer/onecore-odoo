# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re
import textwrap
from binascii import Error as binascii_error
from collections import defaultdict

from odoo import _, api, Command, fields, models, modules, tools
from odoo.exceptions import AccessError
from odoo.osv import expression
from odoo.tools import clean_context, groupby as tools_groupby, SQL

_logger = logging.getLogger(__name__)
_image_dataurl = re.compile(r'(data:image/[a-z]+?);base64,([a-z0-9+/\n]{3,}=*)\n*([\'"])(?: data-filename="([^"]*)")?', re.I)

class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    message_type = fields.Selection(
        selection_add=[
            ("from_tenant", "From tenant"),
            ("tenant_sms", "Sent to tenant by SMS"),
            ("tenant_mail", "Sent to tenant by email"),
            ("tenant_sms_error", "Sent to tenant by SMS, but sending failed"),
            ("tenant_mail_error", "Sent to tenant by email, but sending failed"),
        ],
        ondelete={
            "from_tenant": "set default",
            "tenant_sms": "set default",
            "tenant_mail": "set default",
            "tenant_sms_error": "set default",
            "tenant_mail_error": "set default",
        },
    )
    
    # send_to_tenant_as = fields.Selection("Skicka som", selection=[("sms", "SMS"), ("email", "E-post")])


    @api.model_create_multi
    def create(self, values_list):
        tracking_values_list = []
        _logger.info("-----------------------> Creating mail.message with values_list: %s", values_list)
        for values in values_list:
            if 'email_from' not in values:  # needed to compute reply_to
                _author_id, email_from = self.env['mail.thread']._message_compute_author(values.get('author_id'), email_from=None, raise_on_email=False)
                values['email_from'] = email_from
            if not values.get('message_id'):
                values['message_id'] = self._get_message_id(values)
            if 'reply_to' not in values:
                values['reply_to'] = self._get_reply_to(values)
            if 'record_name' not in values and 'default_record_name' not in self.env.context:
                values['record_name'] = self._get_record_name(values)

            if not values.get('attachment_ids'):
                values['attachment_ids'] = []
            # extract base64 images
            if 'body' in values:
                Attachments = self.env['ir.attachment'].with_context(clean_context(self._context))
                data_to_url = {}
                def base64_to_boundary(match):
                    key = match.group(2)
                    if not data_to_url.get(key):
                        name = match.group(4) if match.group(4) else 'image%s' % len(data_to_url)
                        try:
                            attachment = Attachments.create({
                                'name': name,
                                'datas': match.group(2),
                                'res_model': values.get('model'),
                                'res_id': values.get('res_id'),
                            })
                        except binascii_error:
                            _logger.warning("Impossible to create an attachment out of badly formated base64 embedded image. Image has been removed.")
                            return match.group(3)  # group(3) is the url ending single/double quote matched by the regexp
                        else:
                            attachment.generate_access_token()
                            values['attachment_ids'].append((4, attachment.id))
                            data_to_url[key] = ['/web/image/%s?access_token=%s' % (attachment.id, attachment.access_token), name]
                    return '%s%s alt="%s"' % (data_to_url[key][0], match.group(3), data_to_url[key][1])
                values['body'] = _image_dataurl.sub(base64_to_boundary, tools.ustr(values['body']))

            # delegate creation of tracking after the create as sudo to avoid access rights issues
            tracking_values_list.append(values.pop('tracking_value_ids', False))

        messages = super(OneCoreMailMessage, self).create(values_list)

        # link back attachments to records, to filter out attachments linked to
        # the same records as the message (considered as ok if message is ok)
        # and check rights on other documents
        attachments_tocheck = self.env['ir.attachment']
        doc_to_attachment_ids = defaultdict(set)
        if all(isinstance(command, int) or command[0] in (4, 6)
               for values in values_list
               for command in values['attachment_ids']):
            for values in values_list:
                message_attachment_ids = set()
                for command in values['attachment_ids']:
                    if isinstance(command, int):
                        message_attachment_ids.add(command)
                    elif command[0] == 6:
                        message_attachment_ids |= set(command[2])
                    else:  # command[0] == 4:
                        message_attachment_ids.add(command[1])
                if message_attachment_ids:
                    key = (values.get('model'), values.get('res_id'))
                    doc_to_attachment_ids[key] |= message_attachment_ids

            attachment_ids_all = {
                attachment_id
                for doc_attachment_ids in doc_to_attachment_ids
                for attachment_id in doc_attachment_ids
            }
            AttachmentSudo = self.env['ir.attachment'].sudo().with_prefetch(list(attachment_ids_all))
            for (model, res_id), doc_attachment_ids in doc_to_attachment_ids.items():
                # check only attachments belonging to another model, access already
                # checked on message for other attachments
                attachments_tocheck += AttachmentSudo.browse(doc_attachment_ids).filtered(
                    lambda att: att.res_model != model or att.res_id != res_id
                ).sudo(False)
        else:
            attachments_tocheck = messages.attachment_ids  # fallback on read if any unknown command
        if attachments_tocheck:
            attachments_tocheck.check('read')

        for message, values, tracking_values_cmd in zip(messages, values_list, tracking_values_list):
            if tracking_values_cmd:
                vals_lst = [dict(cmd[2], mail_message_id=message.id) for cmd in tracking_values_cmd if len(cmd) == 3 and cmd[0] == 0]
                other_cmd = [cmd for cmd in tracking_values_cmd if len(cmd) != 3 or cmd[0] != 0]
                if vals_lst:
                    self.env['mail.tracking.value'].sudo().create(vals_lst)
                if other_cmd:
                    message.sudo().write({'tracking_value_ids': tracking_values_cmd})

            if message.is_thread_message(values):
                message._invalidate_documents(values.get('model'), values.get('res_id'))

        return messages

    # def read(self, fields=None, load='_classic_read'):
    #     """ Override to explicitely call check_access_rule, that is not called
    #         by the ORM. It instead directly fetches ir.rules and apply them. """
    #     self.check_access_rule('read')
    #     return super(OneCoreMailMessage, self).read(fields=fields, load=load)

    # def fetch(self, field_names):
    #     # This freaky hack is aimed at reading data without the overhead of
    #     # checking that "self" is accessible, which is already done above in
    #     # methods read() and _search(). It reproduces the existing behavior
    #     # before the introduction of method fetch(), where the low-lever
    #     # reading method _read() did not enforce any actual permission.
    #     self = self.sudo()
    #     return super().fetch(field_names)

    # def write(self, vals):
    #     record_changed = 'model' in vals or 'res_id' in vals
    #     if record_changed or 'message_type' in vals:
    #         self._invalidate_documents()
    #     res = super(OneCoreMailMessage, self).write(vals)
    #     if vals.get('attachment_ids'):
    #         for mail in self:
    #             mail.attachment_ids.check(mode='read')
    #     if 'notification_ids' in vals or record_changed:
    #         self._invalidate_documents()
    #     return res

    # def unlink(self):
    #     # cascade-delete attachments that are directly attached to the message (should only happen
    #     # for mail.messages that act as parent for a standalone mail.mail record).
    #     # the cache of the related document doesn't need to be invalidate (see @_invalidate_documents)
    #     # because the unlink method invalidates the whole cache anyway
    #     if not self:
    #         return True
    #     self.check_access_rule('unlink')
    #     self.mapped('attachment_ids').filtered(
    #         lambda attach: attach.res_model == self._name and (attach.res_id in self.ids or attach.res_id == 0)
    #     ).unlink()
    #     messages_by_partner = defaultdict(lambda: self.env['mail.message'])
    #     partners_with_user = self.partner_ids.filtered('user_ids')
    #     for elem in self:
    #         for partner in elem.partner_ids & partners_with_user:
    #             messages_by_partner[partner] |= elem

    #     # Notify front-end of messages deletion for partners having a user
    #     if messages_by_partner:
    #         self.env['bus.bus']._sendmany([
    #             (partner, 'mail.message/delete', {'message_ids': messages.ids})
    #             for partner, messages in messages_by_partner.items()
    #         ])

    #     return super(OneCoreMailMessage, self).unlink()

    # def export_data(self, fields_to_export):
    #     if not self.env.is_admin():
    #         raise AccessError(_("Only administrators are allowed to export mail message"))

    #     return super(OneCoreMailMessage, self).export_data(fields_to_export)

    # # ------------------------------------------------------
    # # ACTIONS
    # # ----------------------------------------------------

    # def action_open_document(self):
    #     """ Opens the related record based on the model and ID """
    #     self.ensure_one()
    #     return {
    #         'res_id': self.res_id,
    #         'res_model': self.model,
    #         'target': 'current',
    #         'type': 'ir.actions.act_window',
    #         'view_mode': 'form',
    #     }

    # # ------------------------------------------------------
    # # DISCUSS API
    # # ------------------------------------------------------

    # @api.model
    # def mark_all_as_read(self, domain=None):
    #     # not really efficient method: it does one db request for the
    #     # search, and one for each message in the result set is_read to True in the
    #     # current notifications from the relation.
    #     notif_domain = [
    #         ('res_partner_id', '=', self.env.user.partner_id.id),
    #         ('is_read', '=', False)]
    #     if domain:
    #         messages = self.search(domain)
    #         messages.set_message_done()
    #         return messages.ids

    #     notifications = self.env['mail.notification'].sudo().search_fetch(notif_domain, ['mail_message_id'])
    #     notifications.write({'is_read': True})

    #     self.env['bus.bus']._sendone(self.env.user.partner_id, 'mail.message/mark_as_read', {
    #         'message_ids': notifications.mail_message_id.ids,
    #         'needaction_inbox_counter': self.env.user.partner_id._get_needaction_count(),
    #     })

    # def set_message_done(self):
    #     """ Remove the needaction from messages for the current partner. """
    #     partner_id = self.env.user.partner_id

    #     notifications = self.env['mail.notification'].sudo().search_fetch([
    #         ('mail_message_id', 'in', self.ids),
    #         ('res_partner_id', '=', partner_id.id),
    #         ('is_read', '=', False),
    #     ], ['mail_message_id'])

    #     if not notifications:
    #         return

    #     notifications.write({'is_read': True})

    #     # notifies changes in messages through the bus.
    #     self.env['bus.bus']._sendone(partner_id, 'mail.message/mark_as_read', {
    #         'message_ids': notifications.mail_message_id.ids,
    #         'needaction_inbox_counter': self.env.user.partner_id._get_needaction_count(),
    #     })

    # @api.model
    # def unstar_all(self):
    #     """ Unstar messages for the current partner. """
    #     partner = self.env.user.partner_id

    #     starred_messages = self.search([('starred_partner_ids', 'in', partner.id)])
    #     partner.starred_message_ids -= starred_messages
    #     self.env['bus.bus']._sendone(partner, 'mail.message/toggle_star', {
    #         'message_ids': starred_messages.ids,
    #         'starred': False,
    #     })

    # def toggle_message_starred(self):
    #     """ Toggle messages as (un)starred. Technically, the notifications related
    #         to uid are set to (un)starred.
    #     """
    #     # a user should always be able to star a message they can read
    #     self.check_access_rule('read')
    #     starred = not self.starred
    #     partner = self.env.user.partner_id
    #     if starred:
    #         partner.starred_message_ids |= self
    #     else:
    #         partner.starred_message_ids -= self

    #     self.env['bus.bus']._sendone(partner, 'mail.message/toggle_star', {
    #         'message_ids': [self.id],
    #         'starred': starred,
    #     })

    # def _message_reaction(self, content, action):
    #     self.ensure_one()
    #     partner, guest = self.env["res.partner"]._get_current_persona()
    #     # search for existing reaction
    #     domain = [
    #         ("message_id", "=", self.id),
    #         ("partner_id", "=", partner.id),
    #         ("guest_id", "=", guest.id),
    #         ("content", "=", content),
    #     ]
    #     reaction = self.env["mail.message.reaction"].search(domain)
    #     # create/unlink reaction if necessary
    #     if action == "add" and not reaction:
    #         create_values = {
    #             "message_id": self.id,
    #             "content": content,
    #             "partner_id": partner.id,
    #             "guest_id": guest.id,
    #         }
    #         self.env["mail.message.reaction"].create(create_values)
    #     if action == "remove" and reaction:
    #         reaction.unlink()
    #     # format result
    #     group_domain = [("message_id", "=", self.id), ("content", "=", content)]
    #     count = self.env["mail.message.reaction"].search_count(group_domain)
    #     group_command = "ADD" if count > 0 else "DELETE"
    #     personas = [("ADD" if action == "add" else "DELETE", {"id": guest.id if guest else partner.id, "type": "guest" if guest else "partner"})] if guest or partner else []
    #     group_values = {
    #         "content": content,
    #         "count": count,
    #         "personas": personas,
    #         "message": {"id": self.id},
    #     }
    #     payload = {"Message": {"id": self.id, "reactions": [(group_command, group_values)]}}
    #     self.env["bus.bus"]._sendone(self._bus_notification_target(), "mail.record/insert", payload)

    # # ------------------------------------------------------
    # # MESSAGE READ / FETCH / FAILURE API
    # # ------------------------------------------------------

    # def _message_format(self, fnames, format_reply=True):
    #     """Reads values from messages and formats them for the web client."""
    #     vals_list = self._read_format(fnames)
    #     thread_ids_by_model_name = defaultdict(set)
    #     for message in self:
    #         if message.model and message.res_id:
    #             thread_ids_by_model_name[message.model].add(message.res_id)
    #     for vals in vals_list:
    #         message_sudo = self.browse(vals['id']).sudo().with_prefetch(self.ids)
    #         author = False
    #         if message_sudo.author_guest_id:
    #             author = {
    #                 'id': message_sudo.author_guest_id.id,
    #                 'name': message_sudo.author_guest_id.name,
    #                 'type': "guest",
    #             }
    #         elif message_sudo.author_id:
    #             author = message_sudo.author_id.mail_partner_format({'id': True, 'name': True, 'is_company': True, 'user': {"id": True}}).get(message_sudo.author_id)
    #         record_sudo = False
    #         if message_sudo.model and message_sudo.res_id:
    #             record_sudo = self.env[message_sudo.model].browse(message_sudo.res_id).sudo()
    #             record_name = record_sudo.with_prefetch(thread_ids_by_model_name[message_sudo.model]).display_name
    #             default_subject = record_name
    #             if hasattr(record_sudo, '_message_compute_subject'):
    #                 default_subject = record_sudo._message_compute_subject()
    #         else:
    #             record_name = False
    #             default_subject = False
    #         reactions_per_content = defaultdict(self.env['mail.message.reaction'].sudo().browse)
    #         for reaction in message_sudo.reaction_ids:
    #             reactions_per_content[reaction.content] |= reaction
    #         reaction_groups = [{
    #             'content': content,
    #             'count': len(reactions),
    #             'personas': [{'id': guest.id, 'name': guest.name, 'type': "guest"} for guest in reactions.guest_id] + [{'id': partner.id, 'name': partner.name, 'type': "partner"} for partner in reactions.partner_id],
    #             'message': {'id': message_sudo.id},
    #         } for content, reactions in reactions_per_content.items()]
    #         allowed_tracking_ids = message_sudo.tracking_value_ids.filtered(lambda tracking: not tracking.field_groups or self.env.is_superuser() or self.user_has_groups(tracking.field_groups))
    #         displayed_tracking_ids = allowed_tracking_ids
    #         if record_sudo and hasattr(record_sudo, '_track_filter_for_display'):
    #             displayed_tracking_ids = record_sudo._track_filter_for_display(displayed_tracking_ids)
    #         vals.update(message_sudo._message_format_extras(format_reply))
    #         vals.update({
    #             'author': author,
    #             'default_subject': default_subject,
    #             'notifications': message_sudo.notification_ids._filtered_for_web_client()._notification_format(),
    #             'attachments': sorted(message_sudo.attachment_ids._attachment_format(), key=lambda a: a["id"]),
    #             'trackingValues': displayed_tracking_ids._tracking_value_format(),
    #             'linkPreviews': message_sudo.link_preview_ids._link_preview_format(),
    #             'reactions': reaction_groups,
    #             'pinned_at': message_sudo.pinned_at,
    #             'record_name': record_name,
    #             'create_date': message_sudo.create_date,
    #             'write_date': message_sudo.write_date,
    #         })
    #     return vals_list

    # def _message_format_extras(self, format_reply):
    #     self.ensure_one()
    #     return {}

    # @api.model
    # def _message_fetch(self, domain, search_term=None, before=None, after=None, around=None, limit=30):
    #     res = {}
    #     if search_term:
    #         # we replace every space by a % to avoid hard spacing matching
    #         search_term = search_term.replace(" ", "%")
    #         domain = expression.AND([domain, expression.OR([
    #             # sudo: access to attachment is allowed if you have access to the parent model
    #             [("attachment_ids", "in", self.env["ir.attachment"].sudo()._search([("name", "ilike", search_term)]))],
    #             [("body", "ilike", search_term)],
    #             [("subject", "ilike", search_term)],
    #             [("subtype_id.description", "ilike", search_term)],
    #         ])])
    #         domain = expression.AND([domain, [("message_type", "not in", ["user_notification", "notification"])]])
    #         res["count"] = self.search_count(domain)
    #     if around:
    #         messages_before = self.search(domain=[*domain, ('id', '<=', around)], limit=limit // 2, order="id DESC")
    #         messages_after = self.search(domain=[*domain, ('id', '>', around)], limit=limit // 2, order='id ASC')
    #         return {**res, "messages": (messages_after + messages_before).sorted('id', reverse=True)}
    #     if before:
    #         domain = expression.AND([domain, [('id', '<', before)]])
    #     if after:
    #         domain = expression.AND([domain, [('id', '>', after)]])
    #     res["messages"] = self.search(domain, limit=limit, order='id ASC' if after else 'id DESC')
    #     if after:
    #         res["messages"] = res["messages"].sorted('id', reverse=True)
    #     return res

    # def message_format(self, format_reply=True, msg_vals=None):
    #     """ Get the message values in the format for web client. Since message
    #     values can be broadcasted, computed fields MUST NOT BE READ and
    #     broadcasted.

    #     :param msg_vals: dictionary of values used to create the message. If
    #       given it may be used to access values related to ``message`` without
    #       accessing it directly. It lessens query count in some optimized use
    #       cases by avoiding access message content in db;

    #     :returns list(dict).
    #          Example :
    #             {
    #                 'body': HTML content of the message
    #                 'model': u'res.partner',
    #                 'record_name': u'Agrolait',
    #                 'attachments': [
    #                     {
    #                         'file_type_icon': u'webimage',
    #                         'id': 45,
    #                         'name': u'sample.png',
    #                         'filename': u'sample.png'
    #                     }
    #                 ],
    #                 'needaction_partner_ids': [], # list of partner ids
    #                 'res_id': 7,
    #                 'trackingValues': [
    #                     {
    #                         'changedField': "Customer",
    #                         'id': 2965,
    #                         'fieldName': 'partner_id',
    #                         'fieldType': 'char',
    #                         'newValue': {
    #                             'currencyId': "",
    #                             'value': "Axelor",
    #                         ],
    #                         'oldValue': {
    #                             'currencyId': "",
    #                             'value': "",
    #                         ],
    #                     }
    #                 ],
    #                 'author_id': (3, u'Administrator'),
    #                 'email_from': 'sacha@pokemon.com' # email address or False
    #                 'subtype_id': (1, u'Discussions'),
    #                 'date': '2015-06-30 08:22:33',
    #                 'partner_ids': [[7, "Sacha Du Bourg-Palette"]], # list of partner convert_to_read
    #                 'message_type': u'comment',
    #                 'id': 59,
    #                 'subject': False
    #                 'is_note': True # only if the message is a note (subtype == note)
    #                 'is_discussion': False # only if the message is a discussion (subtype == discussion)
    #                 'parentMessage': {...}, # formatted message that this message is a reply to. Only present if format_reply is True
    #             }
    #     """
    #     self.check_access_rule('read')
    #     vals_list = self._message_format(self._get_message_format_fields(), format_reply=format_reply)

    #     com_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_comment')
    #     note_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')

    #     # fetch scheduled notifications once, only if msg_vals is not given to
    #     # avoid useless queries when notifying Inbox right after a message_post
    #     scheduled_dt_by_msg_id = {}
    #     if msg_vals:
    #         scheduled_dt_by_msg_id = {msg.id: msg_vals.get('scheduled_date') for msg in self}
    #     elif self:
    #         schedulers = self.env['mail.message.schedule'].sudo().search([
    #             ('mail_message_id', 'in', self.ids)
    #         ])
    #         for scheduler in schedulers:
    #             scheduled_dt_by_msg_id[scheduler.mail_message_id.id] = scheduler.scheduled_datetime

    #     for vals in vals_list:
    #         message_sudo = self.browse(vals['id']).sudo().with_prefetch(self.ids)
    #         notifs = message_sudo.notification_ids.filtered(lambda n: n.res_partner_id)
    #         vals.update({
    #             'needaction_partner_ids': notifs.filtered(lambda n: not n.is_read).res_partner_id.ids,
    #             'history_partner_ids': notifs.filtered(lambda n: n.is_read).res_partner_id.ids,
    #             'is_note': message_sudo.subtype_id.id == note_id,
    #             'is_discussion': message_sudo.subtype_id.id == com_id,
    #             'subtype_description': message_sudo.subtype_id.description,
    #             'recipients': [{'id': p.id, 'name': p.name, 'type': "partner"} for p in message_sudo.partner_ids],
    #             'scheduledDatetime': scheduled_dt_by_msg_id.get(vals['id'], False),
    #         })
    #         if vals['model'] and self.env[vals['model']]._original_module:
    #             vals['module_icon'] = modules.module.get_module_icon(self.env[vals['model']]._original_module)
    #     return vals_list

    # @api.model
    # def _message_format_personalized_prepare(self, messages_formatted, partner_ids=None):
    #     """ Prepare message to be personalized by partner.

    #     This method add partner information in batch to the messages so that the
    #     messages could be personalized for each partner by using
    #     _message_format_personalize with no or a limited number of queries.

    #     For example, it gathers all followers of the record related to the messages
    #     in one go (or limit it to the partner given in parameter), so that the method
    #     _message_format_personalize could then personalize each message for each partner.

    #     Note that followers for message related to discuss.channel are not fetched.

    #     :param list messages_formatted: list of message formatted using the method
    #         message_format
    #     :param list partner_ids: (optional) limit value computation to the partners
    #         of the given list; if not set, all partners are considered (all partners
    #         following each record will be included in follower_id_by_partner_id).

    #     :return: list of messages_formatted with added value:
    #         'follower_id_by_partner_id': dict partner_id -> follower_id of the record
    #     """
    #     domain = expression.OR([
    #         [('res_model', '=', model), ('res_id', 'in', list({value['res_id'] for value in values}))]
    #         for model, values in tools_groupby(
    #             (vals for vals in messages_formatted
    #              if vals.get("res_id") and vals.get("model") not in {None, False, '', 'discuss.channel'}),
    #             key=lambda r: r["model"]
    #         )
    #     ])
    #     if partner_ids:
    #         domain = expression.AND([domain, [('partner_id', 'in', partner_ids)]])
    #     records_followed = self.env['mail.followers'].sudo().search(domain)
    #     followers_by_record_ref = (
    #         {(res_model, res_id): {value['partner_id'][0]: value['id'] for value in values}
    #          for (res_model, res_id), values in tools_groupby(
    #             records_followed.read(['res_id', 'res_model', 'partner_id']),
    #             key=lambda r: (r["res_model"], r['res_id'])
    #         )})
    #     for vals in messages_formatted:
    #         vals['follower_id_by_partner_id'] = followers_by_record_ref.get((vals['model'], vals['res_id']), dict())
    #     return messages_formatted

    # def _message_format_personalize(self, partner_id, messages_formatted=None, format_reply=True, msg_vals=None):
    #     """ Personalize the messages for the partner.

    #     :param integer partner_id: id of the partner to personalize the messages for
    #     :param list messages_formatted: (optional) list of message formatted using
    #         the method _message_format_personalized_prepare.
    #         If not provided message_format is called on self with the 2 next parameters
    #         to format the messages and then the messages are personalized.
    #     :param bool format_reply: (optional) see method message_format
    #     :param dict msg_vals: (optional) see method message_format
    #     :return: list of messages_formatted personalized for the partner
    #     """
    #     if not messages_formatted:
    #         messages_formatted = self.message_format(format_reply=format_reply, msg_vals=msg_vals)
    #         self._message_format_personalized_prepare(messages_formatted, [partner_id])
    #     for vals in messages_formatted:
    #         # set value for user being a follower, fallback to False if not prepared
    #         follower_id_by_pid = vals.pop('follower_id_by_partner_id', {})
    #         vals['user_follower_id'] = follower_id_by_pid.get(partner_id, False)
    #     return messages_formatted

    # def _get_message_format_fields(self):
    #     return [
    #         'id', 'body', 'date', 'email_from',  # base message fields
    #         'message_type', 'subtype_id', 'subject',  # message specific
    #         'model', 'res_id', 'record_name',  # document related
    #         'starred_partner_ids',  # list of partner ids for whom the message is starred
    #     ]

    # def _message_notification_format(self):
    #     """Returns the current messages and their corresponding notifications in
    #     the format expected by the web client.

    #     Notifications hold the information about each recipient of a message: if
    #     the message was successfully sent or if an exception or bounce occurred.
    #     """
    #     return [{
    #         'author': {'id': message.author_id.id, 'type': "partner"} if message.author_id else False,
    #         'id': message.id,
    #         'res_id': message.res_id,
    #         'model': message.model,
    #         'res_model_name': message.env['ir.model']._get(message.model).display_name,
    #         'date': message.date,
    #         'message_type': message.message_type,
    #         'body': message.body,
    #         'notifications': message.notification_ids._filtered_for_web_client()._notification_format(),
    #     } for message in self]

    # def _notify_message_notification_update(self):
    #     """Send bus notifications to update status of notifications in the web
    #     client. Purpose is to send the updated status per author."""
    #     messages = self.env['mail.message']
    #     for message in self:
    #         # Check if user has access to the record before displaying a notification about it.
    #         # In case the user switches from one company to another, it might happen that they don't
    #         # have access to the record related to the notification. In this case, we skip it.
    #         # YTI FIXME: check allowed_company_ids if necessary
    #         if message.model and message.res_id:
    #             record = self.env[message.model].browse(message.res_id)
    #             try:
    #                 record.check_access_rights('read')
    #                 record.check_access_rule('read')
    #             except AccessError:
    #                 continue
    #             else:
    #                 messages += message
    #     messages_per_partner = defaultdict(lambda: self.env['mail.message'])
    #     for message in messages:
    #         if not self.env.user._is_public():
    #             messages_per_partner[self.env.user.partner_id] |= message
    #         if message.author_id and not any(user._is_public() for user in message.author_id.with_context(active_test=False).user_ids):
    #             messages_per_partner[message.author_id] |= message
    #     updates = [
    #         (partner, 'mail.message/notification_update', {'elements': messages._message_notification_format()})
    #         for partner, messages in messages_per_partner.items()
    #     ]
    #     self.env['bus.bus']._sendmany(updates)

    # def _bus_notification_target(self):
    #     self.ensure_one()
    #     return self.env.user.partner_id

    # # ------------------------------------------------------
    # # TOOLS
    # # ------------------------------------------------------

    # def _cleanup_side_records(self):
    #     """ Clean related data: notifications, stars, ... to avoid lingering
    #     notifications / unreachable counters with void messages notably. """
    #     self.write({
    #         'starred_partner_ids': [(5, 0, 0)],
    #         'notification_ids': [(5, 0, 0)],
    #     })

    # def _filter_empty(self):
    #     """ Return subset of "void" messages """
    #     return self.filtered(
    #         lambda msg:
    #             (not msg.body or tools.is_html_empty(msg.body)) and
    #             (not msg.subtype_id or not msg.subtype_id.description) and
    #             not msg.attachment_ids and
    #             not msg.tracking_value_ids
    #     )

    # def _get_message_preview(self, max_char=190):
    #     """Returns an unformatted version of the message body. Unless `max_char=0` is passed,
    #     output will be capped at max_char characters with a ' [...]' suffix if applicable.
    #     Default `max_char` is the longest known mail client preview length (Outlook 2013)."""
    #     self.ensure_one()

    #     plaintext_ct = tools.html_to_inner_content(self.body)
    #     return textwrap.shorten(plaintext_ct, max_char) if max_char else plaintext_ct

    # @api.model
    # def _get_record_name(self, values):
    #     """ Return the related document name, using display_name. It is done using
    #         SUPERUSER_ID, to be sure to have the record name correctly stored. """
    #     model = values.get('model', self.env.context.get('default_model'))
    #     res_id = values.get('res_id', self.env.context.get('default_res_id'))
    #     if not model or not res_id or model not in self.env:
    #         return False
    #     return self.env[model].sudo().browse(res_id).display_name

    # @api.model
    # def _get_reply_to(self, values):
    #     """ Return a specific reply_to for the document """
    #     model = values.get('model', self._context.get('default_model'))
    #     res_id = values.get('res_id', self._context.get('default_res_id')) or False
    #     email_from = values.get('email_from')
    #     message_type = values.get('message_type')
    #     records = None
    #     if self.is_thread_message({'model': model, 'res_id': res_id, 'message_type': message_type}):
    #         records = self.env[model].browse([res_id])
    #     else:
    #         records = self.env[model] if model else self.env['mail.thread']
    #     return records._notify_get_reply_to(default=email_from)[res_id]

    # @api.model
    # def _get_message_id(self, values):
    #     if values.get('reply_to_force_new', False) is True:
    #         message_id = tools.generate_tracking_message_id('reply_to')
    #     elif self.is_thread_message(values):
    #         message_id = tools.generate_tracking_message_id('%(res_id)s-%(model)s' % values)
    #     else:
    #         message_id = tools.generate_tracking_message_id('private')
    #     return message_id

    # def is_thread_message(self, vals=None):
    #     if vals:
    #         res_id = vals.get('res_id')
    #         model = vals.get('model')
    #         message_type = vals.get('message_type')
    #     else:
    #         self.ensure_one()
    #         res_id = self.res_id
    #         model = self.model
    #         message_type = self.message_type
    #     return res_id and model and message_type != 'user_notification'

    # def _invalidate_documents(self, model=None, res_id=None):
    #     """ Invalidate the cache of the documents followed by ``self``. """
    #     fnames = ['message_ids', 'message_needaction', 'message_needaction_counter']
    #     self.flush_recordset(['model', 'res_id'])
    #     for record in self:
    #         model = model or record.model
    #         res_id = res_id or record.res_id
    #         if model in self.pool and issubclass(self.pool[model], self.pool['mail.thread']):
    #             self.env[model].browse(res_id).invalidate_recordset(fnames)

    # def _get_search_domain_share(self):
    #     return ['&', '&', ('is_internal', '=', False), ('subtype_id', '!=', False), ('subtype_id.internal', '=', False)]
