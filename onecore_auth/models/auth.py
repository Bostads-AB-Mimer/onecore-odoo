import requests
from odoo import models, fields

class OnecoreAuth(models.Model):
    _name = 'onecore.auth'
    _description = 'ONECore Auth'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    token = fields.Char(string='Token', required=True)

    def get_token(self):
        token = self.search([('user_id', '=', self.env.user.id)]).token
        if not token:
            token = self.refresh_token()
        return token

    def set_token(self, new_token):
        record = self.search([('user_id', '=', self.env.user.id)])
        if record:
            record.write({'token': new_token})
        else:
            self.create({'user_id': self.env.user.id, 'token': new_token})

    def refresh_token(self):
        body = {
            'username': self.env['ir.config_parameter'].get_param('onecore_body_username', ''),
            'password': self.env['ir.config_parameter'].get_param('onecore_body_password', ''),
        }
        response = requests.post(
            self.env['ir.config_parameter'].get_param('onecore_generate_token_url', ''),
            json=body
        )
        if response.status_code == 200:
            new_token = response.json().get('token')
            self.set_token(new_token)
            return new_token
        else:
            response.raise_for_status()

    def onecore_request(self, url, params):
        token = self.get_token()
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(url, params=params, headers=headers)

        if response.status_code == 401:
            token = self.refresh_token()
            headers['Authorization'] = f'Bearer {token}'
            response = requests.post(url, params=params, headers=headers)

            if response.status_code == 401:
                _logger.error('Unauthorized request after token refresh: %s', response.text)
                response.raise_for_status()

        return response