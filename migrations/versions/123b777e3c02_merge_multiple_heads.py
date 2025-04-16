"""Merge multiple heads

Revision ID: 123b777e3c02
Revises: e5bb80317a8d, 13f5604f2288
Create Date: 2025-04-16 22:41:58.272265

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '123b777e3c02'
down_revision = ('e5bb80317a8d', '13f5604f2288')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
