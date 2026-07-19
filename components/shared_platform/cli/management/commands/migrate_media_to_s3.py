"""One-time migration: copy every file under MEDIA_ROOT into the
configured S3 default storage.

When prod swapped DEFAULT_FILE_STORAGE from LocalMediaStorage to
S3MediaStorage, every existing media file (recipient photos,
receipt PDFs, workspace avatars, ...) needs to be lifted from the
EC2 disk into the bucket OR the URLs the database already stores
will start 404'ing. This command does that lift idempotently --
re-running is safe; it skips objects already present in S3.

Usage on the host (the EC2 still has the files at this point):

    docker exec compose-web-1 python manage.py migrate_media_to_s3 --confirm

Without --confirm it does a dry-run that prints what WOULD copy.

Local + dev environments use FileSystemStorage as the default, so
this command no-ops there ("nothing to copy because source == dest").
The check is the storage backend class, not the env name, so anyone
who configures S3 in local will get the same behaviour without
needing to special-case settings.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from infrastructure.storage.backends import S3MediaStorage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Copy MEDIA_ROOT contents into the configured S3 default storage."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually copy. Without this flag the command prints what it would do.",
        )
        parser.add_argument(
            "--media-root",
            type=str,
            default=None,
            help=(
                "Override the source directory. Defaults to settings.MEDIA_ROOT. "
                "Useful when running from a recovery container that mounted the "
                "old EC2 media volume at a different path."
            ),
        )

    def handle(self, *args, **options) -> None:
        if not isinstance(default_storage, S3MediaStorage):
            # The "I'm pointing at FileSystemStorage" case is a no-op,
            # not an error -- the local dev environment hits this every
            # time tests touch this code path.
            self.stdout.write(
                self.style.WARNING(
                    f"default_storage is {type(default_storage).__name__}, "
                    f"not S3MediaStorage. Nothing to migrate."
                )
            )
            return

        raw_root = options["media_root"] or settings.MEDIA_ROOT
        if not raw_root:
            # An empty MEDIA_ROOT used to silently default to Path("") which
            # resolves to the cwd ("/app" inside the container) -- the first
            # run of this command walked the entire repo (~4800 files would
            # have uploaded as "media") before --confirm was passed. Refuse
            # so a misconfigured environment can't ever cause a real copy.
            raise CommandError(
                "MEDIA_ROOT is empty and --media-root was not supplied. "
                "Refusing to walk the cwd."
            )
        media_root = Path(raw_root).resolve()
        if not media_root.exists():
            # Genuinely missing MEDIA_ROOT means there's nothing to copy
            # (fresh EC2, fresh local checkout). Not an error.
            self.stdout.write(
                self.style.WARNING(
                    f"MEDIA_ROOT does not exist at {media_root}. Nothing to migrate."
                )
            )
            return
        # Sanity check: the resolved path should end in /media OR be
        # explicitly overridden via --media-root. This catches the case
        # where MEDIA_ROOT was set to /app or some other broad directory.
        if media_root.name != "media" and not options["media_root"]:
            raise CommandError(
                f"Resolved MEDIA_ROOT={media_root} does not look like a media dir "
                f"(expected directory named 'media'). Pass --media-root explicitly "
                f"if this is intentional."
            )

        confirm = bool(options["confirm"])
        bucket = getattr(default_storage, "bucket_name", "?")
        location = getattr(default_storage, "location", "?")
        self.stdout.write(
            f"Migrating media from {media_root} → s3://{bucket}/{location}/ "
            f"({'LIVE' if confirm else 'DRY RUN'})"
        )

        copied = 0
        skipped = 0
        failed = 0
        for fs_path in self._walk(media_root):
            relpath = fs_path.relative_to(media_root)
            key = str(relpath)

            # default_storage.exists() does a HEAD; cheap enough for an
            # initial backfill. If this is ever re-run on a workspace
            # with millions of media files we'd want to swap to bucket
            # listing + set membership, but at demo scale this is fine.
            if default_storage.exists(key):
                skipped += 1
                continue

            if not confirm:
                self.stdout.write(f"  would copy: {key}")
                copied += 1
                continue

            try:
                with fs_path.open("rb") as fh:
                    default_storage.save(key, fh)
                copied += 1
                self.stdout.write(f"  copied: {key}")
            except Exception:
                failed += 1
                logger.exception("migrate_media_to_s3 failed key=%s", key)

        summary = f"copied={copied} skipped={skipped} failed={failed}"
        if failed:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

    @staticmethod
    def _walk(root: Path):
        """Yield every regular file under ``root``. Excludes directories
        Django never writes to (cache, tmp) so a stray .DS_Store on a
        developer laptop doesn't accidentally upload to prod."""
        ignore_dirs = {".cache", "__pycache__", "tmp", ".DS_Store"}
        for dirpath, dirnames, filenames in os.walk(root):
            # Mutate in place so os.walk doesn't descend into ignored dirs.
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            for name in filenames:
                if name in ignore_dirs:
                    continue
                yield Path(dirpath) / name
