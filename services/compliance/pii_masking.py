"""
PROP-506: Automated PII masking (regex + Presidio) for transcripts stored
in the DB (interactions.transcript).

Presidio's built-in recognizers are already a regex+NLP hybrid (phone/
email/credit-card/SSN are regex-based, PERSON uses spaCy NER) -- that
combination is what the plan's "regex + Presidio" refers to, not a
separate hand-rolled layer on top.

Deliberately does NOT mask LOCATION/addresses: a property's street
address is core business data this CRM needs, not PII to hide from
ourselves. Only caller-identifying and financial info is masked.
"""

from __future__ import annotations

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

DEFAULT_ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"]

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


def _get_analyzer() -> AnalyzerEngine:
    global _analyzer
    if _analyzer is None:
        config = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
        nlp_engine = NlpEngineProvider(nlp_configuration=config).create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
    return _analyzer


def _get_anonymizer() -> AnonymizerEngine:
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = AnonymizerEngine()
    return _anonymizer


def mask_pii(text: str, entities: list[str] | None = None) -> str:
    """Returns text with PII replaced by <ENTITY_TYPE> placeholders."""
    if not text:
        return text
    results = _get_analyzer().analyze(text=text, language="en", entities=entities or DEFAULT_ENTITIES)
    return _get_anonymizer().anonymize(text=text, analyzer_results=results).text
