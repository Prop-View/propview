"""
PROP-501: GPT-4o-mini -- the middle stage of the cascaded fallback (STT ->
LLM -> TTS). Takes the transcript Deepgram produced plus the running
conversation history and returns a text reply, which cartesia_client.py
then synthesizes to speech.

Deliberately non-streaming (one full completion per turn, not
token-by-token): this cascade already trades latency for reliability
(it's the fallback path, not the primary one) -- streaming would add
real complexity (partial-sentence TTS chunking) for a latency win that
isn't this path's actual job. Gemini's own native S2S path is where
low-latency streaming matters; see ../gemini-client/.

**Partially live-verified**: no real OpenAI API key available in this
environment, but `generate_reply()` was run for real against OpenAI's API
with a fake key (`api_key="sk-fake"`) -- it reached a real
`AuthenticationError` (401) from OpenAI's own auth layer, confirming the
request shape is correct. What's NOT verified: real completion quality,
since that needs a real key.
"""

from __future__ import annotations

from openai import AsyncOpenAI

DEFAULT_MODEL = "gpt-4o-mini"
MAX_REPLY_TOKENS = 150  # keeps replies phone-call-short, matching the plan's voice-brevity requirement


class FallbackLLM:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate_reply(self, system_prompt: str, conversation_history: list[dict[str, str]]) -> str:
        """`conversation_history` -- a list of {"role": "user"|"assistant", "content": str}
        turns, oldest first. Returns the assistant's reply text (empty
        string if the model returned nothing, e.g. a content-filtered
        response -- callers should treat that as "say nothing this turn,"
        not crash)."""
        messages = [{"role": "system", "content": system_prompt}, *conversation_history]
        response = await self._client.chat.completions.create(
            model=self._model, messages=messages, max_completion_tokens=MAX_REPLY_TOKENS, temperature=0.7
        )
        choice = response.choices[0]
        return choice.message.content or ""
