"""
Check for Alison T Burleson - reported duplicate.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def check_burleson():
    client = get_supabase_client()

    # Find Flea Markets filer
    filer = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data[0]
    print(f"Filer: {filer['name']}")

    # Search for Burleson - check recipients
    all_recips = client.table('recipients').select('id, name, tin').eq('filer_id', filer['id']).execute().data

    burleson_recips = [r for r in all_recips if 'burleson' in r['name'].lower()]

    print(f"\nRecipients matching 'Burleson': {len(burleson_recips)}")
    for r in burleson_recips:
        print(f"  - {r['name']} (TIN: ***-**-{r['tin'][-4:] if r['tin'] else '????'})")

        # Get forms for this recipient
        forms = client.table('forms_1099').select('id, form_type, nec_box1, created_at').eq('recipient_id', r['id']).execute().data
        print(f"    Forms: {len(forms)}")
        for f in forms:
            print(f"      - {f['form_type']}: ${f.get('nec_box1') or 0:,.2f} (created: {f['created_at'][:19]})")

    # Also check ALL forms for this filer to find any with $3,314.70
    print(f"\n\nSearching for forms with amount $3,314.70...")
    all_forms = client.table('forms_1099').select('id, recipient_id, form_type, nec_box1, created_at').eq('filer_id', filer['id']).execute().data

    matching_forms = [f for f in all_forms if f.get('nec_box1') and abs(float(f['nec_box1']) - 3314.70) < 0.01]

    print(f"Forms with $3,314.70: {len(matching_forms)}")
    for f in matching_forms:
        recip = client.table('recipients').select('name, tin').eq('id', f['recipient_id']).execute().data[0]
        print(f"  - {recip['name']} (TIN: ***-**-{recip['tin'][-4:]})")
        print(f"    Form ID: {f['id'][:8]}... Created: {f['created_at'][:19]}")

    # Check for duplicate amounts in general
    print(f"\n\nChecking for duplicate amounts across all forms...")
    from collections import defaultdict
    by_amount = defaultdict(list)
    for f in all_forms:
        amt = f.get('nec_box1')
        if amt and float(amt) > 0:
            by_amount[float(amt)].append(f)

    dup_amounts = {amt: forms for amt, forms in by_amount.items() if len(forms) > 1}
    print(f"Amounts appearing more than once: {len(dup_amounts)}")

    for amt, forms in sorted(dup_amounts.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"\n  ${amt:,.2f} appears {len(forms)} times:")
        for f in forms:
            recip = client.table('recipients').select('name').eq('id', f['recipient_id']).execute().data[0]
            print(f"    - {recip['name']}")

if __name__ == "__main__":
    check_burleson()
