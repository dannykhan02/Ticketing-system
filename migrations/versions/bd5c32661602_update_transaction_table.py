"""update transaction table

Revision ID: bd5c32661602
Revises: 47d952d071d4
Create Date: 2025-03-10 15:37:18.029753

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd5c32661602'
down_revision = '47d952d071d4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.alter_column('payment_status',
               existing_type=sa.VARCHAR(length=9),
               type_=sa.Enum('PENDING', 'COMPLETED', 'FAILED', 'REFUNDED', 'CANCELED', 'CHARGEBACK', 'ON_HOLD', name='paymentstatus'),
               existing_nullable=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.alter_column('payment_status',
               existing_type=sa.Enum('PENDING', 'COMPLETED', 'FAILED', 'REFUNDED', 'CANCELED', 'CHARGEBACK', 'ON_HOLD', name='paymentstatus'),
               type_=sa.VARCHAR(length=9),
               existing_nullable=False)

    # ### end Alembic commands ###
