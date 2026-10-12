"""Words allowed to leave our infrastructure.

This is an ALLOWLIST: a word printed on a bill is sent to a model only if it
is listed here (compared lowercase, without accents). Everything else
(names, street and city names, business names, OCR garbage) is replaced by
a placeholder before any request is built.

Rules for adding a word:
- it is a billing / energy / calendar / grammar word, never a proper noun;
- it can't plausibly be someone's name on its own. In doubt, leave it out:
  the cost of a missing word is a slightly worse extraction, the cost of a
  wrong word is a privacy incident.
Keep it sorted by theme; it is reviewed like code.
"""

from __future__ import annotations

import unicodedata


def fold(word: str) -> str:
    """Lowercase, accents stripped: 'Électricité' -> 'electricite'."""
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_WORDS = """
# --- grammar (fr) ---
a au aux avec ce ces cet cette d de des du en et l la le les leur n ne no non
ou par pas plus pour sa se son sur un une vos votre y est sont ete etre
jusqu jusqua apres avant entre chaque autre autres reste dont qui que
# --- grammar (en) ---
a all an and any are as at be by each for from if in into is it its not of
on or our per than that the this to up with you your will been has have
other remaining since until after before
# --- calendar ---
janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre
janv fevr fev avr juil sept oct nov dec
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep
lundi mardi mercredi jeudi vendredi samedi dimanche
monday tuesday wednesday thursday friday saturday sunday
jour jours j d day days mois month months annee annees an ans year years
date dates periode periodes period periods du au from to through thru
debut fin start end quotidienne quotidien daily moyenne average
semaine week hebdomadaire mensuel mensuelle monthly bimestriel bimonthly
precedente precedent previous prochaine prochain next courante courant current
derniere dernier last cette this
# --- bill structure ---
facture factures bill bills billing invoice statement releve releves reading readings
compte account accounts client customer customers numero number no n
page sommaire summary detail details information informations info utile useful
resume total totale totals sous partiel subtotal sub montant montants amount amounts
solde balance du due echeance paiement paiements payment payments recu received
merci thank thanks verse paid pay payer regler
frais charge charges cout couts cost costs prix price prices tarif tarifs rate rates
plan plans option service services fourniture supply transport transportation
distribution delivery livraison regulatory reglementaires reglementaire
acheminement abonnement subscription redevance base fixe fixed variable
credit credits cr debit rabais rebate remise discount ajustement ajustements
adjustment adjustments correction estimation estime estimated reel reelle actual
taxe taxes tax tps tvq tvh gst qst hst pst tva ht ttc
administration administratifs penalite interet interets interest late retard
contrat contract compteur compteurs meter meters multiplicateur multiplier
difference nouveau nouvelle new ancien ancienne old lecture
consommation consommations consomme consommee usage use used utilisation
volume volumes quantite quantity
historique history comparaison comparison
annuel annuelle annual
reference references index indexes type class classe categorie category
actual read lu premise premises site
coefficient conversion converti converted pcs
mode modalites versements egaux equal
# --- energy ---
electricite electrique electricity electric energie energy gaz gas naturel natural
puissance demand power appel facturee facturer billed billing minimale minimum
maximale maximum reelle real apparente apparent facteur factor
pointe peak hors off mid heures hours heure hour hiver winter ete summer
tou time
kwh kw kva kvar mwh wh gj m3 m³ mcf ccf therm therms btu litres litre
kilowattheure kilowattheures kilowatt kilowatts kilowatthour kilowatthours
temperature degres degre
reseau network grid acces access systeme system
carbone carbon spede climat climate
tier tiers palier paliers baseline generation transmission franchise surcharge
indifference commission users utilisateurs program programs programme
loss pertes adjusted ajuste ajustee multiplicateur
contribution tarifaire accise ticgn cta cspe turpe taxes prelevement preleve
naturels naturelle
domestique residential residentiel residentielle commercial general generale
dt dp d m g flex rpp tou
# --- currency / units ---
cad usd eur dollars dollar cents cent
# --- address labels only (never street or city names) ---
adresse address desservie service lieu location
proprietaire owner locataire tenant titulaire holder
# --- utilities and their generic name words (organisations, not people) ---
hydro quebec hydroquebec energir ontario
# --- misc labels ---
voir see details detaille suite continued plus loin follow follows ci dessous below
presente present presentes cette ci www com
"""

VOCABULARY: frozenset[str] = frozenset(
    fold(word)
    for line in _WORDS.splitlines()
    if not line.lstrip().startswith("#")
    for word in line.split()
)
