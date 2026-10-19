"""Add OAuth 2.0 provider tables for "Sign in with Arctos".

Third-party apps (e.g. arctos-recorder) need to act on a user's behalf
without ever seeing that user's password. Users register apps
(``oauth_clients``), authorize them through a consent page
(``oauth_authorization_codes``), and the apps receive revocable,
short-lived access tokens with rotating refresh tokens (``oauth_tokens``).

Revision ID: 0022_oauth_provider
Revises: 0021_sidecomp_entry_number_scope
Create Date: 2026-10-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022_oauth_provider"
down_revision: Union[str, Sequence[str], None] = "0021_sidecomp_entry_number_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("homepage_url", sa.String(length=500), nullable=True),
        sa.Column("redirect_uris", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(length=50), nullable=False),
        sa.Column("owner_type", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True)
    op.create_index("ix_oauth_clients_owner_id", "oauth_clients", ["owner_id"])

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("user_type", sa.String(length=10), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("code_challenge", sa.String(length=255), nullable=True),
        sa.Column("code_challenge_method", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=True),
        sa.Column("user_type", sa.String(length=10), nullable=True),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("access_token_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_in", sa.Integer(), nullable=False),
        sa.Column("access_token_revoked", sa.Boolean(), nullable=False),
        sa.Column("refresh_token_revoked", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_token_hash"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_oauth_tokens_client_id", "oauth_tokens", ["client_id"])
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_user_id", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_client_id", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_index("ix_oauth_clients_owner_id", table_name="oauth_clients")
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
