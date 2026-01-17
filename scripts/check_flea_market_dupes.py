"""
Check for duplicates in Flea Markets of Madison 1099s.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from collections import defaultdict

def check_flea_market_dupes():
    client = get_supabase_client()

    # Find the Flea Markets of Madison filer
    filers = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data

    if not filers:
        print("Filer not found - searching all filers...")
        filers = client.table('filers').select('id, name').execute().data
        for f in filers:
            print(f"  - {f['name']}")
        return

    filer = filers[0]
    print(f"Filer: {filer['name']} (ID: {filer['id'][:8]}...)")

    # Get all forms for this filer
    forms = client.table('forms_1099').select(
        'id, recipient_id, form_type, nec_box1, created_at'
    ).eq('filer_id', filer['id']).execute().data

    print(f"Total forms: {len(forms)}")

    # Get all recipients
    recipient_ids = list(set(f['recipient_id'] for f in forms))
    recipients = client.table('recipients').select('id, name, tin').in_('id', recipient_ids).execute().data
    recip_map = {r['id']: r for r in recipients}

    print(f"Unique recipients: {len(recipients)}")

    # Check for duplicate recipients (same name)
    by_name = defaultdict(list)
    for r in recipients:
        by_name[r['name'].upper().strip()].append(r)

    dup_names = {name: recips for name, recips in by_name.items() if len(recips) > 1}

    if dup_names:
        print(f"\n=== DUPLICATE RECIPIENT NAMES ({len(dup_names)}) ===")
        for name, recips in dup_names.items():
            print(f"\n'{name}' appears {len(recips)} times:")
            for r in recips:
                tin_last4 = r['tin'][-4:] if r['tin'] else '????'
                # Find forms for this recipient
                recip_forms = [f for f in forms if f['recipient_id'] == r['id']]
                amounts = [f"${f.get('nec_box1', 0) or 0:,.2f}" for f in recip_forms]
                print(f"   TIN: ***-**-{tin_last4}, Forms: {len(recip_forms)}, Amounts: {', '.join(amounts)}")
    else:
        print("\nNo duplicate recipient names found.")

    # Check for same TIN appearing multiple times
    by_tin = defaultdict(list)
    for r in recipients:
        if r['tin']:
            by_tin[r['tin']].append(r)

    dup_tins = {tin: recips for tin, recips in by_tin.items() if len(recips) > 1}

    if dup_tins:
        print(f"\n=== DUPLICATE TINS ({len(dup_tins)}) ===")
        for tin, recips in dup_tins.items():
            print(f"\nTIN ***-**-{tin[-4:]} appears {len(recips)} times:")
            for r in recips:
                recip_forms = [f for f in forms if f['recipient_id'] == r['id']]
                amounts = [f"${f.get('nec_box1', 0) or 0:,.2f}" for f in recip_forms]
                print(f"   Name: '{r['name']}', Forms: {len(recip_forms)}, Amounts: {', '.join(amounts)}")
    else:
        print("\nNo duplicate TINs found.")

    # Check for recipients with multiple forms (same person, multiple 1099s)
    by_recipient = defaultdict(list)
    for f in forms:
        by_recipient[f['recipient_id']].append(f)

    multi_forms = {rid: flist for rid, flist in by_recipient.items() if len(flist) > 1}

    if multi_forms:
        print(f"\n=== RECIPIENTS WITH MULTIPLE FORMS ({len(multi_forms)}) ===")
        for rid, flist in multi_forms.items():
            recip = recip_map.get(rid, {})
            print(f"\n'{recip.get('name', 'Unknown')}' has {len(flist)} forms:")
            for f in flist:
                print(f"   - {f['form_type']}: ${f.get('nec_box1', 0) or 0:,.2f} (created: {f['created_at'][:19]})")
    else:
        print("\nNo recipients with multiple forms.")

    # Summary
    print(f"\n=== SUMMARY ===")
    print(f"Forms: {len(forms)}")
    print(f"Unique recipients: {len(recipients)}")
    print(f"Expected: {len(forms)} forms should equal {len(forms)} recipients (if 1 form per person)")
    if len(forms) != len(recipients):
        print(f"DISCREPANCY: {len(forms) - len(recipients)} extra forms or missing recipients")

if __name__ == "__main__":
    check_flea_market_dupes()
