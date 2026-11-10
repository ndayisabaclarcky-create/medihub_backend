# MediHub — API backend

Backend REST de MediHub construit avec Django REST Framework et PostgreSQL. Il couvre la gestion multi-établissement, les patients, les soins, la pharmacie, le laboratoire interne, la facturation, le portail patient, les partenariats, les équipements et les statistiques.

## Prérequis

- Python compatible avec Django 6.1.1
- PostgreSQL
- `psql` disponible pour initialiser une nouvelle base

## Installation locale sous Windows / PowerShell

Depuis la racine du dépôt :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Modifie ensuite `.env` : renseigne un vrai `SECRET_KEY`, le mot de passe PostgreSQL, et garde `DEBUG=True` uniquement pour le développement local. `.env` est ignoré par Git et ne doit pas être publié.

### Initialiser PostgreSQL

Sur une installation vierge, le script suivant crée la base `medihub` et le rôle applicatif `medihub_app` avec la Row-Level Security activée sans privilège de contournement. Exécute-le une seule fois avec un compte PostgreSQL administrateur :

```powershell
psql -U postgres -v app_password='CHOISIR_UN_MOT_DE_PASSE' -f scripts/db_setup.sql
```

Mets le même mot de passe dans `DB_PASSWORD` dans `.env`. Configure également `DB_NAME=medihub`, `DB_USER=medihub_app`, `DB_HOST=localhost` et `DB_PORT=5432`. Si cette base et ce rôle existent déjà, ne relance pas le script ; vérifie simplement les valeurs de `.env`.

Applique les migrations puis lance le serveur :

```powershell
python manage.py migrate
python manage.py runserver
```

L’API est disponible sur `http://127.0.0.1:8000/` et l’administration Django sur `http://127.0.0.1:8000/admin/`.

### Premier établissement et premier compte administrateur

Le dépôt ne contient aucun compte ni mot de passe de démonstration. Après les migrations, si la base ne contient encore aucun établissement, crée un hôpital initial depuis le shell Django :

```powershell
python manage.py shell
```

```python
from etablissements.models import Etablissement, Hopital

etablissement = Etablissement.objects.create(
    nom_etablissement="Hôpital de démonstration",
    type_etablissement="hopital",
    adresse="Gitega",
    telephone_contact="+257 00 00 00 00",
)
Hopital.objects.create(
    id_etablissement=etablissement,
    numero_agrement="AGR-INITIAL",
)
print(etablissement.id_etablissement)
```

Quitte le shell avec `exit()`, puis crée le compte plateforme avec :

```powershell
python manage.py createsuperuser
```

Saisis l’identifiant, les informations demandées et l’UUID de l’établissement imprimé précédemment. Choisis un mot de passe fort. Cet administrateur pourra provisionner d’autres établissements via l’API.

## Authentification des API

Les API utilisent actuellement l’authentification par session Django, pas JWT. Pour se connecter depuis Postman ou un client web :

1. `GET http://127.0.0.1:8000/api/auth/session/` pour initialiser le cookie CSRF.
2. `POST http://127.0.0.1:8000/api/auth/session/` avec `Content-Type: application/json` :

   ```json
   {
     "identifiant_connexion": "votre_identifiant",
     "password": "votre_mot_de_passe"
   }
   ```

3. Conserve les cookies de session. Pour les requêtes `POST`, `PUT`, `PATCH` et `DELETE`, envoie également `X-CSRFToken` avec la valeur du cookie `csrftoken`.
4. `GET` ou `DELETE /api/auth/session/` permet de consulter ou fermer la session.

Les permissions dépendent du rôle métier et de l’établissement de l’utilisateur. La Row-Level Security de PostgreSQL complète ces contrôles pour isoler les données par établissement.

## Principales routes

| Domaine | Préfixe |
| --- | --- |
| Session du personnel | `/api/auth/session/` |
| Établissement, personnel, services | `/api/etablissements/` |
| Patients | `/api/patients/` |
| Rendez-vous, consultations, actes, hospitalisations | `/api/soins/` |
| Médicaments, lots, prescriptions, ventes, alertes | `/api/pharmacie/` |
| Examens et résultats du laboratoire interne | `/api/laboratoire/` |
| Factures | `/api/facturation/` |
| Portail patient, codes, rendez-vous, documents | `/api/portail/` |
| Partenariats entre établissements | `/api/partenariats/` |
| Équipements et maintenance | `/api/equipements/` |
| Statistiques | `/api/statistiques/` |

Les routes détaillées et leurs champs sont définis dans les `urls.py` et serializers de chaque application.

## Portail patient en développement

