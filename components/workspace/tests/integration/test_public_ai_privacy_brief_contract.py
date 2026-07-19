import pytest


pytestmark = pytest.mark.django_db


def test_public_ai_privacy_brief_contract_returns_contract_and_audit_metadata(api_client):
    response = api_client.get('/workspaces/public/ai-privacy-brief/contract/')

    assert response.status_code == 200
    payload = response.data
    assert payload['status'] == 'success'

    data = payload['data']
    assert data['contract']['scope'] == 'public_ai_privacy_brief'
    assert data['contract']['version'] == '2026-02-28'

    assert data['ai_privacy_brief']['data_residency']['supported'] is True
    assert data['ai_privacy_brief']['casl_reassurance']['supported'] is True

    controls = data['auditable_controls_metadata']['controls']
    assert isinstance(controls, list)
    assert len(controls) >= 3
    assert controls[0]['audit_signal']
