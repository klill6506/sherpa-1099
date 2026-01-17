"""
Check Sheri Murphy and Terry McFarlane - duplicate/skip issue.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def check_both():
    client = get_supabase_client()

    # Find Flea Markets filer
    filer = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data[0]
    filer_id = filer['id']
    print(f"Filer: {filer['name']}\n")

    # Get all recipients
    all_recips = client.table('recipients').select('id, name, tin').eq('filer_id', filer_id).execute().data

    # Find Murphy and McFarlane
    murphy = [r for r in all_recips if 'murphy' in r['name'].lower()]
    mcfarlane = [r for r in all_recips if 'mcfarlane' in r['name'].lower()]

    print("=== Sheri Murphy ===")
    for r in murphy:
        print(f"Recipient ID: {r['id']}")
        print(f"Name: {r['name']}")
        print(f"TIN: {r['tin']}")

        forms = client.table('forms_1099').select('id, form_type, nec_box1').eq('recipient_id', r['id']).execute().data
        print(f"Forms: {len(forms)}")
        for f in forms:
            print(f"  Form ID: {f['id']}")
            print(f"  Type: {f['form_type']}, Amount: ${f.get('nec_box1') or 0:,.2f}")

    print("\n=== Terry McFarlane ===")
    for r in mcfarlane:
        print(f"Recipient ID: {r['id']}")
        print(f"Name: {r['name']}")
        print(f"TIN: {r['tin']}")

        forms = client.table('forms_1099').select('id, form_type, nec_box1').eq('recipient_id', r['id']).execute().data
        print(f"Forms: {len(forms)}")
        for f in forms:
            print(f"  Form ID: {f['id']}")
            print(f"  Type: {f['form_type']}, Amount: ${f.get('nec_box1') or 0:,.2f}")

    if not mcfarlane:
        print("*** Terry McFarlane NOT FOUND in recipients! ***")
        print("\nSearching all recipients for similar names...")
        for r in all_recips:
            if 'terry' in r['name'].lower() or 'mcf' in r['name'].lower():
                print(f"  - {r['name']}")

    # Now let's look at the form IDs and see their order
    print("\n\n=== Form ID Analysis ===")
    all_forms = client.table('forms_1099').select('id, recipient_id').eq('filer_id', filer_id).execute().data

    # Get form IDs for Murphy and McFarlane
    murphy_ids = [r['id'] for r in murphy]
    mcfarlane_ids = [r['id'] for r in mcfarlane]

    murphy_form_ids = [f['id'] for f in all_forms if f['recipient_id'] in murphy_ids]
    mcfarlane_form_ids = [f['id'] for f in all_forms if f['recipient_id'] in mcfarlane_ids]

    print(f"Murphy form IDs: {murphy_form_ids}")
    print(f"McFarlane form IDs: {mcfarlane_form_ids}")

    # Check if IDs are similar (could indicate UUID collision or similar issue)
    if murphy_form_ids and mcfarlane_form_ids:
        print(f"\nComparing UUIDs:")
        print(f"  Murphy:    {murphy_form_ids[0]}")
        print(f"  McFarlane: {mcfarlane_form_ids[0]}")

if __name__ == "__main__":
    check_both()
