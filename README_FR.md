# vadiMAP — Test technique Backend / Intégration IA

*English version: [README_EN.md](./README_EN.md)*

Bienvenue, et merci de prendre le temps de faire l'exercice. Un rythme
suggéré (~3h45 au total) est dans la section **Tickets** plus bas — ce sont
des indications, pas une limite stricte. Si vous vous voyez aller nettement
au-delà, arrêtez et notez ce que vous auriez fait ensuite dans votre
`NOTES.md`.

## À propos des outils d'IA

On utilise l'IA beaucoup au quotidien et on ne vous décourage pas de
l'utiliser ici. Ce qu'on relit, c'est votre code final et votre `NOTES.md`
— pas comment vous y êtes arrivé. Si l'IA vous permet de finir vite,
profitez du temps qui reste pour ralentir : planifiez, contestez les
suggestions qui ne vous semblent pas justes, esquissez des alternatives
dans vos notes.

Notre base de code est antérieure aux LLM, donc une grande partie de notre
travail consiste à retravailler du code écrit sans IA. Les personnes
capables de signaler un problème, d'en esquisser la solution et d'accepter
que le vrai correctif appartienne peut-être à une PR de suivi correspondent
mieux à notre réalité que celles qui se précipitent dans une réécriture.

## Contexte

vadiMAP aide les propriétaires de bâtiments à planifier leurs rénovations
énergétiques. Pour ça, on a besoin de leurs **factures d'énergie** —
électricité, gaz — sous forme de données structurées : période de
facturation, consommation, montants. Aujourd'hui, quelqu'un les saisit à la
main.

Ce dépôt est une petite application Django + React calquée sur la nôtre :

- Un **bâtiment** a des **factures** (`Bill`) — une par compte de
  fournisseur (son électricité Hydro-Québec, son gaz, …).
- Une facture a des **entrées** (`BillEntry`), une par période de
  facturation : une année de factures, c'est typiquement 6 entrées
  bimestrielles ou 12 mensuelles.

On peut déjà **téléverser** un fichier de facture, ce qui ajoute une entrée
à l'une des factures d'un bâtiment, **saisir** une entrée à la main, et
**réviser** les entrées. Les téléversements passent par une chaîne
d'analyse — mais aucun analyseur n'existe encore, donc chaque entrée
téléversée finit en `unparsed`. Votre travail : faire en sorte que
l'application lise vraiment les factures.

```
backend/    Django 5 + DRF, SQLite, utilisateurs, bâtiments et une année de factures préinsérés
frontend/   React (Vite, JS) — fourni, vous ne devriez pas avoir à y toucher
samples/    Factures d'exemple synthétiques + ground_truth.json
```

## ⚠️ Renseignements personnels — une contrainte ferme

Les factures d'énergie contiennent des renseignements personnels. Notre
politique d'entreprise, plus stricte que ce qu'exige la Loi 25 :

> **Aucun renseignement personnel ne peut être envoyé à un service tiers**
> — API de LLM hébergées et API d'OCR hébergées comprises.

Ce qui constitue un renseignement personnel sur une facture, où ces
renseignements circulent dans l'application, et comment vous *garantissez*
que la règle est respectée font partie de l'exercice. Les modèles hébergés
ne sont pas interdits — leur envoyer des renseignements personnels l'est.

Les factures d'exemple sont synthétiques — personnes, adresses, comptes et
montants inventés — mais **traitez-les comme de vraies factures de
clients.**

## Installation

Il vous faut **Python 3.11+** et **Node 20+**.

### macOS / Linux / WSL

```bash
./setup.sh        # .env, venv, dépendances, migrations, seed, npm install
```

Puis, dans deux terminaux :

```bash
# Terminal 1 — backend sur http://localhost:8000
cd backend && source .venv/bin/activate && python manage.py runserver

# Terminal 2 — frontend sur http://localhost:5173
cd frontend && npm run dev
```

### Windows (PowerShell)

```powershell
.\setup.ps1
```

```powershell
# Terminal 1
cd backend; .\.venv\Scripts\Activate.ps1; python manage.py runserver

# Terminal 2
cd frontend; npm run dev
```

