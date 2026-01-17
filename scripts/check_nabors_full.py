"""
Full check of William M. Nabors forms.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def check_nabors():
    client = get_supabase_client()

    # Find filer
    filer = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data[0]
    print(f"Filer: {filer['name']}")

    # Find recipient
    recip = client.table('recipients').select('*').eq('filer_id', filer['id']).ilike('name', '%nabors%').execute().data[0]
    print(f"Recipient: {recip['name']}")
    print(f"  TIN: ***-**-{recip['tin'][-4:]}")

    # Get ALL form data
    forms = client.table('forms_1099').select('*').eq('recipient_id', recip['id']).execute().data

    print(f"\n{len(forms)} forms found:")
    for f in forms:
        print(f"\n--- Form Type: {f['form_type']} ---")
        print(f"  ID: {f['id']}")
        print(f"  Created: {f['created_at']}")
        print(f"  NEC Box 1: ${f.get('nec_box1') or 0:,.2f}")
        print(f"  MISC Box 1 (Rents): ${f.get('misc_box1') or 0:,.2f}")
        print(f"  MISC Box 2 (Royalties): ${f.get('misc_box2') or 0:,.2f}")
        print(f"  MISC Box 3 (Other): ${f.get('misc_box3') or 0:,.2f}")

if __name__ == "__main__":
    check_nabors()
