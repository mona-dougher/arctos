"""Share side-comp entry numbers across a tournament or league.

Creates ``sidecomp_entry_numbers``, holding one number per player per scope
(``league:<url>`` or ``tournament:<url>``), and makes
``sidecomp_registrations.weapon`` nullable so a result logged for an
unregistered player can create an incomplete registration.

Revision ID: 0021_sidecomp_entry_number_scope
Revises: 0020_sidecomp_track_losses
Create Date: 2026-10-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021_sidecomp_entry_number_scope"
down_revision: Union[str, Sequence[str], None] = "0020_sidecomp_track_losses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        op.create_table(
            "sidecomp_entry_numbers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=111), nullable=False),
            sa.Column("player", sa.String(length=50), nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["player"], ["players.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope", "player", name="uq_sidecomp_entry_numbers_scope_player"),
            sa.UniqueConstraint("scope", "number", name="uq_sidecomp_entry_numbers_scope_number"),
        )
        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.alter_column("weapon", existing_type=sa.Integer(), nullable=True)
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        bind.exec_driver_sql(
            "DELETE FROM sidecompresults WHERE player IN (SELECT id FROM sidecomp_registrations WHERE weapon IS NULL)"
        )
        bind.exec_driver_sql("DELETE FROM sidecomp_registrations WHERE weapon IS NULL")
        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.alter_column("weapon", existing_type=sa.Integer(), nullable=False)
        op.drop_table("sidecomp_entry_numbers")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