Pour les essais locaux, `.env.example` active `PORTAIL_CODE_DEMO=True`. Dans ce mode de développement, la réponse de demande de code peut inclure le code de vérification simulé. Désactive impérativement ce mode en production (`PORTAIL_CODE_DEMO=False`) et configure l’envoi réel des codes avant d’exposer le portail.

## Vérifications et tests

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --keepdb
```

PostgreSQL est requis : plusieurs protections, dont la Row-Level Security, reposent sur ses fonctions. Le rôle `medihub_app` doit rester `NOSUPERUSER` et `NOBYPASSRLS` ; `manage.py check --database default` signale un compte de base trop privilégié.

## Configuration du frontend

Les origines locales Vite (`http://localhost:5173`) et Next.js (`http://localhost:3000`) sont autorisées par défaut. Après avoir copié `.env.example`, la variable `CORS_ALLOWED_ORIGINS` doit conserver les deux origines, séparées par une virgule. Redémarre Django après toute modification de `.env`.

Les deux frontends utilisent l'authentification par session : les appels doivent inclure les cookies (`credentials: "include"` dans `fetch` ou `withCredentials: true` avec Axios). Pour les opérations d'écriture, le frontend doit d'abord récupérer le cookie `csrftoken` puis le renvoyer dans l'en-tête `X-CSRFToken`. Le portail patient possède sa propre session OTP ; il ne faut pas la remplacer par le compte du personnel.

Routes du portail à connecter : `GET /api/portail/hopitaux/`, `POST /api/portail/codes/demander/`, `POST /api/portail/codes/verifier/`, `GET /api/portail/session/`, `GET /api/portail/profil/`, `GET /api/portail/documents/` et `GET /api/portail/medecins/`. Le profil patient renvoie les allergies, les antécédents, le groupe sanguin, les mesures de poids datées et le médecin référent (nom, prénom, spécialité et photo si configurée). Les URLs de photo peuvent être temporaires lorsque le bucket privé émet des liens signés.

En développement, les photos sont stockées dans `./media`. Pour Railway, configure un stockage objet S3 compatible en renseignant `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY`. Ne mets jamais les identifiants du bucket dans le frontend ou dans Git. Le domaine du bucket devra aussi être autorisé par la configuration d'images du frontend Next.js.

Pour le déploiement, ajoute les origines HTTPS exactes à `CORS_ALLOWED_ORIGINS` (cette liste sert aussi à `CSRF_TRUSTED_ORIGINS`) ainsi que le domaine backend dans `ALLOWED_HOSTS`. Les cookies cross-site doivent être configurés en HTTPS avec `SameSite=None` et `Secure=True` si frontend et backend sont sur des domaines distincts.

## Postman

Les collections et réglages Postman locaux ne sont pas nécessaires à l’exécution du backend et ne sont pas inclus dans le dépôt. Crée une collection locale et n’y exporte jamais de mot de passe, cookie de session ou secret réel.



### Démarrer les trois serveurs en local

Le dépôt `MediHub_Backend` contient l'API Django. Depuis PowerShell, dans cette racine, applique les migrations puis démarre l'API :

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 8000
```

Dans deux autres terminaux, depuis la racine du dépôt `MediHub_Frontend`, installe les dépendances une fois puis lance les deux interfaces :

```powershell
npm ci
npm run dev:staff
```

```powershell
npm run dev:portal
```

Le personnel est servi par Vite sur `http://localhost:5173`, le portail patient par Next.js sur `http://localhost:3000` et l'API sur `http://localhost:8000`. Les deux frontends ont déjà une URL API locale par défaut ; leurs fichiers `.env.example` permettent de la remplacer. Django doit autoriser les deux origines dans `CORS_ALLOWED_ORIGINS` et `CSRF_TRUSTED_ORIGINS`, avec `CORS_ALLOW_CREDENTIALS=True`. Le `.env.example` du backend contient ces deux origines.

Les sessions du personnel et du compte patient peuvent coexister dans le navigateur. Les cookies et les jetons CSRF doivent être envoyés par les deux interfaces. L’espace du personnel est raccordé aux API pour les patients, rendez-vous, consultations et ordonnances, admissions et sorties, laboratoire, pharmacie (catalogue, lots et ventes), facturation (émission et paiements), personnel et tableau de bord. La facturation propose au comptable une liste minimale des épisodes clôturés à facturer. Les partenariats et les équipements restent disponibles dans l’API backend, mais leurs écrans frontend ne sont pas encore intégrés.

### Démarrer tout MediHub avec Docker

