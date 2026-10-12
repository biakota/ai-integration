# NOTES

## En bref

| | |
|---|---|
| **Ticket 1** | `bills/parsing/hydroquebec.py` lit les 5 PDF Hydro-Québec à couche texte comme `ground_truth.json` (vérifié en test). Il décline tout le reste (scan, autre fournisseur, image) et ne met `parsed` que si **tous** les recoupements de la facture concordent. |
| **Ticket 2** | `bills/parsing/model.py` : texte local (couche PDF ou OCR local) → **pseudonymisation par liste blanche** (`bills/privacy/redact.py`) → **garde de sortie** (`bills/privacy/guard.py`) → modèle → **validation** (`bills/ai/validate.py`). Toujours `needs_review`. |
| **Preuve RP** | `bills/tests/test_privacy.py` téléverse **chaque échantillon** par l'API et vérifie qu'aucune des `personal_information` de `ground_truth.json` (ni variante : casse, accents, groupement de chiffres, mot isolé) ne figure dans ce qui serait sorti. |
| **Ticket 3** | Plus bas. |

```bash
cd backend
python manage.py test                                    # 50 tests, AI_PROVIDER=fake, ~7 s
RUN_OCR_TESTS=1 python manage.py test bills.tests.test_real_ocr   # même preuve sur la sortie de RapidOCR (lent)
python manage.py evaluate_samples                        # pipeline réel (OCR + modèle de .env) vs ground truth
AI_PROVIDER=ollama python manage.py evaluate_samples --only ovpl
```

Branches : `ticket-1`, `ticket-2`, `final` (= tout + ces notes).

---

## Décisions

### Ticket 1 — lecteur Hydro-Québec

- **Décliner plutôt que deviner.** Le parser renvoie `None` si : plusieurs documents, autre chose qu'un PDF, pas de couche texte, pas les marqueurs « Hydro-Québec » + « N° de compte / Account No. », **plusieurs sections « Détail des coûts »** (plusieurs contrats/compteurs : une seule entrée ne peut pas les représenter), ou si la période, la consommation ou le sous-total manquent. Le parser suivant (modèle) prend alors le relais.
- **Règle `parsed` vs `needs_review`.** Une facture HQ imprime plusieurs fois la même information. `parsed` seulement si tout concorde :
  - même n° de compte sur chaque page et sur le talon ;
  - période FR (jj-mm-aaaa) = période EN (mm-jj-aaaa), ce qui lève l'ambiguïté jour/mois ;
  - `fin − début` = nombre de jours imprimé ;
  - même période dans les sections consommation et coûts ;
  - consommation totale = somme des différences de compteur ;
  - lignes de coût = sous-total ;
  - sous-total = « Coûts de l'électricité » de la page 1 ;
  - sous-total + TPS + TVQ = total ;
  - tarif connu (D, DP) ;
  - puissance trouvée si le tarif est à la puissance.

  Un seul écart suffit pour `needs_review`, avec la raison dans `review_notes`.
