"""
Backfill workspace embeddings for a single workspace ID.
Indexes Workspace (workspace_story/shared_body), Actions, and Comments for the provided workspace.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from infrastructure.persistence.workspaces.models import Workspace, Action, WorkspaceComment
from components.knowledge.infrastructure.factories.vector_stores.factory import VectorStoreFactory


class Command(BaseCommand):
    help = 'Backfill embeddings for a single workspace by ID'

    def add_arguments(self, parser):
        parser.add_argument('workspace_id', type=str, help='Workspace ID to backfill')

    def handle(self, *args, **options):
        workspace_id = options['workspace_id']
        self.stdout.write(f"🔄 Backfilling embeddings for workspace: {workspace_id}")
        self.stdout.write("=" * 60)

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            self.stdout.write(self.style.ERROR("❌ Workspace not found"))
            return

        # Initialize vector store (uses default OpenAI embeddings)
        vector_store = VectorStoreFactory.create_vector_store()

        total = 0

        # Workspace content
        content_parts = []
        if workspace.workspace_story:
            content_parts.append(workspace.workspace_story)
        if workspace.shared_body:
            content_parts.append(workspace.shared_body)
        if content_parts:
            combined = " ".join(content_parts)
            vector_store.add_texts(
                texts=[combined],
                metadatas=[{
                    'type': 'workspace',
                    'workspace_id': str(workspace.id),
                    'workspace_name': workspace.workspace_name,
                    'owner_id': str(workspace.workspace_owner.id) if workspace.workspace_owner else None,
                    'created_at': workspace.created_at.isoformat() if workspace.created_at else None,
                    'updated_at': workspace.updated_at.isoformat() if workspace.updated_at else None,
                    'privacy': workspace.privacy,
                    'status': workspace.status,
                }]
            )
            self.stdout.write(self.style.SUCCESS("✅ Indexed workspace story/shared body"))
            total += 1

        # Actions
        actions = Action.objects.filter(workspace_id=workspace.id).exclude(
            (Q(title__isnull=True) | Q(title='')) & (Q(body__isnull=True) | Q(body=''))
        )
        count = 0
        for a in actions:
            text = f"{a.title or ''} {a.body or ''}".strip()
            if not text:
                continue
            vector_store.add_texts(
                texts=[text],
                metadatas=[{
                    'type': 'action',
                    'action_id': str(a.id),
                    'title': a.title,
                    'workspace_id': str(workspace.id),
                    'owner_id': str(a.owner.id) if a.owner else None,
                    'created_at': a.created_date.isoformat() if a.created_date else None,
                    'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                    'privacy': a.privacy,
                }]
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f"✅ Indexed {count} actions"))
        total += count

        # Comments
        comments = WorkspaceComment.objects.filter(seeds_id=workspace.id).exclude(Q(comment__isnull=True) | Q(comment=''))
        count = 0
        for c in comments:
            vector_store.add_texts(
                texts=[c.comment],
                metadatas=[{
                    'type': 'comment',
                    'comment_id': str(c.id),
                    'workspace_id': str(workspace.id),
                    'author_id': str(c.author.id) if c.author else None,
                    'created_at': c.created_on.isoformat() if c.created_on else None,
                    'privacy': c.privacy,
                    'is_parent': c.is_parent,
                }]
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f"✅ Indexed {count} comments"))
        total += count

        # Income/Expenses indexing removed; use budget.transactions for financial data

        self.stdout.write(self.style.SUCCESS(f"🎉 Backfill complete. Total chunks indexed: {total}"))

