"""Remove column string size restrinctions in emails, they gives no benefits and crash on real world email

Revision ID: 3b5bb2cefa6d
Revises: 5adf6d88ab56
Create Date: 2013-09-18 14:59:19.452383

"""

# revision identifiers, used by Alembic.
revision = '3b5bb2cefa6d'
down_revision = '5adf6d88ab56'

from alembic import context, op
import sqlalchemy as sa
import transaction


from assembl import models as m
from assembl.lib import config


def upgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.alter_column('email', 'recipients', type_=sa.Unicode())
        op.alter_column('email', 'sender', type_=sa.Unicode())
        op.alter_column('email', 'subject', type_=sa.Unicode())
        op.alter_column('email', 'message_id', type_=sa.Unicode())
        op.alter_column('email', 'in_reply_to', type_=sa.Unicode())
        ### end Alembic commands ###

    # Do stuff with the app's models here.
    with transaction.manager:
        pass


def downgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        pass
        ### end Alembic commands ###
