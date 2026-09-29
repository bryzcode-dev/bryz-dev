from __future__ import annotations

import unittest

from tests import helpers as _helpers  # noqa: F401

from projectos.google.contract import WorkbookSnapshot
from projectos.google.fake_gateway import FakeGatewayFailure, FakeGoogleGateway, FailurePoint
from projectos.google.gateway import GoogleGateway


def fixture() -> dict:
    return {
        "contract_version": 1,
        "tabs": {},
        "requests": [
            {"sequence": 2, "request_id": "r2", "value": "second"},
            {"sequence": 1, "request_id": "r1", "value": "first"},
        ],
        "access_events": [{"sequence": 1, "event_id": "e1"}],
        "write_ready": True,
    }


class FakeGoogleGatewayTests(unittest.TestCase):
    def test_fake_implements_gateway_protocol(self) -> None:
        gateway = FakeGoogleGateway.from_fixture(fixture())
        self.assertIsInstance(gateway, GoogleGateway)
        self.assertIsInstance(gateway.read_contract(object()), WorkbookSnapshot)

    def test_fake_pull_order_and_cursor_are_deterministic(self) -> None:
        gateway = FakeGoogleGateway.from_fixture(fixture())
        batch = gateway.pull_requests(object(), "0")
        self.assertEqual(("r1", "r2"), tuple(row["request_id"] for row in batch.rows))
        self.assertEqual("2", batch.cursor)
        self.assertEqual(64, len(batch.historical_digest))
        self.assertEqual((), gateway.pull_requests(object(), "2").rows)

    def test_fake_records_calls_without_secret_values(self) -> None:
        data = fixture()
        data["requests"][0]["token"] = "super-secret-value"
        gateway = FakeGoogleGateway.from_fixture(data)
        gateway.pull_requests(object(), "0")
        rendered = repr(gateway.call_log)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("token", rendered.lower())

    def test_failure_injection_is_one_shot_or_persistent_as_configured(self) -> None:
        once = FakeGoogleGateway.from_fixture(
            fixture(), failures={FailurePoint.BEFORE_PULL_REQUESTS: 1}
        )
        with self.assertRaises(FakeGatewayFailure):
            once.pull_requests(object(), "0")
        self.assertEqual(2, len(once.pull_requests(object(), "0").rows))

        persistent = FakeGoogleGateway.from_fixture(
            fixture(), failures={FailurePoint.BEFORE_PREFLIGHT: -1}
        )
        for _ in range(2):
            with self.assertRaises(FakeGatewayFailure):
                persistent.preflight(object())

    def test_fake_rejects_write_when_binding_gate_is_closed(self) -> None:
        data = fixture()
        data["write_ready"] = False
        gateway = FakeGoogleGateway.from_fixture(data)
        with self.assertRaisesRegex(FakeGatewayFailure, "write gate"):
            gateway.publish_results(object(), ({"request_id": "r1"},))
        with self.assertRaisesRegex(FakeGatewayFailure, "write gate"):
            gateway.publish_projection(object(), {"revision_id": "v1", "tabs": {}})

    def test_historical_payload_digest_detects_remote_edit_or_delete(self) -> None:
        gateway = FakeGoogleGateway.from_fixture(fixture())
        gateway.pull_requests(object(), "2")
        gateway.replace_request_rows(
            ({"sequence": 1, "request_id": "r1", "value": "edited"},)
        )
        with self.assertRaisesRegex(FakeGatewayFailure, "historical payload"):
            gateway.pull_requests(object(), "2")


if __name__ == "__main__":
    unittest.main()
