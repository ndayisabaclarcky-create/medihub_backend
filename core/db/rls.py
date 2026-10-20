"""
Fabrique de policies PostgreSQL Row-Level Security pour l'isolation multi-tenant.

Contenu :
- enable_tenant_rls()   : isolation stricte par établissement (policy FOR ALL).
- open_select_policy()  : policy FOR SELECT supplémentaire, qui OUVRE la lecture
                          d'une table à tous les établissements (voir ci-dessous).
- temporary_tenant()    : bascule transactionnelle et réversible du contexte
                          d'établissement. À n'utiliser que dans les fonctions
                          de patients/services.py (point de passage unique et
                          auditable de l'exception RG36).
"""

from contextlib import contextmanager

from django.db import connection, migrations

SESSION_VAR = "app.current_etablissement"


def enable_tenant_rls(table_name, fk_column="id_etablissement", policy_name=None):
    """
    Retourne une django.db.migrations.RunSQL prête à insérer dans `operations`,
    qui active et force la RLS sur `table_name`, puis crée une policy limitant
    SELECT/INSERT/UPDATE/DELETE aux lignes de l'établissement courant.
    """
    policy_name = policy_name or f"tenant_isolation_{table_name}"
    forward = f"""
        ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {policy_name} ON {table_name}
            USING ({fk_column} = NULLIF(current_setting('{SESSION_VAR}', true), '')::uuid)
            WITH CHECK ({fk_column} = NULLIF(current_setting('{SESSION_VAR}', true), '')::uuid);
    """
    reverse = f"""
        DROP POLICY IF EXISTS {policy_name} ON {table_name};
        ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;
    """
    return migrations.RunSQL(sql=forward, reverse_sql=reverse)


def open_select_policy(table_name, policy_name=None):
    """
    Ajoute à une table DÉJÀ sous RLS (voir enable_tenant_rls) une seconde policy
    permissive limitée à SELECT : tout établissement peut LIRE toutes les lignes.

    Les policies permissives s'additionnent (OU logique) : INSERT / UPDATE /
    DELETE restent soumis à la seule policy tenant_isolation_*, donc chaque
    établissement continue de n'écrire que ses propres lignes.

    Uniquement pour index_rapprochement (RG35, Processus 3) : la table ne porte
    aucune donnée médicale, et sa lecture est ce qui permet à l'hôpital B de
    découvrir qu'un patient est déjà connu de l'hôpital A.
    """
    policy_name = policy_name or f"open_select_{table_name}"
    forward = f"CREATE POLICY {policy_name} ON {table_name} FOR SELECT USING (true);"
    reverse = f"DROP POLICY IF EXISTS {policy_name} ON {table_name};"
    return migrations.RunSQL(sql=forward, reverse_sql=reverse)


def current_tenant():
    """Établissement courant de la session PostgreSQL ('' si aucun)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [SESSION_VAR])
        return cursor.fetchone()[0] or ""


def _set_tenant(value):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [SESSION_VAR, str(value) if value else ""])


@contextmanager
def temporary_tenant(id_etablissement):
    """
    Bascule la variable de session vers `id_etablissement` le temps du bloc,
    puis restaure la valeur précédente (même en cas d'exception).

    Équivalent d'un SET LOCAL : la valeur est limitée à la transaction en cours,
    d'où l'obligation d'être dans un bloc atomic (sinon la bascule serait sans
    effet, chaque requête étant sa propre transaction).
    """
    if not connection.in_atomic_block:
        raise RuntimeError("temporary_tenant() doit être appelé dans une transaction (transaction.atomic).")
    previous = current_tenant()
    _set_tenant(id_etablissement)
    try:
        yield
    finally:
        _set_tenant(previous)
