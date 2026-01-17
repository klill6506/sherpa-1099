"""
Fix the duplicate William M. Nabors form.
Delete the $0 1099-MISC form, keep the real 1099-NEC.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def fix_nabors():
    client = get_supabase_client()

    # Find William M. Nabors recipient for Flea Markets
    filer = client.table('filers').select('id').ilike('name', '%flea%market%').execute().data[0]

    recip = client.table('recipients').select('id, name').eq('filer_id', filer['id']).ilike('name', '%nabors%').execute().data

    if not recip:
        print("Recipient not found")
        return

    recip = recip[0]
    print(f"Found: {recip['name']} (ID: {recip['id'][:8]}...)")

    # Get forms for this recipient
    forms = client.table('forms_1099').select('*').eq('recipient_id', recip['id']).execute().data

    print(f"\nForms for this recipient:")
    for f in forms:
        nec = f.get('nec_box1') or 0
        misc = f.get('misc_box1') or 0
        print(f"  - ID: {f['id'][:8]}... Type: {f['form_type']}, NEC Box1: ${nec}, MISC Box1: ${misc}")

    # Find the $0 MISC form to delete
    misc_forms = [f for f in forms if f['form_type'] == '1099-MISC']

    for mf in misc_forms:
        misc_amount = mf.get('misc_box1') or 0
        if misc_amount == 0:
            print(f"\n*** Deleting 1099-MISC with $0: {mf['id'][:8]}...")
            # Uncomment to actually delete:
            result = client.table('forms_1099').delete().eq('id', mf['id']).execute()
            print(f"    Deleted successfully")

    # Verify
    forms_after = client.table('forms_1099').select('id, form_type, nec_box1').eq('recipient_id', recip['id']).execute().data
    print(f"\nForms remaining: {len(forms_after)}")
    for f in forms_after:
        print(f"  - {f['form_type']}: ${f.get('nec_box1', 0) or 0:,.2f}")

if __name__ == "__main__":
    fix_nabors()
