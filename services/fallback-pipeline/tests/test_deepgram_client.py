"""
PROP-501: Unit tests for the Deepgram transcript-extraction logic --
plain objects standing in for the SDK's typed result variants, no
network/real socket needed.

Run: python -m pytest tests/test_deepgram_client.py -v
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deepgram_client import extract_transcript


def _results_message(transcript: str, is_final: bool):
    return SimpleNamespace(
        channel=SimpleNamespace(alternatives=[SimpleNamespace(transcript=transcript)]),
        is_final=is_final,
    )


def test_extracts_text_and_final_flag_from_results_message():
    text, is_final = extract_transcript(_results_message("hello there", True))
    assert text == "hello there"
    assert is_final is True


def test_interim_result_is_extracted_with_final_false():
    text, is_final = extract_transcript(_results_message("hello th", False))
    assert text == "hello th"
    assert is_final is False


def test_non_results_message_type_yields_no_transcript():
    # e.g. Metadata/UtteranceEnd/SpeechStarted messages -- no `channel` attribute.
    metadata_message = SimpleNamespace(request_id="abc123")
    text, is_final = extract_transcript(metadata_message)
    assert text == ""
    assert is_final is False


def test_empty_transcript_is_treated_as_no_transcript():
    text, is_final = extract_transcript(_results_message("", True))
    assert text == ""


def test_no_alternatives_yields_no_transcript():
    message = SimpleNamespace(channel=SimpleNamespace(alternatives=[]), is_final=True)
    text, is_final = extract_transcript(message)
    assert text == ""
