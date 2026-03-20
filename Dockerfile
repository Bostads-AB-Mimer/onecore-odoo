# Official Odoo 19 image (Debian-based, runs as non-root 'odoo' user by default)
FROM odoo:19.0

# Switch to root to install additional Python packages
USER root

# faker: used for generating test data (onecore_maintenance_extension/tests/)
# filetype: used for file type detection in production code (onecore_maintenance_extension/models/utils/image_utils.py)
# --break-system-packages: required because the official image uses system-managed Python (PEP 668)
RUN pip3 install --break-system-packages faker filetype

# Switch back to the unprivileged odoo user for runtime security
USER odoo
