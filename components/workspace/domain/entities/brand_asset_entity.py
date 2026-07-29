"""Entity: one item in a workspace's brand image library.

The library complements the fixed logo slots on the theme — assets are the
reusable many (hero shots, team photos, extra logos) public pages pull from.
Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass

BRAND_ASSET_KINDS = ("photo", "logo", "graphic")


@dataclass(frozen=True)
class BrandAssetEntity:
    id: str
    workspace_id: str
    url: str
    storage_key: str = ""
    label: str = ""
    alt_text: str = ""
    kind: str = "photo"
    deleted: bool = False
    created_at: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "url": self.url,
            "storage_key": self.storage_key,
            "label": self.label,
            "alt_text": self.alt_text,
            "kind": self.kind,
            "created_at": self.created_at,
        }
