"""Pure-vocabulary tests for the shared ATT&CK catalogue."""

from __future__ import annotations

import pytest

from components.shared_kernel.domain.mitre import (
    TECHNIQUES,
    MitreTactic,
    order_flow,
    technique,
)

pytestmark = pytest.mark.unit


def test_registry_is_keyed_by_id_and_self_consistent():
    for tid, t in TECHNIQUES.items():
        assert t.technique_id == tid
        assert isinstance(t.tactic, MitreTactic)
        assert t.name


def test_technique_resolves_known_id():
    t = technique("T1190")
    assert t.name == "Exploit Public-Facing Application"
    assert t.tactic is MitreTactic.INITIAL_ACCESS


def test_technique_unknown_id_raises():
    with pytest.raises(KeyError):
        technique("T9999")


def test_subtechnique_url_nests_under_parent():
    assert technique("T1078.004").url == "https://attack.mitre.org/techniques/T1078/004/"
    assert technique("T1190").url == "https://attack.mitre.org/techniques/T1190/"


def test_to_dict_shape():
    d = technique("T1530").to_dict()
    assert d == {
        "technique_id": "T1530",
        "name": "Data from Cloud Storage",
        "tactic": "collection",
        "tactic_label": "Collection",
        "url": "https://attack.mitre.org/techniques/T1530/",
    }


def test_order_flow_sorts_kill_chain():
    collection = technique("T1530")  # order 9
    initial = technique("T1190")  # order 1
    priv = technique("T1078.004")  # order 4
    assert order_flow((collection, priv, initial)) == (initial, priv, collection)


def test_tactic_order_is_monotonic_kill_chain():
    orders = [t.order for t in MitreTactic]
    assert orders == sorted(orders)
    assert MitreTactic.INITIAL_ACCESS.order < MitreTactic.IMPACT.order
