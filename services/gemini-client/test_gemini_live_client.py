from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import types

import gemini_live_client
from gemini_live_client import GeminiLiveSession, TurnComplete


class FakeLiveSession:
    def __init__(self, messages):
        self.messages = messages
        self.sent_audio = []
        self.received = False

    async def receive(self):
        if self.received:
            return
        self.received = True
        for message in self.messages:
            yield message

    async def send_realtime_input(self, **kwargs):
        self.sent_audio.append(kwargs)

    async def send_tool_response(self, **kwargs):
        pass

    async def send_client_content(self, **kwargs):
        pass


class FakeConnectContext:
    def __init__(self, session):
        self.session = session
        self.exit_calls = 0

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_exc_info):
        self.exit_calls += 1


class FakeLiveAPI:
    def __init__(self, contexts):
        self.contexts = iter(contexts)
        self.connect_calls = []

    def connect(self, *, model, config):
        self.connect_calls.append((model, config))
        return next(self.contexts)


class FakeClient:
    def __init__(self, live_api):
        self.aio = SimpleNamespace(live=live_api)


def _message(*, update=None, go_away=None, server_content=None):
    return SimpleNamespace(
        session_resumption_update=update,
        go_away=go_away,
        tool_call=None,
        server_content=server_content,
    )


@pytest.mark.asyncio
async def test_goaway_resumes_with_latest_handle_and_keeps_compression(monkeypatch):
    old_session = FakeLiveSession(
        [
            _message(
                update=types.LiveServerSessionResumptionUpdate(
                    new_handle="resume-token",
                    resumable=True,
                )
            ),
            _message(go_away=types.LiveServerGoAway(time_left="5s")),
        ]
    )
    new_session = FakeLiveSession(
        [
            _message(
                server_content=types.LiveServerContent(
                    turn_complete=True,
                )
            )
        ]
    )
    old_context = FakeConnectContext(old_session)
    new_context = FakeConnectContext(new_session)
    live_api = FakeLiveAPI([old_context, new_context])
    monkeypatch.setattr(gemini_live_client.genai, "Client", lambda **_kwargs: FakeClient(live_api))

    session = GeminiLiveSession(api_key="test-key")
    async with session:
        events = [event async for event in session.receive_events()]
        await session.send_audio(b"\x00\x00")

    assert events == [TurnComplete()]
    assert [call[0] for call in live_api.connect_calls] == ["gemini-3.8-live"] * 2
    initial_config = live_api.connect_calls[0][1]
    resumed_config = live_api.connect_calls[1][1]
    assert initial_config.session_resumption.handle is None
    assert resumed_config.session_resumption.handle == "resume-token"
    assert initial_config.context_window_compression.sliding_window is not None
    assert resumed_config.context_window_compression.sliding_window is not None
    assert old_context.exit_calls == 1
    assert new_context.exit_calls == 1
    assert new_session.sent_audio


@pytest.mark.asyncio
async def test_goaway_without_resumable_handle_fails_explicitly(monkeypatch):
    session_instance = FakeLiveSession([_message(go_away=types.LiveServerGoAway(time_left="5s"))])
    live_api = FakeLiveAPI([FakeConnectContext(session_instance)])
    monkeypatch.setattr(gemini_live_client.genai, "Client", lambda **_kwargs: FakeClient(live_api))

    session = GeminiLiveSession(api_key="test-key")
    async with session:
        with pytest.raises(RuntimeError, match="has not provided a resumable session handle"):
            _ = [event async for event in session.receive_events()]


def test_model_default_is_configurable(monkeypatch):
    monkeypatch.setattr(gemini_live_client.genai, "Client", lambda **_kwargs: object())
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    assert GeminiLiveSession(api_key="test-key")._model == "gemini-3.8-live"

    monkeypatch.setenv("GEMINI_LIVE_MODEL", "custom-live-model")
    assert GeminiLiveSession(api_key="test-key")._model == "custom-live-model"
