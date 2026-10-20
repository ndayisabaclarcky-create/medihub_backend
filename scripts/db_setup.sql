-- Création du rôle applicatif MediHub (à exécuter UNE FOIS, en super-utilisateur).
--
--   psql -U postgres -v app_password='un-vrai-mot-de-passe' -f scripts/db_setup.sql
--
-- Pourquoi : un super-utilisateur (postgres) ou un rôle BYPASSRLS ignore TOUTE
-- la Row-Level Security, même avec FORCE ROW LEVEL SECURITY. Django doit donc se
-- connecter avec ce rôle, puis .env doit contenir DB_USER=medihub_app.
--
-- CREATEDB : nécessaire uniquement pour que `manage.py test` puisse créer sa base.
-- Le rôle est propriétaire de la base : il peut appliquer les migrations
-- (y compris ALTER TABLE ... FORCE ROW LEVEL SECURITY) sans aucun privilège spécial.

CREATE ROLE medihub_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOBYPASSRLS NOCREATEROLE CREATEDB;

CREATE DATABASE medihub OWNER medihub_app;
