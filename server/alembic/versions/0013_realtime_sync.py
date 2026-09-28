"""Coalesce replaceable state without discarding durable history or events."""

import sqlalchemy as sa
from alembic import op

revision = "0013_realtime_sync"
down_revision = "0012_edge_cloud"
branch_labels = None
depends_on = None

KEY_FUNCTION = r"""
CREATE FUNCTION sync_state_key(entity text, doc jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE entity
  WHEN 'tag_current_values' THEN entity || ':' || (doc->>'tag_id')
  WHEN 'connection_runtime' THEN entity || ':' || (doc->>'connection_id')
  WHEN 'worker_runtime' THEN entity || ':' || (doc->>'id')
  ELSE NULL END
$$;
"""

CAPTURE = r"""
CREATE OR REPLACE FUNCTION capture_sync_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE doc jsonb;
BEGIN
 IF (SELECT mode FROM sync_state WHERE id=1) IS DISTINCT FROM 'edge' THEN RETURN NULL; END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('tag_history','commands','alarm_events','automation_executions','remote_inbox') THEN RETURN NULL; END IF;
 doc := sync_document(TG_TABLE_NAME, CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END);
 INSERT INTO sync_outbox(event_id,entity,operation,priority,payload,created_at,coalesce_key)
 VALUES(gen_random_uuid()::text,TG_TABLE_NAME,CASE WHEN TG_OP='DELETE' THEN 'delete' ELSE 'upsert' END,TG_ARGV[0]::int,doc,now(),sync_state_key(TG_TABLE_NAME,doc))
 ON CONFLICT (coalesce_key) DO UPDATE SET
  id=EXCLUDED.id,event_id=EXCLUDED.event_id,operation=EXCLUDED.operation,
  payload=EXCLUDED.payload,created_at=EXCLUDED.created_at,retry_at=NULL;
 RETURN NULL;
END $$;
"""

# Restores the original append-only capture when deliberately downgrading. Durable rows
# are untouched; obsolete intermediate state removed by upgrade cannot be reconstructed.
OLD_CAPTURE = r"""
CREATE OR REPLACE FUNCTION capture_sync_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE doc jsonb;
BEGIN
 IF (SELECT mode FROM sync_state WHERE id=1) IS DISTINCT FROM 'edge' THEN RETURN NULL; END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('tag_history','commands','alarm_events','automation_executions','remote_inbox') THEN RETURN NULL; END IF;
 doc := sync_document(TG_TABLE_NAME, CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END);
 INSERT INTO sync_outbox(event_id,entity,operation,priority,payload,created_at)
 VALUES(gen_random_uuid()::text,TG_TABLE_NAME,CASE WHEN TG_OP='DELETE' THEN 'delete' ELSE 'upsert' END,TG_ARGV[0]::int,doc,now());
 RETURN NULL;
END $$;
"""


def upgrade() -> None:
    # Lock state writers before their outbox target. The entire transition is transactional.
    op.execute(
        "LOCK TABLE tag_current_values, connection_runtime, worker_runtime IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute("LOCK TABLE sync_outbox IN ACCESS EXCLUSIVE MODE")
    op.add_column("sync_outbox", sa.Column("coalesce_key", sa.String(120), nullable=True))
    op.execute(KEY_FUNCTION)
    op.execute(
        "UPDATE sync_outbox SET coalesce_key=sync_state_key(entity,payload::jsonb) WHERE entity IN ('tag_current_values','connection_runtime','worker_runtime')"
    )
    op.execute("""
      WITH ranked AS (
        SELECT id, row_number() OVER (PARTITION BY coalesce_key ORDER BY id DESC) AS ordinal
        FROM sync_outbox WHERE coalesce_key IS NOT NULL
      ) DELETE FROM sync_outbox USING ranked WHERE sync_outbox.id=ranked.id AND ranked.ordinal>1
    """)
    op.execute("UPDATE sync_outbox SET retry_at=NULL WHERE coalesce_key IS NOT NULL")
    op.create_unique_constraint("uq_sync_outbox_coalesce_key", "sync_outbox", ["coalesce_key"])
    op.create_index("ix_sync_outbox_entity_id", "sync_outbox", ["entity", "id"])
    op.execute(CAPTURE)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE tag_current_values, connection_runtime, worker_runtime IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute("LOCK TABLE sync_outbox IN ACCESS EXCLUSIVE MODE")
    op.execute(OLD_CAPTURE)
    op.drop_index("ix_sync_outbox_entity_id", table_name="sync_outbox")
    op.drop_constraint("uq_sync_outbox_coalesce_key", "sync_outbox", type_="unique")
    op.drop_column("sync_outbox", "coalesce_key")
    op.execute("DROP FUNCTION sync_state_key(text,jsonb)")
