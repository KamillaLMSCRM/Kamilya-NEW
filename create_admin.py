"""Create tenant and superadmin user via Supabase REST API."""
import requests
import uuid

SUPABASE_URL = "https://ducegbxphkgffgozkchw.supabase.co/rest/v1"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1Y2VnYnhwaGtnZmZnb2t6Y2giLCJyb2xlIjoiYW5vbiIsImlhdCI6MTczOTIwMDAwMCwiZXhwIjoyMDU0Nzc2MDAwfQ.placeholder"
JWT_SECRET = "AvW3keNLtairhV56pEjwCF0I12dKqTHf"  # Same as server .env

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# 1. Create tenant
tenant_id = str(uuid.uuid4())
print(f"Creating tenant ID: {tenant_id}")

tenant_data = {
    "id": tenant_id,
    "name": "Acme Corp",
    "slug": "acme-corp",
    "status": "active",
    "plan": "starter",
    "settings": {}
}

resp = requests.post(f"{SUPABASE_URL}/tenants", json=tenant_data, headers=headers)
if resp.status_code == 201:
    print(f"✅ Tenant created: {resp.json()}")
elif resp.status_code == 409:
    print(f"⚠️ Tenant already exists: {resp.json()}")
    # Get existing tenant
    get_resp = requests.get(f"{SUPABASE_URL}/tenants?slug=eq.acme-corp", headers=headers)
    if get_resp.status_code == 200:
        tenant = get_resp.json()[0]
        tenant_id = tenant["id"]
        print(f"   Using existing tenant: {tenant_id}")
else:
    print(f"❌ Failed to create tenant: {resp.status_code} {resp.text[:500]}")

# 2. Create superadmin user
password = "SuperAdmin123"
import hashlib
argon_hash = None  # We'll use the password endpoint

# Actually need to let server hash password. Create via admin endpoint if exists, or directly.
print(f"\nTenant ID: {tenant_id}")
