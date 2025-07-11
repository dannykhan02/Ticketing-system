"""adds nullable

Revision ID: 1a35a212ede0
Revises: 839d0028aec6
Create Date: 2025-07-04 12:15:46.652778

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a35a212ede0'
down_revision = '839d0028aec6'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.alter_column('currency_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.alter_column('currency_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    # ### end Alembic commands ###
