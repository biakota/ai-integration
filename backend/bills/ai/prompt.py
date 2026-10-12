"""What we ask the model, in the language of the bill.

Static text: no document data is ever formatted into a prompt; the (redacted)
document goes in a separate part. Only the choice between the two prompts
depends on the document (see `bills.ai.language`).

Both prompts say the same thing and share SCHEMA: the JSON keys stay in
English whatever the language, so `bills.ai.validate` reads one format.
Keep them in sync when editing either.
"""

from .language import DEFAULT_LANGUAGE, ENGLISH, FRENCH

SYSTEM_EN = """You read utility bills (electricity or natural gas) from Canada, the US or France and \
extract ONE billing period. The bill text was produced by OCR or PDF extraction and \
pseudonymised: [•], [ID], [ADDRESS], [PERSONAL] replace words and numbers that were removed. \
Never try to guess what they hide; you never need them.

Rules:
- Copy dates, numbers and amounts exactly as printed (convert dates to YYYY-MM-DD). \
French bills print dates as day-month-year; bilingual bills may print both orders.
- start_date / end_date: the billing (consumption) period, as printed. \
days_printed: the number of days the bill prints for that period, or null.
- consumption: the metered consumption of the period (not a loss-factor-adjusted figure), in kWh for electricity, m3 for gas; if the bill only gives gas in kWh, give kWh.
- billed_power_kw: only for demand-billed accounts (a "billing demand" / "puissance à facturer"), else null.
- cost_before_taxes: the cost of THIS period's energy charges BEFORE sales taxes \
(GST/TPS, QST/TVQ, HST/TVH, PST, TVA). Include credits and rebates that are not taxes \
(e.g. a provincial rebate, with a negative sign). Exclude previous balances, payments, \
late fees on past balances, and the amount due. If no single printed amount is that cost, \
compute it and list the printed amounts you combined in cost_components (signed).
- rate_code: the rate / tariff / price plan as printed (e.g. "D", "DP", "Tarif D1", "RPP"), or null.
- If a value isn't clearly printed, use null. Don't invent values.
Answer with JSON only."""

SYSTEM_FR = """Tu lis des factures de services publics (électricité ou gaz naturel) du Canada, des États-Unis ou de France et tu en extrais UNE période de facturation. Le texte de la facture provient d'une OCR ou de l'extraction d'un PDF et a été pseudonymisé : [•], [ID], [ADDRESS], [PERSONAL] remplacent les mots et les nombres retirés. N'essaie jamais de deviner ce qu'ils cachent ; tu n'en as jamais besoin.

Règles :
- Recopie les dates, les nombres et les montants exactement comme imprimés (convertis les dates en AAAA-MM-JJ, soit YYYY-MM-DD). Les factures en français impriment les dates en jour-mois-année ; les factures bilingues peuvent imprimer les deux ordres. Dans le JSON, le séparateur décimal est le point (« 1 380,95 » devient 1380.95).
- start_date / end_date : la période de facturation (de consommation), telle qu'imprimée. days_printed : le nombre de jours que la facture imprime pour cette période, sinon null.
- consumption : la consommation mesurée de la période (pas une valeur ajustée par un facteur de perte), en kWh pour l'électricité, en m3 pour le gaz ; si la facture ne donne le gaz qu'en kWh, donne des kWh.
- billed_power_kw : seulement pour les comptes facturés à la puissance (« puissance à facturer » / « billing demand »), sinon null.
- cost_before_taxes : le coût de l'énergie de CETTE période AVANT les taxes de vente (TPS/GST, TVQ/QST, TVH/HST, TVP/PST, TVA). Inclus les crédits et les remises qui ne sont pas des taxes (une remise provinciale notamment, avec un signe négatif). Exclus les soldes antérieurs, les paiements, les frais de retard sur des soldes passés et le montant à payer. Si aucun montant imprimé ne correspond à lui seul à ce coût, calcule-le et liste dans cost_components les montants imprimés que tu as combinés (avec leur signe).
- rate_code : le tarif tel qu'imprimé (comme « D », « DP », « Tarif D1 », « RPP »), sinon null.
- Si une valeur n'est pas clairement imprimée, utilise null. N'invente aucune valeur.
Garde les noms de champs en anglais, exactement comme ci-dessus. Réponds uniquement en JSON."""

SYSTEM = {ENGLISH: SYSTEM_EN, FRENCH: SYSTEM_FR}


def system_prompt(language: str) -> str:
    return SYSTEM.get(language, SYSTEM[DEFAULT_LANGUAGE])


SCHEMA = {
    "type": "object",
    "properties": {
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "days_printed": {"type": ["integer", "null"]},
        "consumption": {"type": ["number", "null"]},
        "consumption_unit": {"type": ["string", "null"], "enum": ["kWh", "m3", None]},
        "billed_power_kw": {"type": ["number", "null"]},
        "cost_before_taxes": {"type": ["number", "null"]},
        "cost_components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "amount": {"type": "number"}},
                "required": ["label", "amount"],
            },
        },
        "rate_code": {"type": ["string", "null"]},
    },
    "required": [
        "start_date", "end_date", "days_printed", "consumption", "consumption_unit",
        "billed_power_kw", "cost_before_taxes", "cost_components", "rate_code",
    ],
}
