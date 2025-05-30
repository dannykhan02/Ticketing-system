"""Add report_data, timestamp, and make ticket_type_id nullable in Report model

Revision ID: 306f621a87bb
Revises: 08cbd3b6d8b4
Create Date: 2025-05-25 19:38:41.390661

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '306f621a87bb'
down_revision = '08cbd3b6d8b4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('reports',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('ticket_type_id', sa.Integer(), nullable=True),
    sa.Column('total_tickets_sold', sa.Integer(), nullable=False),
    sa.Column('total_revenue', sa.Float(), nullable=False),
    sa.Column('report_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], ),
    sa.ForeignKeyConstraint(['ticket_type_id'], ['ticket_type.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reports_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reports_ticket_type_id'), ['ticket_type_id'], unique=False)

    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.drop_index('ix_report_event_id')
        batch_op.drop_index('ix_report_ticket_type_id')

    op.drop_table('report')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('report',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('ticket_type_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('total_tickets_sold', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('total_revenue', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name='report_event_id_fkey'),
    sa.ForeignKeyConstraint(['ticket_type_id'], ['ticket_type.id'], name='report_ticket_type_id_fkey'),
    sa.PrimaryKeyConstraint('id', name='report_pkey')
    )
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.create_index('ix_report_ticket_type_id', ['ticket_type_id'], unique=False)
        batch_op.create_index('ix_report_event_id', ['event_id'], unique=False)

    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reports_ticket_type_id'))
        batch_op.drop_index(batch_op.f('ix_reports_event_id'))

    op.drop_table('reports')
    # ### end Alembic commands ###
