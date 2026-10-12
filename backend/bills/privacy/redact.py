"""Turn a bill's text into something that can leave our infrastructure.

Approach: *allowlist*, not detection. We don't try to find the personal
information on a bill (names and addresses have no reliable shape, and OCR
garbles the ones that do: "K0K 1T1" comes out as "KOK 171"). Instead every
token is kept only if it is provably harmless:

- a word from `vocabulary.VOCABULARY` (billing / energy / calendar terms);
- an amount, a date, a percentage, or a short number (< 7 digits; longer
  digit runs are account, meter, contract or phone numbers) - a number of
  any length is kept when a unit follows it (kWh, m³, kW, $);
- a one-letter token, or a ≤ 3 character code mixing letters and digits
  (rate codes like D1, M) that isn't half a postal code;
- punctuation.

Everything else becomes a placeholder. On top of that, before the token
pass:
- street addresses ("999, rue Volt, app. 3", "42 TEST CRESCENT") are
  masked as a whole, because street names are often ordinary words;
- the start of the line just above an address (where the name is printed)
  is masked;
- personal information we already hold about this bill (customer name,
  account number, building address, owner) is masked wherever it appears,
  accent- and case-insensitively.

`bills.privacy.guard` independently re-checks the result before any request
leaves; this module is the transformation, the guard is the proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .vocabulary import VOCABULARY, fold

ID_MASK = "[ID]"
ADDRESS_MASK = "[ADDRESS]"
PERSONAL_MASK = "[PERSONAL]"
EMAIL_MASK = "[EMAIL]"
URL_MASK = "[URL]"
PLACEHOLDERS = (ID_MASK, ADDRESS_MASK, PERSONAL_MASK, EMAIL_MASK, URL_MASK)

STREET_TYPES = (
    r"rue|avenue|av|ave|boulevard|boul|bd|blvd|chemin|ch|route|rte|rang|place|pl|montee|"
    r"impasse|allee|promenade|cote|carre|croissant|terrasse|square|quai|"
    r"street|st|road|rd|crescent|cres|drive|dr|lane|ln|court|ct|way|circle|cir|"
    r"terrace|highway|hwy|parkway|pkwy|trail|park|row|close|grove"
)
# Folded text: "999, rue Volt", "42 TEST CRESCENT", "1000, chemin du Compteur".
STREET_RE = re.compile(
    rf"\b\d{{1,6}}[a-z]?(?:-\d{{1,6}})?,?\s+(?:[a-z'’.-]+\s+){{0,3}}?(?:{STREET_TYPES})\b\.?"
)
# Words that typically start the *next* column on the same OCR line: the
# address span stops there so we don't lose the label that follows.
# Only Capitalised tokens stop the span: "chemin du Compteur" is a street,
# "... Du 10-04-2025" is the next column.
COLUMN_STOP = {
    "from", "du", "facture", "total", "adresse", "account", "numero", "montant",
    "amount", "date", "due", "meter", "statement", "billing", "periode",
    "electricity", "puissance", "consommation",
}
MAX_ADDRESS_TOKENS = 8

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.I)

AMOUNT_RE = re.compile(r"^[-−–]?\$?[-−–]?\d{1,3}(?:[ ,.  ]\d{3})*[.,]\d{1,5}\$?$")
DATE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}$")
PERCENT_RE = re.compile(r"^\d{1,3}(?:[.,]\d+)?%$")
# A run of digits with single separators: "299 000 000 001", "0000-000001-1".
DIGIT_RUN_RE = re.compile(r"(?<![\w.,])\d+(?:[ \-.](?=\d)\d+)*(?![\w])")
UNIT_AFTER_RE = re.compile(r"^\s*(?:kwh|kw|kva|m3|m³|gj|\$|mwh)\b", re.I)
RATE_CODE_RE = re.compile(r"^[A-Za-z]{1,2}\d{1,2}$")
MAX_SAFE_DIGITS = 6


@dataclass
class Redacted:
    text: str
    masked_tokens: int
    kept_tokens: int


def _mask_known(line: str, known: list[str]) -> str:
    """Mask known personal values (accent/case-insensitive, any digit grouping)."""
    for value in known:
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 6 and len(digits) == len(re.sub(r"\s", "", value).replace("-", "")):
            # An account-like number: match it whatever the separators.
            pattern = r"[\s\-.]?".join(re.escape(d) for d in digits)
            line = re.sub(pattern, PERSONAL_MASK, line)
            continue
        # The whole value first (a name made of ordinary words: "Gestion Hiver"),
        # then each distinctive part on its own ("Testeur" without "Jean-Éloi").
        line = _replace_folded(line, value.strip())
        for part in re.split(r"[\s,]+", value):
            if len(part) >= 3 and fold(part) not in VOCABULARY and not part.isdigit():
                line = _replace_folded(line, part)
    return line


def _replace_folded(line: str, value: str) -> str:
    """Replace `value` in `line`, ignoring case and accents, on word boundaries."""
    if not value:
        return line
    pattern = re.compile(rf"(?<!\w){re.escape(fold(value))}(?!\w)")
    folded = fold(line)
    if len(folded) != len(line):  # fold() keeps the length of Latin text; be safe otherwise
        return line.replace(value, PERSONAL_MASK)
    for match in reversed(list(pattern.finditer(folded))):
        line = line[:match.start()] + PERSONAL_MASK + line[match.end():]
    return line


def _mask_street(line: str) -> tuple[str, bool]:
    """Mask every street address on one line ("... Adresse desservie 555, rue ...")."""
    found = False
    while match := STREET_RE.search(fold(line)):
        found = True
        # Extend the span over the following tokens (street name, "app. 3",
        # "bureau 410") until a label of the next column, a date, or a cap.
        tail = line[match.end():].split()
        taken = 0
        for token in tail:
            word = token.strip(",.:;")
            if taken >= MAX_ADDRESS_TOKENS or DATE_RE.match(word) or (
                word[:1].isupper() and fold(word) in COLUMN_STOP
            ):
                break
            taken += 1
        line = f"{line[:match.start()]}{ADDRESS_MASK} {' '.join(tail[taken:])}".strip()
    return line, found


def _mask_addresses(lines: list[str]) -> list[str]:
    out = list(lines)
    for i, line in enumerate(lines):
        out[i], found = _mask_street(line)
        # The addressee is printed just above: mask that line up to its first label.
        if found and i > 0 and ADDRESS_MASK not in out[i - 1]:
            above = out[i - 1].split()
            cut = next(
                (k for k, t in enumerate(above)
                 if t[:1].isupper() and fold(t.strip(",.:;")) in COLUMN_STOP),
                len(above),
            )
            if cut:
                out[i - 1] = " ".join([PERSONAL_MASK, *above[cut:]])
    return out


def _mask_digit_runs(line: str) -> str:
    def replace(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match[0])
        if len(digits) <= MAX_SAFE_DIGITS or DATE_RE.match(match[0]):
            return match[0]
        # "388.000000 kWh": one decimal point, digits on both sides, no other
        # separator - a quantity, not an identifier.
        if re.fullmatch(r"\d{1,7}\.\d{1,6}", match[0]):
            return match[0]
        # "1 013 245 kWh": a big consumption, not an identifier.
        if UNIT_AFTER_RE.match(line[match.end():]) and re.fullmatch(r"\d{1,3}(?:[ ,]\d{3})+", match[0]):
            return match[0]
        return ID_MASK
    return DIGIT_RUN_RE.sub(replace, line)


def _is_safe_word(token: str) -> bool:
    core = token.strip("()[]{}.,;:!?«»\"'’“”*#/|°")
    if not core:
        return True
    if core in PLACEHOLDERS or token in PLACEHOLDERS:
        return True
    if AMOUNT_RE.match(core) or DATE_RE.match(core) or PERCENT_RE.match(core):
        return True
    bare = fold(core.strip("$€¢-−–+=@~").rstrip("%"))  # fold: "m³" -> "m3"
    if not bare or not any(c.isalnum() for c in bare):
        return True
    if bare in VOCABULARY:
        return True
    if bare.isdigit():
        return len(bare) <= MAX_SAFE_DIGITS
    has_digit, has_alpha = any(c.isdigit() for c in bare), any(c.isalpha() for c in bare)
    if has_digit and has_alpha:
        # Rate codes like "D1", "M2": letters then digits, very short. Rejects
        # postal-code halves even when OCR swaps O/0 ("1TO", "H0H", "KOK").
        return bool(RATE_CODE_RE.match(bare))
    if re.fullmatch(r"\d+(?:[.,]\d+)?", bare):
        return True
    # Words, possibly compound: "d’électricité", "Time-of-Use", "On-Peak".
    parts = [p for p in re.split(r"[-’'/.°]", bare) if p]
    return all(len(p) == 1 or fold(p) in VOCABULARY for p in parts)


def redact_lines(lines: list[str], known_personal_info: list[str] | None = None) -> Redacted:
    known = [k for k in (known_personal_info or []) if k and k.strip()]
    lines = [_mask_known(line, known) for line in lines]
    lines = [URL_RE.sub(URL_MASK, EMAIL_RE.sub(EMAIL_MASK, line)) for line in lines]
    lines = _mask_addresses(lines)
    lines = [_mask_digit_runs(line) for line in lines]

    out_lines, masked, kept = [], 0, 0
    for line in lines:
        tokens = []
        for token in line.split():
            if _is_safe_word(token):
                tokens.append(token)
                kept += 1
            else:
                masked += 1
        if tokens and any(t not in PLACEHOLDERS for t in tokens):
            out_lines.append(" ".join(tokens))
    return Redacted(text="\n".join(out_lines), masked_tokens=masked, kept_tokens=kept)


def unsafe_tokens(text: str) -> list[str]:
    """Tokens of `text` that redact_lines() would not have let through.

    Used by the guard as an independent check of the final payload.
    """
    bad = []
    for line in text.splitlines():
        checked = _mask_digit_runs(line)
        if checked != line:
            bad.extend(t for t in line.split() if t not in checked.split())
        bad.extend(t for t in line.split() if not _is_safe_word(t))
    return bad
