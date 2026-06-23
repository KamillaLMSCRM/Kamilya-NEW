-- Create tenant and superadmin user for Kamilya LMS
-- Run via: ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 "PGPASSWORD='<SUPABASE_PASSWORD>' psql -h aws-1-eu-central-1.pooler.supabase.com -p 5432 -U postgres.ducegbxphkgffgozkchw -d postgres -f -"

-- Create tenant
INSERT INTO tenants (id, name, slug, status, plan, settings)
VALUES (
    gen_random_uuid(),
    'Acme Corp',
    'acme-corp',
    'active',
    'starter',
    '{}'::jsonb
) ON CONFLICT (slug) DO NOTHING;

-- Find the tenant
-- (Will need to query for the ID after creation)
