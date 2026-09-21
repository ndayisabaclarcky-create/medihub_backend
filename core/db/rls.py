"""
Fabrique de policies PostgreSQL Row-Level Security pour l'isolation multi-tenant.
"""

from django.db import migrations

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