import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii_masking import mask_pii


def test_masks_person_name():
    result = mask_pii("My name is John Smith and I'm interested in a 3-bedroom house.")
    assert "John Smith" not in result
    assert "<PERSON>" in result


def test_masks_phone_number():
    result = mask_pii("You can reach me at 555-123-4567.")
    assert "555-123-4567" not in result
    assert "<PHONE_NUMBER>" in result


def test_masks_email():
    result = mask_pii("My email is jane.doe@example.com.")
    assert "jane.doe@example.com" not in result
    assert "<EMAIL_ADDRESS>" in result


def test_masks_credit_card():
    result = mask_pii("My card number is 4111111111111111.")
    assert "4111111111111111" not in result
    assert "<CREDIT_CARD>" in result


def test_masks_ssn():
    # NOT 123-45-6789: Presidio deliberately deny-lists that exact number
    # as a well-known canonical placeholder/example SSN (correct behavior,
    # discovered by this test failing against it and tracing why).
    result = mask_pii("My social security number is 245-67-8901.")
    assert "245-67-8901" not in result
    assert "<US_SSN>" in result


def test_does_not_mask_property_address():
    """Addresses are business data the CRM needs, not PII to hide."""
    result = mask_pii("I'm interested in the property at 123 Oak Street, Austin, Texas.")
    assert "123 Oak Street" in result
    assert "Austin" in result


def test_does_not_mask_price_or_numbers():
    result = mask_pii("The price is $520,000 for a 3 bedroom, 2 bathroom house.")
    assert "$520,000" in result
    assert "3 bedroom" in result


def test_masks_multiple_pii_in_one_transcript():
    text = "Hi, this is Sarah Johnson, my number is 512-555-0199 and email sarah.j@example.com."
    result = mask_pii(text)
    assert "Sarah Johnson" not in result
    assert "512-555-0199" not in result
    assert "sarah.j@example.com" not in result


def test_empty_string_returns_empty():
    assert mask_pii("") == ""


def test_text_with_no_pii_is_unchanged():
    text = "Do you have any 3-bedroom houses under 550000?"
    assert mask_pii(text) == text
