from __future__ import annotations

from components.money.application.reconcile_workspace_currency_service import (
    ReconcileWorkspaceCurrency,
)


class _FakeReader:
    def __init__(self, currency):
        self._currency = currency
        self.calls = []

    def resolve(self, *, workspace_id):
        self.calls.append(workspace_id)
        return self._currency


class _FakeWriter:
    def __init__(self, changed=True):
        self._changed = changed
        self.writes = []

    def write(self, *, workspace_id, currency):
        self.writes.append((workspace_id, currency))
        return self._changed


class TestReconcileWorkspaceCurrency:
    def test_writes_settlement_currency_when_present(self):
        reader = _FakeReader("CAD")
        writer = _FakeWriter(changed=True)

        result = ReconcileWorkspaceCurrency(reader=reader, writer=writer).execute(
            workspace_id="ws-1"
        )

        assert writer.writes == [("ws-1", "CAD")]
        assert result.settlement_currency == "CAD"
        assert result.changed is True

    def test_no_write_when_no_connected_account_currency(self):
        reader = _FakeReader(None)
        writer = _FakeWriter()

        result = ReconcileWorkspaceCurrency(reader=reader, writer=writer).execute(
            workspace_id="ws-2"
        )

        assert writer.writes == []
        assert result.settlement_currency is None
        assert result.changed is False

    def test_reports_unchanged_when_writer_is_noop(self):
        reader = _FakeReader("USD")
        writer = _FakeWriter(changed=False)

        result = ReconcileWorkspaceCurrency(reader=reader, writer=writer).execute(
            workspace_id="ws-3"
        )

        assert writer.writes == [("ws-3", "USD")]
        assert result.changed is False
