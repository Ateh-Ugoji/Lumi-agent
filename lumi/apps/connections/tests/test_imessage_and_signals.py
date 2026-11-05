import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from apps.connections.imessage.client import IMessageResult, send_imessage
from apps.connections.imessage.service import handle_inbound_imessage
from apps.connections.signals.dispatcher import SignalEvent, format_signal_message, dispatch_signal_alert


@pytest.fixture
def auth_client(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


@pytest.mark.django_db
class TestIMessageAndSignals:
    def test_imessage_status_endpoint(self, auth_client, make_profile, owner):
        profile = make_profile(owner)
        resp = auth_client.get(f"/api/v1/channels/imessage/status?profile_id={profile.pk}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "native_macos_available" in data
        assert "setup_guide" in data

    @patch("subprocess.run")
    def test_send_native_applescript_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        res = send_imessage(recipient="+1234567890", message="Test Alert")
        assert res.success is True
        assert res.recipient == "+1234567890"
        assert res.channel == "native_macos"

    @patch("apps.connections.imessage.service.send_imessage")
    @patch("apps.core.agent_runtime.get_runtime")
    def test_handle_inbound_imessage(self, mock_get_runtime, mock_send, owner, make_profile):
        profile = make_profile(owner)
        mock_runtime = MagicMock()

        async def fake_run_turn(pid, text):
            return MagicMock(content="I analyzed your viral hook.")

        mock_runtime.run_turn = fake_run_turn
        mock_get_runtime.return_value = mock_runtime
        mock_send.return_value = IMessageResult(
            success=True,
            channel="native_macos",
            recipient="+1234567890",
            message="I analyzed your viral hook.",
        )

        res = handle_inbound_imessage(
            sender="+1234567890",
            text="How is my latest post doing?",
            profile_id=profile.pk,
        )

        assert res["ok"] is True
        assert "viral hook" in res["reply"]
        assert res["sender"] == "+1234567890"

    def test_format_signal_messages(self):
        spike_signal = SignalEvent(
            event_type="spike.velocity",
            title="Spike",
            message="",
            data={"velocity": "3.5x", "replies": 45, "url": "https://x.com/post/1"},
        )
        spike_text = format_signal_message(spike_signal)
        assert "3.5x" in spike_text
        assert "13.5x" in spike_text

        breakout_signal = SignalEvent(
            event_type="competitor.breakout",
            title="Competitor",
            message="",
            data={"handle": "timmyisagod", "hook": "Stop doing this.", "lift": "4.1x"},
        )
        breakout_text = format_signal_message(breakout_signal)
        assert "@timmyisagod" in breakout_text
        assert "Stop doing this." in breakout_text

    @patch("apps.connections.signals.dispatcher.send_imessage")
    def test_signal_test_endpoint(self, mock_send, auth_client, owner, make_profile):
        profile = make_profile(owner)
        mock_send.return_value = IMessageResult(
            success=True,
            channel="native_macos",
            recipient="+1999888777",
            message="Test",
        )

        resp = auth_client.post(
            f"/api/v1/signals/test?profile_id={profile.pk}",
            {"event_type": "spike.velocity", "imessage_recipient": "+1999888777"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["test_result"]["imessage"]["success"] is True
