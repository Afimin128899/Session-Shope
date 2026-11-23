"""Input helpers from Session PR #1, commit b51e3174268d41cf8641bb3ecd38a1468a79df76."""
from typing import Optional

def normalize_phone(text: str) -> Optional[str]:
    """Return a phone number in E.164 form, accepting input with or without ``+``."""
    text = text.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if text.startswith("00"):
        text = text[2:]
    if text.startswith("+"):
        digits = text[1:]
    else:
        digits = text

    # A common local Russian spelling is 8XXXXXXXXXX; convert it to +7XXXXXXXXXX.
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    # E.164 numbers contain at most 15 digits.  The lower bound prevents
    # attempting an authentication request for obviously incomplete input.
    if not digits.isdigit() or not (10 <= len(digits) <= 15):
        return None
    return f"+{digits}"

def normalize_code(text: str) -> Optional[str]:
    """Accept a Telegram confirmation code typed with spaces or hyphens."""
    code = text.strip().replace(" ", "").replace("-", "")
    if not code.isdigit() or not (4 <= len(code) <= 8):
        return None
    return code
