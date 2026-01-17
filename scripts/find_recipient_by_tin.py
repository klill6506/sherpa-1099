"""
Find recipient by TIN ending.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def find_by_tin(tin_ending: str):
    client = get_supabase_client()

    # Find Flea Markets filer
    filer = client.table('filers').select('id').ilike('name', '%flea%market%').execute().data[0]

    # Get all recipients
    recips = client.table('recipients').select('id, name, tin').eq('filer_id', filer['id']).execute().data

    # Find matching TIN
    matches = [r for r in recips if r['tin'] and r['tin'].endswith(tin_ending)]

    print(f"Recipients with TIN ending '{tin_ending}':")
    for r in matches:
        print(f"  - {r['name']} (TIN: {r['tin']})")

        # Get their forms
        forms = client.table('forms_1099').select('id, form_type, nec_box1, misc_box1').eq('recipient_id', r['id']).execute().data
        print(f"    Forms: {len(forms)}")
        for f in forms:
            amt = f.get('nec_box1') or f.get('misc_box1') or 0
            print(f"      - {f['form_type']}: ${float(amt):,.2f} (ID: {f['id'][:8]}...)")

if __name__ == "__main__":
    tin_ending = sys.argv[1] if len(sys.argv) > 1 else "0224"
    find_by_tin(tin_ending)