> WSL fonctionne aussi — suivez les instructions macOS / Linux dans votre
> shell WSL.

> Vous installez à la main plutôt qu'avec le script ? Après `pip install -r
> requirements.txt`, lancez aussi les deux lignes OpenCV de `setup.sh` :
> elles installent la version « headless » d'OpenCV, dont l'OCR a besoin
> sous Linux / WSL.

Ouvrez http://localhost:5173. Le serveur de dev Vite redirige `/api/*` et
`/media/*` vers Django. Si le port 8000 est occupé, lancez Django sur un
autre port (`python manage.py runserver 8001`) et démarrez Vite avec
`BACKEND_URL=http://localhost:8001 npm run dev`. Lancez les tests avec `python manage.py test`
depuis `backend/`.

### Authentification et données préinsérées

Authentification par jeton DRF avec le mot-clé `Bearer` ;
`POST /api/auth/login/` avec `{"username", "password"}` renvoie un jeton.
Le menu « Acting as » dans l'en-tête vous connecte comme l'un des
utilisateurs préinsérés : `admin` (superutilisateur), `alice`, `bob` —
**tous avec le mot de passe `takehome`**.

La base de données contient déjà **3 bâtiments** (2 pour Alice, 1 pour Bob),
chacun avec une année d'entrées de factures saisies à la main, pour montrer
à quoi ressemblent les données. Pour faire la démonstration de votre
travail, **créez un nouveau bâtiment** depuis la page d'accueil, ajoutez-lui
une facture et téléversez-y les exemples.

Swagger UI est sur http://localhost:8000/api/docs/ (cliquez sur
« Authorize » et collez le jeton brut). L'admin Django est sur
http://localhost:8000/admin/.

> **Hors périmètre :** formulaire de connexion, inscription, expiration des
> jetons, modification des utilisateurs préinsérés (le frontend les code en
> dur).

## Fonctionnement actuel de l'application

| Endpoint | Rôle |
|---|---|
| `GET /api/buildings/` | Vos bâtiments, avec un résumé de leurs factures. |
| `POST /api/buildings/` | Crée un bâtiment qui vous appartient. |
| `GET /api/buildings/{id}/` | Un bâtiment, ses factures et toutes leurs entrées. |
| `POST /api/buildings/{id}/bills/` | Ajoute une facture (compte de fournisseur) à un bâtiment. |
| `POST /api/bills/{id}/upload/` | Multipart, un ou plusieurs `files` (un PDF, ou une image par page). Les enregistre dans une nouvelle entrée, lance la chaîne d'analyse, renvoie l'entrée. |
| `POST /api/bills/{id}/entries/` | Saisie manuelle. Crée une entrée `confirmed` avec `source=manual`. |
| `GET /api/entries/{id}/` | Une entrée, avec ses documents. |
| `PUT /api/entries/{id}/` | Une personne corrige une entrée extraite → `confirmed`. |

Sur une entrée, `end_billing_period` est **exclusive** (une période
facturée du 1er au 31 janvier se termine le 1er février, donc
`end − start` est le nombre de jours facturés) et `bill_cost` est le coût
**avant taxes**.

La chaîne d'analyse vit dans `backend/bills/` :

- `services.process_upload()` — extrait la couche texte des PDF, construit
  un `DocumentInput` par fichier, lance les analyseurs, copie le résultat
  sur la `BillEntry` (et remplit le numéro de compte / le tarif de la
  facture s'ils sont vides), et fixe le statut de l'entrée.
- `parsing/base.py` — `DocumentInput`, `ParsedEntry` et le protocole
  `BillParser`. `parsing/registry.py` — la liste ordonnée `PARSERS` (vide
  aujourd'hui).
- `extraction/ocr.py` — un **utilitaire d'OCR local** prêt à l'emploi
  (RapidOCR, s'exécute sur votre machine) : `ocr_lines(image)` renvoie les
  lignes de texte d'une page, de haut en bas, redressées pour les photos
  légèrement inclinées ; `pdf_page_images(path)` rend les pages d'un PDF
  (pour les numérisations sans couche texte). Il n'est pas branché dans la
  chaîne d'analyse. Le premier appel prend quelques secondes (chargement des
  modèles), puis quelques secondes par page.
- `ai/client.py` — une petite interface `LLMClient` et un `FakeLLMClient`
  qui renvoie des réponses préparées et **enregistre chaque requête qu'il
  reçoit**. `get_llm_client()` choisit le client selon `AI_PROVIDER` dans
  `.env`.

Le `status` d'une entrée pilote l'écran de révision : `unparsed` (rien n'a
pu la lire), `needs_review` (extraite, une personne doit vérifier),
`parsed` (extraite, fiable), `confirmed` (vérifiée par une personne).
`source` indique qui l'a remplie : `manual`, `deterministic` ou `ai`.

Ces structures sont un point de départ. Changez-les si votre conception
l'exige — gardez simplement les champs qu'affiche le frontend, et
expliquez pourquoi dans `NOTES.md`.

### Exemples

`samples/ground_truth.json` liste chaque exemple avec ses valeurs attendues
— les champs du compte sous `bill`, la période de facturation sous `entry` —
(formes canoniques : dates ISO, chaînes décimales `"1234.56"`, numéros de
compte sans séparateurs) et les renseignements personnels qui y figurent.

- `hydro-quebec/pdf/` — des factures Hydro-Québec **synthétiques** que nous
  avons générées : elles reproduisent la mise en page des spécimens publics
  d'Hydro-Québec, avec une couche texte comme les PDF téléchargés depuis
  l'Espace client, mais toutes les valeurs sont inventées. Plus un PDF
  numérisé sans couche texte.
- `hydro-quebec/images/` — les mêmes factures synthétiques en capture
  d'écran et en photo prise au téléphone (une image par page).
- `hydro-quebec/specimens/` — les spécimens **officiels** publiés par
  Hydro-Québec sur hydroquebec.com. Des gabarits sans valeurs ; pour
  référence de mise en page seulement.
- `other-utilities/` — des factures synthétiques de deux fournisseurs
  **fictifs** avec des mises en page différentes.

On fournit l'utilitaire d'OCR parce qu'écrire la plomberie d'OCR en dit peu
sur votre jugement aujourd'hui. Utilisez-le, remplacez-le ou ignorez-le — ce
qu'on regarde, c'est ce que vous faites de sa sortie.

## Tickets

### Rythme suggéré

- Lecture + installation : ~30 min
- Ticket 1 : ~75 min
- Ticket 2 : ~90 min
- Ticket 3 + `NOTES.md` : ~30 min

### Vue d'ensemble

- **Les tickets 1 et 2 sont obligatoires** — merci d'implémenter les deux.
- **Le ticket 3 est écrit seulement**, dans `NOTES.md`.

Merci de faire des commits entre les tickets pour qu'on puisse suivre votre
progression. Si quelque chose est ambigu, **faites un choix raisonnable et
documentez-le dans `NOTES.md`**.

**Corriger les bogues du code existant est hors périmètre.** Cela dit, en
équipe, on documente toute observation ou préoccupation sur le code dans
lequel on travaille — merci de lister les vôtres dans `NOTES.md`.

### Ticket 1 — Lecteur déterministe Hydro-Québec

Les factures Hydro-Québec téléchargées depuis l'Espace client sont des PDF
avec une couche texte et une mise en page stable. Les lire ne demande pas
de modèle.

Construisez un analyseur déterministe pour les factures PDF Hydro-Québec
et branchez-le dans la chaîne d'analyse, de sorte que téléverser l'un des
fichiers de `samples/hydro-quebec/pdf/` remplisse l'entrée avec
`source=deterministic`.

- Il doit extraire correctement les champs pour chaque exemple
  PDF Hydro-Québec qui a une couche texte — vérifiez-les contre
  `ground_truth.json` **dans des tests**.
- Il doit **décliner** ce qu'il ne sait pas lire (autres fournisseurs,
  numérisations, …) plutôt que deviner, pour laisser sa chance à
  l'analyseur suivant.
- Décidez quand un résultat est fiable (`parsed`) ou `needs_review`, et
  expliquez la règle.

### Ticket 2 — Tout le reste, avec un modèle

Le lecteur déterministe ne sait pas traiter les photos, les numérisations
ni les autres fournisseurs. Ajoutez une voie d'extraction qui utilise un
modèle — approche de votre choix : modèle hébergé ou local, OCR + LLM,
modèle de vision, ou un mélange.

- **La contrainte sur les renseignements personnels ci-dessus
  s'applique.** Montrez comment votre conception la garantit, et prouvez-le
  avec un test.
- Ne faites pas confiance au modèle aveuglément : décidez ce que vous
  vérifiez avant d'accepter sa sortie, et ce qui se passe quand il se
  trompe ou n'est pas sûr.
- Nos exemples ne couvrent pas tous les fournisseurs. **On vous encourage à
  trouver les vôtres** : beaucoup de fournisseurs publient des spécimens de
  facture commentés (« comprendre ma facture »), au Québec, ailleurs au
  Canada, aux États-Unis ou en France. Essayer votre conception sur une mise
  en page pour laquelle vous ne l'avez pas construite en dit long —
  dites-nous ce que vous avez essayé et ce que vous en avez appris.
  Utilisez uniquement des spécimens publics, jamais la facture d'une
  personne réelle.
- **Votre rendu doit fonctionner, et ses tests passer, avec
  `AI_PROVIDER=fake`** — on le relira sans aucune clé d'API.
- On ne fournit pas de clé d'API et **on ne s'attend pas à ce que vous
  dépensiez quoi que ce soit**. Concevoir et tester avec le faux client est
  une réponse complète. Pour essayer un vrai modèle gratuitement, le plus
  simple est un **modèle local avec [Ollama](https://ollama.com)** — par
  exemple `ollama pull qwen2.5:7b` (≈ 5 Go), servi sur
  `http://localhost:11434`. Il fonctionne sans GPU, mais lentement : sur le
  processeur d'un portable, comptez 1 à 2 minutes par facture, donc
  essayez quelques exemples plutôt que tous. Une offre gratuite d'un
  fournisseur ou une clé que vous avez déjà conviennent aussi, tant que la
  règle sur les renseignements personnels est respectée. Dans tous les
  cas, dites-nous quel modèle, comment il s'en est sorti sur les exemples,
  et ce qu'il coûterait à peu près par facture.

### Ticket 3 — Production *(écrit seulement)*

Dans `NOTES.md`, une page maximum. Supposons que ça passe en production
pour des milliers de factures par mois :

- **Circulation des renseignements personnels :** où sont-ils stockés, qui
  peut les voir, qu'est-ce qui sort de notre infrastructure, combien de
  temps garde-t-on quoi ?
- Comment **exécuteriez**-vous l'extraction (synchrone ou asynchrone,
  reprises, délais d'expiration) ?
- Comment sauriez-vous qu'elle est **toujours exacte** dans six mois, quand
  un fournisseur change sa mise en page ?
- Quand vaut-il la peine d'écrire un autre analyseur déterministe plutôt
  que de s'appuyer sur le modèle ?

## Gestion de versions

Merci d'utiliser git — on demande l'historique pour pouvoir suivre votre
raisonnement. Faites `git init` au début et committez au fil de l'eau. Une
organisation qu'on trouverait facile à lire : une branche par ticket
(`ticket-1`, `ticket-2`) et une branche `final` avec tout.

## Livrables

- Votre code dans un zip — **merci d'inclure le dossier `.git/`**. Laissez
  de côté `.env`, `node_modules/`, `.venv/`.
- Un `NOTES.md` qui couvre :
  - Les **décisions** que vous avez prises là où la consigne était ambiguë
  - Vos **observations ou préoccupations** sur le code existant
  - **Ce que vous contesteriez** s'il s'agissait d'un vrai ticket
  - **Ce que vous feriez ensuite** avec plus de temps
  - Le ticket 3
  - Le temps passé, à peu près

On ne s'attend **pas** à la perfection — on s'attend à du goût. Amusez-vous
bien.
