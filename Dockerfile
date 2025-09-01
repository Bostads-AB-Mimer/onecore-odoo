FROM bitnami/odoo:17.0.20240305-debian-12-r0

RUN /opt/bitnami/odoo/venv/bin/pip3 install python-dotenv "python-jose[cryptography]"
