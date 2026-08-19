"""Restore the pgvector column the workspace-RAG store searches on.

``ai_embedding_chunks.embedding`` is read by every retrieval path in the
knowledge context (``1 - (embedding <=> %s::vector)``) and written by every
indexer (``UPDATE ai_embedding_chunks SET embedding = %s::vector``). No
migration created it: the fork's migration reset collapsed the history into
fresh ``0001``s and the column — which only ever existed as raw SQL, never as
an ORM field — was lost with it. Result: every vector search raised
``UndefinedColumn`` on every deployed database.

``CreateExtension("vector")`` emits ``CREATE EXTENSION IF NOT EXISTS vector``, so
it is a no-op where the extension is already installed, is skipped on
non-PostgreSQL backends, and honours ``allow_migrate`` — which matters because
this migration runs once per tenant alias (ADR 0029 dedicated tier), and a
tenant database provisioned fresh will not have the extension yet.

**Do not swap this back to pgvector's ``VectorExtension``.** That subclass sets
only ``self.name`` and never calls ``super().__init__()``, so ``self.hints`` is
never assigned — and Django 6.0's ``CreateExtension.database_forwards`` reads
``self.hints`` to evaluate ``allow_migrate``. It therefore dies with
``AttributeError: 'VectorExtension' object has no attribute 'hints'`` before
running any SQL, which took the whole migrate Job — and every deployment that
depends on it — down with it. Django's own operation is the compatible one, and
is precisely what the paragraph above claims this migration does.
"""

import pgvector.django.vector
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0004_aiactiondailyrollup"),
    ]

    operations = [
        CreateExtension(name="vector"),
        migrations.AddField(
            model_name="embeddingchunk",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=1536, null=True),
        ),
    ]
