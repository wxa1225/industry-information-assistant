"""Initial schema - all existing tables

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== users ==========
    op.create_table(
        'users',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('email', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('is_superuser', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== chat_sessions ==========
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('title', sa.String(255), default='新对话'),
        sa.Column('session_type', sa.String(50), default='chat'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_chat_sessions_user_id', 'chat_sessions', ['user_id'])

    # ========== chat_messages ==========
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE')),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('thinking', sa.Text()),
        sa.Column('references_data', sa.dialects.postgresql.JSONB()),
        sa.Column('image_results', sa.dialects.postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_chat_messages_session_id', 'chat_messages', ['session_id'])

    # ========== chat_attachments ==========
    op.create_table(
        'chat_attachments',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('message_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('chat_messages.id', ondelete='CASCADE'), nullable=True),
        sa.Column('session_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('content_text', sa.Text()),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== long_term_memories ==========
    op.create_table(
        'long_term_memories',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('session_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('key_insights', sa.dialects.postgresql.JSONB()),
        sa.Column('milvus_ids', sa.ARRAY(sa.Text())),
        sa.Column('token_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # ========== knowledge_bases ==========
    op.create_table(
        'knowledge_bases',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('document_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== documents ==========
    op.create_table(
        'documents',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('knowledge_base_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE')),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50)),
        sa.Column('file_size', sa.BigInteger()),
        sa.Column('file_path', sa.String(500)),
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('chunk_count', sa.Integer(), default=0),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_documents_knowledge_base_id', 'documents', ['knowledge_base_id'])

    # ========== industry_stats ==========
    op.create_table(
        'industry_stats',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('industry_name', sa.String(100), nullable=False, index=True),
        sa.Column('metric_name', sa.String(100), nullable=False, index=True),
        sa.Column('metric_value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(50)),
        sa.Column('year', sa.Integer(), index=True),
        sa.Column('quarter', sa.Integer()),
        sa.Column('month', sa.Integer()),
        sa.Column('region', sa.String(50), default='全国'),
        sa.Column('source', sa.String(200)),
        sa.Column('source_url', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== company_data ==========
    op.create_table(
        'company_data',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_name', sa.String(200), nullable=False, index=True),
        sa.Column('stock_code', sa.String(20)),
        sa.Column('industry', sa.String(100), index=True),
        sa.Column('sub_industry', sa.String(100)),
        sa.Column('revenue', sa.Float()),
        sa.Column('net_profit', sa.Float()),
        sa.Column('gross_margin', sa.Float()),
        sa.Column('market_cap', sa.Float()),
        sa.Column('employees', sa.Integer()),
        sa.Column('market_share', sa.Float()),
        sa.Column('year', sa.Integer(), index=True),
        sa.Column('quarter', sa.Integer()),
        sa.Column('data_source', sa.String(200)),
        sa.Column('extra_data', sa.dialects.postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== policy_data ==========
    op.create_table(
        'policy_data',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('policy_name', sa.String(500), nullable=False),
        sa.Column('policy_number', sa.String(100)),
        sa.Column('department', sa.String(200), nullable=False, index=True),
        sa.Column('level', sa.String(50), default='国家级'),
        sa.Column('publish_date', sa.Date(), index=True),
        sa.Column('effective_date', sa.Date()),
        sa.Column('expiry_date', sa.Date()),
        sa.Column('category', sa.String(100), index=True),
        sa.Column('industry', sa.String(100), index=True),
        sa.Column('summary', sa.Text()),
        sa.Column('key_points', sa.dialects.postgresql.JSONB()),
        sa.Column('full_text_url', sa.Text()),
        sa.Column('impact_level', sa.String(20)),
        sa.Column('affected_entities', sa.dialects.postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== research_checkpoints ==========
    op.create_table(
        'research_checkpoints',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', sa.String(64), nullable=False, index=True),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('phase', sa.String(32), nullable=False),
        sa.Column('iteration', sa.Integer(), default=0),
        sa.Column('state_json', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('ui_state_json', sa.dialects.postgresql.JSONB()),
        sa.Column('final_report', sa.Text()),
        sa.Column('status', sa.String(16), default='running'),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== industry_news ==========
    op.create_table(
        'industry_news',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('industry_id', sa.String(50), index=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text()),
        sa.Column('source', sa.String(200)),
        sa.Column('source_url', sa.Text()),
        sa.Column('category', sa.String(50), default='新闻', index=True),
        sa.Column('department', sa.String(200)),
        sa.Column('publish_time', sa.DateTime(), index=True),
        sa.Column('collected_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('keywords', sa.String(500)),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== bidding_info ==========
    op.create_table(
        'bidding_info',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('industry_id', sa.String(50), index=True),
        sa.Column('bid_id', sa.String(100), unique=True, index=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('notice_type', sa.String(50), index=True),
        sa.Column('province', sa.String(50), index=True),
        sa.Column('city', sa.String(50)),
        sa.Column('content', sa.Text()),
        sa.Column('publish_time', sa.DateTime(), index=True),
        sa.Column('source', sa.String(200), default='81api'),
        sa.Column('collected_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ========== news_collection_tasks ==========
    op.create_table(
        'news_collection_tasks',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('total_collected', sa.Integer(), default=0),
        sa.Column('error_message', sa.Text()),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('completed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('news_collection_tasks')
    op.drop_table('bidding_info')
    op.drop_table('industry_news')
    op.drop_table('research_checkpoints')
    op.drop_table('policy_data')
    op.drop_table('company_data')
    op.drop_table('industry_stats')
    op.drop_table('documents')
    op.drop_table('knowledge_bases')
    op.drop_table('long_term_memories')
    op.drop_table('chat_attachments')
    op.drop_table('chat_messages')
    op.drop_table('chat_sessions')
    op.drop_table('users')