- **Le nom du client n'est jamais bloquant.** Son extraction dépend de l'ordre du texte. S'il est introuvable ou diffère du talon, on ajoute un avertissement, sans décliner.
- **Fin exclusive.** La date « au » d'HQ est déjà exclusive (60 jours du 10-04 au 09-06). On le vérifie à chaque facture au lieu de le supposer.
- **`billed_power`** = la puissance à facturer (62 kW dans « (62 kW – 50 kW) »), conformément à `ground_truth.json`. Les 12 kW sont la part au-delà du seuil, utile pour le coût mais pas pour modéliser le bâtiment.
- **Contrôles communs à tous les parsers** (`services.check_against_bill`) : n° de compte ≠ celui de la facture (mauvais compte ?), unité ≠ unité de la facture (facture de gaz téléversée sur l'électricité), chevauchement avec une entrée existante (doublon). Chacun force `needs_review`. Le n° de compte existant n'est **jamais écrasé**.
- **Modèle** : ajout de `BillEntry.review_notes` (JSON, migration `0002`), exposé en lecture seule par l'API et affiché sur la page de révision. Petit changement au frontend, parce qu'un `needs_review` sans raison oblige le réviseur à tout revérifier.

### Ticket 2 — voie modèle et renseignements personnels

**Ce qui est un renseignement personnel sur une facture** : nom (personne ou entreprise), adresses (facturation et lieu desservi), n° de compte, de client, de facture, de contrat et de compteur, ligne de lecture optique du talon, téléphone, courriel. S'y ajoute la **combinaison** adresse + historique de consommation, qui révèle l'occupation d'un logement. Le modèle ne reçoit ni nom, ni adresse, ni identifiant. La consommation qu'il voit ne peut donc être rattachée à personne.

**Pourquoi une liste blanche et pas de la détection.** Les noms et les adresses n'ont pas de forme fiable, et l'OCR abîme celles qui en ont une (« K0K 1T1 » devient « KOK 171 », « Jean-Éloi » devient « Jean-Eloi »). Plutôt que de chercher les RP, on ne laisse passer que ce qui est **démontrablement inoffensif** :
- les mots d'un vocabulaire de facturation relu comme du code (`vocabulary.py`) ;
- les montants, les dates et les pourcentages ;
- les nombres de moins de 7 chiffres (au-delà, ce sont des identifiants) ;
- un nombre suivi d'une unité ;
- les codes courts du type « D1 ».


**Garantie en deux couches indépendantes.**
1. `redact.py` transforme le texte.
2. `PrivacyGuardedClient` revérifie la requête finale juste avant l'envoi : aucune image, chaque jeton dans la liste blanche, aucune RP connue. En cas d'échec, une exception est levée et rien ne part.

`get_llm_client()` renvoie **toujours** le client gardé, quel que soit le fournisseur. La garantie ne dépend donc ni de l'endroit où tourne le modèle, ni de l'absence de bug dans la rédaction. Le garde journalise le *type* de problème, jamais le texte.

**Autres choix :**
- **Texte seulement, jamais d'image.** On ne peut pas prouver qu'une image ne contient pas de RP. L'OCR est local (RapidOCR fourni). Un modèle de vision *local* serait défendable, mais demanderait une exception explicite au garde. Je ne l'ai pas faite.
- **On ne demande pas au modèle le nom ni le n° de compte.** On n'en a pas besoin pour modéliser un bâtiment (minimisation). Le n° de compte connu est vérifié **localement** dans le texte complet : s'il est absent, une note « mauvaise facture ? » est ajoutée.
- **Ne pas faire confiance au modèle** (`validate.py`) :
  - chaque valeur doit être **imprimée** dans le texte que le modèle a vu (montants et dates comparés dans tous leurs formats FR/EN) ;
  - une valeur non retrouvée est **effacée**, pas gardée « pour révision » : un chiffre plausible inventé est pire qu'un champ vide, parce qu'un réviseur survole ce qui est déjà rempli ;
  - le coût peut être **calculé** (OVPL : sous-total − remise de l'Ontario = 147,03 $, montant imprimé nulle part) seulement si le modèle liste les montants imprimés qu'il a combinés et que la somme tombe juste ;
  - autres contrôles : nombre de jours (une fin inclusive est convertie en exclusive, avec une note), ordre des dates, durée plausible, prix unitaire plausible par unité, et une ligne de taxe imprimée doit correspondre à coût × un taux connu (sinon « le coût inclut-il les taxes ? »).
- **Toujours `needs_review`** : aucune précision n'est encore mesurée par fournisseur. La `confidence` est **calculée** (champs retrouvés × 0,9 par note), jamais auto-déclarée par le modèle.
- **Réponse inutilisable** (pas de JSON, aucune valeur retrouvée, modèle indisponible, requête bloquée par le garde) → `unparsed`, donc saisie manuelle, comme aujourd'hui.
- **Modèle** : `OllamaClient` (`AI_PROVIDER=ollama`, `qwen2.5:7b` par défaut), `/api/chat` avec schéma JSON imposé et température 0. Pas de nouvelle dépendance (urllib).
- **Coût par facture** :
  - entrée ≈ 1 500 caractères de consignes + 0,5 à 4 k caractères de facture pseudonymisée, soit **~0,6 à 1,5 k jetons** ; sortie ~150 jetons ;
  - en local (Ollama) : 0 $, mais 1 à 2 min par facture sur un CPU de portable (ordre de grandeur donné par le README) ;
  - avec un petit modèle hébergé : ce volume de jetons coûte une fraction de cent par facture. C'est acceptable, puisque la charge utile ne contient aucune RP. Je préférerais quand même un fournisseur sans rétention des données.

### Ce que je n'ai pas pu exécuter (à lire)

- **RapidOCR** : ses modèles se téléchargent au premier appel, et mon environnement de développement n'y avait pas accès. J'ai donc enregistré la sortie d'**OCR Tesseract** des images comme fixtures (`tests/fixtures/ocr_lines.json`, documentée comme telle). Les tests rejouent ces lignes. C'est un bon substitut (même bruit : accents perdus, codes postaux abîmés, signe moins perdu sur la remise OVPL), mais pas la sortie réelle. `test_real_ocr` (opt-in) refait la preuve RP sur RapidOCR.
- **Vrai modèle** : je n'ai pas pu lancer Ollama dans cet environnement. La voie modèle est conçue et testée contre le client factice (exigence du README). Les tests vérifient qu'une réponse correcte survit à la validation sur **chaque** échantillon, OCR compris, donc que la pseudonymisation laisse tout ce dont le modèle a besoin.
- **À COMPLÉTER avant l'envoi** : résultats de `AI_PROVIDER=ollama python manage.py evaluate_samples` (exactitude par champ, temps par facture, et ligne « PII sent: NONE »).

### Essai sur des mises en page pour lesquelles le code n'a pas été écrit

J'ai reconstruit les étiquettes de spécimens publics :
- facture TOU de [Toronto Hydro](https://www.torontohydro.com/for-home/tou-sample-bill) ;
- glossaire de facture [PG&E](https://civil.colorado.edu/~silverst/aren2110/pge%20sample%20utility%20bill.pdf) ;
- guides Engie / [TotalEnergies](https://www.totalenergies.fr/particuliers/gaz/gaz-le-guide/facture-gaz/comprendre-sa-facture-de-gaz) pour la France.

Mon outil de lecture web ne rendait que des résumés, pas le texte brut des PDF : c'est donc un essai de la **rédaction**, pas de l'extraction de bout en bout. Ce que j'ai appris :
- **PG&E imprime « 388.000000 kWh »** : la rédaction le prenait pour un identifiant et la consommation disparaissait. Corrigé, avec un test de régression.
- **Le vocabulaire est régional.** Il manquait Rate *Class*, Tier, Baseline, Index, Accise, CTA, ¢… Le coût d'un mot manquant est une moins bonne extraction, jamais une fuite. C'est le bon sens d'erreur, mais il faut surveiller le taux de `[•]` par fournisseur.
- **Ambiguïtés métier, pas techniques :**
  - en France, le gaz est facturé en **kWh** (m³ × coefficient de conversion), alors que le modèle `Bill` n'accepte que m³ pour le gaz ;
  - aux États-Unis, il est en **therms** ;
  - en Ontario, il existe des kWh **ajustés pour les pertes** à côté des kWh mesurés. Le prompt demande maintenant la consommation mesurée.

  Il faut une décision produit sur les unités canoniques.
- **Le spécimen officiel HQ tarif DP** (`samples/hydro-quebec/specimens/`) diffère des PDF synthétiques : section « Détail de la puissance », multiplicateur de compteur, puissance décimale (51,5 kW). Le parser est validé **uniquement** sur les synthétiques. Avant la production, il faut le tester sur de vrais PDF du portail (avec consentement). D'ici là, il déclinera ou passera en révision, et c'est voulu.

---

## Constats sur le code existant

Par ordre de gravité. Je n'ai corrigé que ce qui touchait directement les RP de mon travail ; le reste mérite des PR séparées.

1. **Contrôle d'accès absent sur les objets (IDOR).** Seul `GET /api/buildings/` filtre par propriétaire. Le détail d'un bâtiment, l'ajout de facture, le **téléversement**, la saisie et `GET/PUT /api/entries/{id}/` acceptent n'importe quel id : Bob peut lire et modifier les factures d'Alice, documents compris. C'est la plus grosse fuite de RP de l'application, bien avant le modèle. Correctif : `get_queryset()` filtré par `building__owner` partout, plus des tests. *Non corrigé.*
2. **`/media/` servi sans authentification** (`static()` dans `config/urls.py`), avec des chemins prévisibles (`bills/<nom original>`) : toute facture téléversée est publique pour qui connaît l'URL. *Non corrigé.*
3. **Journaux.**
   - `process_upload` écrivait le **texte complet** de chaque facture dans `logs/app.log` au niveau DEBUG (actif par défaut) ;
   - le `ParsedEntry` journalisé contenait nom et n° de compte ;
   - le nom de fichier téléversé est journalisé (« facture-jean-tremblay.pdf »).

   Or les journaux partent souvent vers des services tiers (Datadog, Sentry). *Les deux premiers sont corrigés* (`repr=False` sur les champs personnels) ; le troisième ne l'est pas.
4. **`BillDocument.raw_text`** duplique tout le contenu de la facture en base, sans durée de conservation.
5. **Traitement synchrone dans la requête HTTP.** Avec OCR + modèle local, cela peut prendre une à deux minutes. De plus, une exception d'un parser renvoyait une 500 après la création de l'entrée. *Exception attrapée dans `registry.parse`*, mais le reste relève du ticket 3.
6. **Champs de compte copiés « seulement s'ils sont vides »** : un document d'un autre compte passait silencieusement. *Maintenant signalé.*
7. `Bill.customer_name` est stocké alors qu'il ne sert pas à la modélisation (question de minimisation). Les unités possibles (kWh, m³) ne couvrent ni les therms ni les GJ, ni le gaz français en kWh.
8. Mineurs :
   - `RUNNING_TESTS = "test" in sys.argv` ;
   - jeton dans `localStorage` ;
   - `DEBUG`, `ALLOWED_HOSTS=*`, CORS ouvert (normal pour l'exercice) ;
   - `PUT` confirme une entrée quel que soit son statut ;
   - `ground_truth` donne `rate_code: "RPP-TOU"`, qui n'est imprimé nulle part. Il manque une taxonomie canonique des tarifs.

## Ce que je contesterais sur un vrai ticket

- **Auto-confiance des extractions par modèle** : pas avant d'avoir une précision mesurée par fournisseur et par champ, à partir des corrections humaines.
- **« Une facture = une entrée »** : les factures multi-contrats ou multi-compteurs et les changements de tarif en cours de période existent. Il faut pouvoir produire plusieurs entrées ou au moins le signaler.
- **Stocker le nom du client** si personne ne s'en sert.
- **Prioriser l'IDOR et `/media/` avant de brancher un modèle** : la contrainte RP est violée aujourd'hui sans aucun service tiers.

## Ce que je ferais ensuite

1. Lancer `evaluate_samples` avec Ollama et RapidOCR, et compléter les résultats ci-dessus. Ajuster le prompt et le vocabulaire selon les erreurs.
2. Corriger l'IDOR et `/media/` (PR séparées, avec tests).
3. Traitement asynchrone : statut `processing` et file de tâches (ticket 3).
4. Recycler le parser HQ sur le texte OCR, avec les **mêmes** recoupements. Si tout concorde sur une photo, c'est assez fiable pour se passer du modèle.
5. Mesurer le taux de `[•]` par fournisseur pour repérer les trous du vocabulaire. Ajouter des spécimens publics (Énergir, Hydro One, Hydro Ottawa, Con Edison, Engie) comme jeu de non-régression.
6. Conservation : purger `raw_text` et les originaux après confirmation, selon une politique à définir.

---

## Ticket 3 — Mise en production (des milliers de factures par mois)

**Flux des RP.**
- **Où elles vivent :** originaux dans un stockage objet **privé** au Canada (chiffré, clés gérées), servis uniquement par URL signée de courte durée après contrôle d'accès ; base de données au Canada, chiffrée.
- **Qui les voit :** le propriétaire du bâtiment et le personnel habilité, avec journal d'audit des consultations.
- **Ce qui sort :** **uniquement** le texte pseudonymisé et vérifié par le garde, vers le modèle. De préférence un modèle auto-hébergé dans notre VPC (vLLM ou Ollama sur GPU). Sinon, un fournisseur sous contrat sans rétention ni entraînement : par conception, il ne reçoit rien de personnel, mais on réduit tout de même la surface.
- **Combien de temps :** pas de texte brut ni d'OCR persistés au-delà du traitement (ou chiffrés, 30 jours, pour le débogage) ; originaux purgés N jours après confirmation, sauf consentement explicite ; valeurs extraites conservées (ce sont nos données métier) ; journaux sans contenu de document, avec un test qui le vérifie.

**Exécution.** Asynchrone.
- Le téléversement crée l'entrée en `processing` et renvoie 202. Le frontend interroge le statut ou reçoit une notification.
- Une file (Celery/RQ ou une file Postgres) alimente des workers OCR (CPU) et modèle (GPU), séparés pour les dimensionner indépendamment.
- Délais : OCR ~30 s par page, modèle ~60 s.
- Reprises avec backoff exponentiel **seulement** pour les erreurs transitoires (réseau, 5xx, délai dépassé). Une réponse invalide ou un blocage du garde n'est pas une erreur transitoire : on passe directement en `unparsed`.
- Idempotence par `entry_id` + empreinte du document ; file d'échec visible.
- On enregistre sur chaque entrée la version du parser, du modèle et du prompt, pour pouvoir rejouer.

**Rester exact dans six mois.**
- Chaque correction humaine est une étiquette gratuite. Tableau de bord par fournisseur et par champ : écart extrait → confirmé, taux de `needs_review`, taux de déclin du parser HQ, taux de valeurs effacées par la validation, taux de `[•]`.
- Un changement de mise en page HQ se voit comme un **pic de déclins**. Grâce au repli sur le modèle et aux recoupements, il dégrade la qualité au lieu de produire des valeurs fausses en silence.
- Alertes sur ces taux.
- Un jeu « doré » (spécimens publics + synthétiques), exécuté en CI à chaque changement de prompt, de modèle ou de vocabulaire, plus un canari lors des mises à jour du modèle.
- Échantillonnage aléatoire de quelques entrées `parsed` pour une revue humaine, afin de mesurer aussi la confiance accordée par le déterministe.

**Quand écrire un parser déterministe.** Quand un fournisseur pèse lourd en volume (au Québec, HQ et Énergir couvrent l'essentiel) **et** que ses PDF ont une couche texte stable. Ou quand les corrections montrent que le modèle s'y trompe souvent. Ou quand on veut l'auto-confiance (`parsed`) : seul un parser qui recoupe les totaux imprimés la justifie. Le modèle reste le filet pour la longue traîne. Les données de corrections disent lequel écrire ensuite.

## Temps passé

**À COMPLÉTER.** Indication : lecture et installation ~30 min, ticket 1 ~75 min, ticket 2 ~2 h (dont l'essai sur d'autres mises en page), notes ~40 min.