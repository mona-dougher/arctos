"""Add loss-tracking flags to sidecomps.

Adds ``track_losses``, ``track_chain_losses``, and ``track_break_losses``
booleans, all defaulting to ``False``. The chain/break flags apply only to
chain/breaking side competitions; ``track_losses`` applies to all other types.

Revision ID: 0020_sidecomp_track_losses
Revises: 0019_sidecomp_finalized
Create Date: 2026-10-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020_sidecomp_track_losses"
down_revision: Union[str, Sequence[str], None] = "0019_sidecomp_finalized"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("track_losses", "track_chain_losses", "track_break_losses")


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("sidecomps") as batch:
            for column_name in _COLUMNS:
                batch.add_column(
                    sa.Column(
                        column_name,
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("sidecomps") as batch:
            for column_name in _COLUMNS:
                batch.drop_column(column_name)
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
