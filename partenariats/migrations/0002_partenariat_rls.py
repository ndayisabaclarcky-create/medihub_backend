from django.db import migrations


FORWARD = """
ALTER TABLE partenariat ENABLE ROW LEVEL SECURITY;
ALTER TABLE partenariat FORCE ROW LEVEL SECURITY;

CREATE POLICY partenariat_participant_select ON partenariat
    FOR SELECT
    USING (
        id_etablissement = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
        OR id_etablissement_partenaire = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
    );

CREATE POLICY partenariat_initiator_insert ON partenariat
    FOR INSERT
    WITH CHECK (
        id_etablissement = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
    );

CREATE POLICY partenariat_participant_update ON partenariat
    FOR UPDATE
    USING (
        id_etablissement = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
        OR id_etablissement_partenaire = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
    )
    WITH CHECK (
        id_etablissement = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
        OR id_etablissement_partenaire = NULLIF(current_setting('app.current_etablissement', true), '')::uuid
    );
"""

REVERSE = """
DROP POLICY IF EXISTS partenariat_participant_update ON partenariat;
DROP POLICY IF EXISTS partenariat_initiator_insert ON partenariat;
DROP POLICY IF EXISTS partenariat_participant_select ON partenariat;
ALTER TABLE partenariat NO FORCE ROW LEVEL SECURITY;
ALTER TABLE partenariat DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("partenariats", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
