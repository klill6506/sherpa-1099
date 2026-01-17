"""
Verify the 4 reported duplicates only appear once in the database.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def verify_no_dupes():
    client = get_supabase_client()

    # Find Flea Markets filer
    filer = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data[0]
    filer_id = filer['id']
    print(f"Filer: {filer['name']}\n")

    # The 4 reported duplicates
    duplicates = [
        ("Alison T Burleson", "4164", 3314.70),
        ("Carol D Hall", "4913", 5219.40),
        ("Craig Walters", "4239", 8198.34),
        ("Llamas Beans & Leaves LLC", "4487", 11104.41),
    ]

    print("Checking reported duplicates in database:\n")

    for name, tin_last4, amount in duplicates:
        # Find recipient
        recips = client.table('recipients').select('id, name, tin').eq('filer_id', filer_id).execute().data
        matching = [r for r in recips if tin_last4 in (r.get('tin') or '')]

        print(f"--- {name} (TIN ending {tin_last4}, ${amount:,.2f}) ---")

        if not matching:
            print(f"  WARNING: No recipient found with TIN ending {tin_last4}")
            continue

        for recip in matching:
            print(f"  Recipient: {recip['name']}")
            print(f"  TIN: ***-**-{recip['tin'][-4:]}")

            # Get forms
            forms = client.table('forms_1099').select('id, form_type, nec_box1, created_at').eq('recipient_id', recip['id']).execute().data
            print(f"  Forms in database: {len(forms)}")

            for f in forms:
                print(f"    - {f['form_type']}: ${f.get('nec_box1') or 0:,.2f}")

        print()

    # Summary
    print("\n=== SUMMARY ===")
    all_forms = client.table('forms_1099').select('id').eq('filer_id', filer_id).execute().data
    print(f"Total forms for this filer: {len(all_forms)}")
    print(f"If PDF had 71 pages but 10 were duplicates (6 extra), that's 65 unique forms")
    print(f"Database has {len(all_forms)} forms")

    if len(all_forms) < 71:
        missing = 71 - len(all_forms)
        print(f"\n*** {missing} forms are MISSING from database ***")
        print("This means some recipients never got imported!")

if __name__ == "__main__":
    verify_no_dupes()