Docker Desktop doit être lancé. Ce dépôt contient le `Dockerfile` de l'API et le `docker-compose.yml` qui démarre PostgreSQL, le backend Django, l'espace du personnel et le portail patient. Pour cette commande locale, garde `MediHub_Backend` et `MediHub_Frontend` côte à côte dans le même dossier.

```powershell
Copy-Item .env.docker.example .env.docker
```

Ouvre `.env.docker`, remplace les secrets d'exemple, puis lance depuis la racine de `MediHub_Backend` :

```powershell
docker compose --env-file .env.docker up --build
```

Les services seront disponibles sur `http://localhost:8000` (API), `http://localhost:5173` (personnel) et `http://localhost:3000` (portail patient). PostgreSQL et les fichiers médias locaux sont conservés dans des volumes Docker. Le script `scripts/db_setup.sql` crée le rôle applicatif `medihub_app` sans privilège de contournement de la Row-Level Security ; cette initialisation ne se rejoue pas tant que le volume PostgreSQL existe.

Le conteneur backend applique les migrations au démarrage, collecte les fichiers statiques Django et lance Gunicorn avec un worker pour limiter la mémoire. Pour créer le premier hôpital et son compte administrateur, ouvre le shell dans le conteneur avec `docker compose --env-file .env.docker exec backend python manage.py shell`, puis exécute le code Python de la section précédente. Journaux : `docker compose --env-file .env.docker logs -f backend`. `docker compose down` arrête les services sans supprimer les données.

Pour Railway, chaque service se construit depuis le dépôt correspondant : backend avec `Dockerfile`, personnel avec `staff/Dockerfile`, portail patient avec `patient-portal/Dockerfile`. Les frontends doivent recevoir l'URL publique du backend aux arguments de build `VITE_API_BASE_URL` et `NEXT_PUBLIC_API_BASE_URL`. Le backend doit autoriser leurs domaines dans `CORS_ALLOWED_ORIGINS` et `ALLOWED_HOSTS`. Le PostgreSQL Railway devra initialiser le rôle `medihub_app` avec `NOBYPASSRLS` ; Django ne doit pas se connecter en superutilisateur. La configuration des variables de production sera nécessaire avant le déploiement.

### Compte patient et partage entre hôpitaux

Le patient peut créer un compte indépendant, confirmer son numéro par code, puis se connecter avec identifiant et mot de passe suivi d'un code à usage unique. Chaque rendez-vous dans un nouvel hôpital crée un dossier local séparé. Depuis son compte, le patient peut choisir un dossier source, un hôpital de destination où il a déjà un dossier, donner son consentement explicite, puis partager une copie figée du résumé médical et des résultats, prescriptions ou factures sélectionnés. Les dossiers restent propres à chaque hôpital ; le partage reçu est un instantané consultable par le patient et l'équipe soignante du nouvel hôpital. Les urgences sans compte restent enregistrables par le personnel comme auparavant.

Routes du compte patient (les requêtes d'écriture nécessitent les cookies de session et CSRF) :

- `POST /api/portail/compte/inscription/` : identifiant, nom, prénom, date de naissance, sexe, téléphone, mot de passe ; allergies, antécédents et groupe sanguin déclarés sont facultatifs.
- `POST /api/portail/compte/connexion/`, puis `POST /api/portail/compte/codes/verifier/` : connexion et validation du code.
- `GET /api/portail/compte/dossiers/` : hôpitaux où le compte a déjà un dossier local.
- `GET /api/portail/medecins/?id_hopital={uuid}` : médecins actifs de l'hôpital choisi.
- `GET /api/portail/compte/disponibilite/?id_hopital={uuid}&matricule_personnel={uuid}&date_rendez_vous=AAAA-MM-JJ&heure_rendez_vous=HH:MM` : vérifie un créneau.
- `POST /api/portail/compte/rendez-vous/{id_hopital}/` : réserve le créneau et crée le dossier local si nécessaire.
- `POST /api/portail/compte/partages/historique/` : envoie le résumé consenti et les documents choisis. Le dossier du patient doit d'abord exister à l'hôpital destinataire.
- `GET /api/portail/profil/?id_hopital={uuid}` et `GET /api/portail/documents/?id_hopital={uuid}` : consulte le profil, les partages reçus et les documents du dossier local.

La livraison SMS réelle n'est pas configurée. `PORTAIL_CODE_DEMO=True` expose un code simulé uniquement pour le développement ; avant une démonstration publique, intégrer un fournisseur SMS, désactiver ce mode et configurer les cookies HTTPS/CORS du déploiement. Un dossier d'urgence créé sans compte doit être lié de façon vérifiée par l'hôpital avant de pouvoir être partagé depuis un compte patient.
