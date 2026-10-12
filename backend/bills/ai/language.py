"""Which language a bill is written in, decided locally from its text.

Counts words that only one of the two languages uses. No model, no network:
this runs on the full text, before anything is redacted or sent.
"""

from __future__ import annotations

import re

from bills.privacy.vocabulary import fold

ENGLISH, FRENCH = "en", "fr"
# Unreadable or perfectly bilingual text: the prompt the samples were tuned with.
DEFAULT_LANGUAGE = ENGLISH

# Folded (lowercase, no accents). Words both languages print are left out on
# purpose: "total", "date", "taxes", "charges", "service", "client", "on".
_WORDS = {
    FRENCH: """
        le la les des du de et au aux un une pour sur est votre vos avec par ce cette
        facture facturation periode consommation montant partiel compte numero tarif
        jours jour mois payer avant apres solde paiement electricite gaz energie releve
        compteur frais echeance puissance redevance abonnement precedent actuel
        janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre
    """,
    ENGLISH: """
        the of and to for your is with by this that from
        bill billing period consumption amount subtotal account number rate
        days day month pay before after balance payment electricity gas energy reading
        meter fees due demand charge subscription previous current statement
        january february march april may june july august september october november december
    """,
}
WORDS = {language: frozenset(words.split()) for language, words in _WORDS.items()}


def detect_language(text: str) -> str:
    """"fr" or "en": whichever has more of its own words in `text`."""
    tokens = re.findall(r"[a-z]+", fold(text))
    french = sum(token in WORDS[FRENCH] for token in tokens)
    english = sum(token in WORDS[ENGLISH] for token in tokens)
    if french == english:
        return DEFAULT_LANGUAGE
    return FRENCH if french > english else ENGLISH
