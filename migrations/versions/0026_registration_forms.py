"""Store optional response-sheet requirements on the shared registration config.

Existing events and leagues retain their registration behavior because all
four fields default to null. Response contents are not stored.

Revision ID: 0026_registration_forms
Revises: 0025_player_profile_details
Create Date: 2026-10-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0026_registration_forms"
down_revision = "0025_player_profile_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registrable_configs", sa.Column("registration_form_url", sa.String(500), nullable=True))
    op.add_column("registrable_configs", sa.Column("registration_form_sheet_id", sa.String(255), nullable=True))
    op.add_column("registrable_configs", sa.Column("registration_form_sheet_gid", sa.Integer(), nullable=True))
    op.add_column("registrable_configs", sa.Column("registration_form_username_column", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("registrable_configs", "registration_form_username_column")
    op.drop_column("registrable_configs", "registration_form_sheet_gid")
    op.drop_column("registrable_configs", "registration_form_sheet_id")
    op.drop_column("registrable_configs", "registration_form_url")
