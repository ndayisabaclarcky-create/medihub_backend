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

Pour un frontend exécuté sur une autre origine en développement, ajoute son origine exacte à `CORS_ALLOWED_ORIGINS` dans `.env`, par exemple `http://localhost:3000`. Les cookies de session nécessitent une configuration cohérente de CORS, CSRF et des cookies pour l’environnement cible. Les secrets, l’origine du frontend et les hôtes autorisés devront être configurés séparément pour le déploiement.

## Postman

Les collections et réglages Postman locaux ne sont pas nécessaires à l’exécution du backend et ne sont pas inclus dans le dépôt. Crée une collection locale et n’y exporte jamais de mot de passe, cookie de session ou secret réel.
