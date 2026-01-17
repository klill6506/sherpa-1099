"""
Check detailed form info for recipients with multiple forms.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def check_recipient_details():
    client = get_supabase_client()

    # Get forms for Charles and William M. Nabors
    recipients = client.table('recipients').select('id, name, tin').execute().data

    target_names = ['Charles', 'William M. Nabors']
    for name in target_names:
        recip = next((r for r in recipients if name.lower() in r['name'].lower()), None)
        if not recip:
            print(f"\n{name}: NOT FOUND")
            continue

        print(f"\n=== {recip['name']} (TIN: ***-**-{recip['tin'][-4:]}) ===")

        forms = client.table('forms_1099').select('*').eq('recipient_id', recip['id']).execute().data

        for f in forms:
            print(f"\nForm Type: {f['form_type']}")
            print(f"  Created: {f['created_at']}")
            if f['form_type'] == '1099-NEC':
                print(f"  NEC Box 1: ${f.get('nec_box1', 0) or 0:,.2f}")
            elif f['form_type'] == '1099-MISC':
                print(f"  MISC Box 1 (Rents): ${f.get('misc_box1', 0) or 0:,.2f}")
                print(f"  MISC Box 2 (Royalties): ${f.get('misc_box2', 0) or 0:,.2f}")
                print(f"  MISC Box 3 (Other): ${f.get('misc_box3', 0) or 0:,.2f}")
            elif f['form_type'] == '1099-S':
                print(f"  S Box 2 (Proceeds): ${f.get('s_box2_gross_proceeds', 0) or 0:,.2f}")
            elif f['form_type'] == '1098':
                print(f"  1098 Box 1 (Mortgage Interest): ${f.get('f1098_box1_mortgage_interest', 0) or 0:,.2f}")

if __name__ == "__main__":
    check_recipient_details()
