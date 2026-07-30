"""add message timeline index

Revision ID: 20260730_02
Revises: 20260730_01
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260730_02"
down_revision: Union[str, Sequence[str], None] = "20260730_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_conversation_messages_timeline",
        "conversation_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_timeline",
        table_name="conversation_messages",
    )
