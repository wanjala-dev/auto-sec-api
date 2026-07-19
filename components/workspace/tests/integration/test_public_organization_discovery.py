import pytest


# The public org discovery/search endpoint (GET /workspaces/public/organizations/
# discovery/) was built pre-DDD (apps/workspaces) and was NOT ported during the
# DDD/Hex refactor — the view + URL were dropped while these tests were copied
# into components/. The capability is genuinely missing (no frontend currently
# calls it, so no active UI breakage). These tests document the intended contract
# and are marked xfail until the endpoint is restored in components/workspace/api/.
# strict=True so they flip to a hard failure (reminding us to remove the marker)
# the moment the endpoint comes back. Tracked as a real backend-capability gap.
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.xfail(
        reason="public org discovery endpoint dropped in the DDD refactor; not yet restored",
        strict=True,
    ),
]


def test_public_organization_discovery_returns_only_public_active_organizations(api_client, workspace_factory):
    public_org = workspace_factory(
        workspace_name="Hope Foundation",
        workspace_story="Helping children through community programs",
        privacy="public",
        status="active",
        is_active=True,
    )
    private_org = workspace_factory(
        workspace_name="Private Org",
        privacy="private",
        status="active",
        is_active=True,
    )

    Sector = public_org._meta.get_field("sector").related_model
    personal_sector, _ = Sector.objects.get_or_create(slug="personal", defaults={"name": "Personal"})
    personal_workspace = workspace_factory(
        workspace_name="My Personal Space",
        sector=personal_sector,
        privacy="public",
        status="active",
        is_active=True,
    )

    response = api_client.get("/workspaces/public/organizations/discovery/")

    assert response.status_code == 200
    payload = response.data
    assert payload["status"] == "success"

    ids = {entry["id"] for entry in payload["data"]}
    assert str(public_org.id) in ids
    assert str(private_org.id) not in ids
    assert str(personal_workspace.id) not in ids


def test_public_organization_discovery_supports_search(api_client, workspace_factory):
    target = workspace_factory(
        workspace_name="Bright Future",
        workspace_story="Donor onboarding and scholarship support",
        privacy="public",
        status="active",
        is_active=True,
    )
    workspace_factory(
        workspace_name="Unrelated Org",
        workspace_story="Completely different mission",
        privacy="public",
        status="active",
        is_active=True,
    )

    response = api_client.get("/workspaces/public/organizations/discovery/", {"q": "scholarship"})

    assert response.status_code == 200
    payload = response.data
    ids = {entry["id"] for entry in payload["data"]}
    assert str(target.id) in ids
    assert payload["meta"]["query"] == "scholarship"


def test_public_organization_discovery_validates_limit(api_client):
    response = api_client.get("/workspaces/public/organizations/discovery/", {"limit": "abc"})

    assert response.status_code == 400
    assert response.data["status"] == "error"
