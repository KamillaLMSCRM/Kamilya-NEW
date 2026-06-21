"""${message}

Revision-ID: %(rev)s
Revises: %(down_revision)s
Create Date: %(created_at)s

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = %(rev)s
down_revision: Union[str, None] = %(down_revision)s
branch_labels: Union[str, Sequence[str], None] = %(branch_labels)s
depends_on: Union[str, Sequence[str], None] = %(depends_on)s


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
