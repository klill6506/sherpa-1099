"""
Check for recipients with duplicate names or TINs.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from collections import defaultdict

def check_similar_recipients():
    client = get_supabase_client()

    # Get all recipients
    recipients = client.table('recipients').select('id, filer_id, name, tin').execute().data
    print(f"Total recipients: {len(recipients)}")

    # Group by name
    by_name = defaultdict(list)
    for r in recipients:
        by_name[r['name'].upper().strip() if r['name'] else 'NO NAME'].append(r)

    dup_names = {name: recips for name, recips in by_name.items() if len(recips) > 1}
    print(f"Recipients with duplicate names: {len(dup_names)}")

    if dup_names:
        print("\n--- Duplicate Names ---")
        for name, recips in list(dup_names.items())[:10]:
            print(f"\n'{name}' appears {len(recips)} times:")
            for r in recips:
                tin_last4 = r['tin'][-4:] if r['tin'] else '????'
                print(f"   ID={r['id'][:8]}... TIN=***-**-{tin_last4}")

    # Group by TIN
    by_tin = defaultdict(list)
    for r in recipients:
        if r['tin']:
            by_tin[r['tin']].append(r)

    dup_tins = {tin: recips for tin, recips in by_tin.items() if len(recips) > 1}
    print(f"\nRecipients with duplicate TINs: {len(dup_tins)}")

    if dup_tins:
        print("\n--- Duplicate TINs ---")
        for tin, recips in list(dup_tins.items())[:10]:
            print(f"\nTIN ***-**-{tin[-4:]} appears {len(recips)} times:")
            for r in recips:
                print(f"   ID={r['id'][:8]}... Name='{r['name']}'")

    # Check for forms pointing to duplicate recipients
    if dup_tins:
        print("\n--- Forms for Duplicate TIN Recipients ---")
        for tin, recips in list(dup_tins.items())[:5]:
            recip_ids = [r['id'] for r in recips]
            forms = client.table('forms_1099').select(
                'id, recipient_id, form_type, nec_box1, created_at'
            ).in_('recipient_id', recip_ids).execute().data

            print(f"\nTIN ***-**-{tin[-4:]} ({len(recips)} recipients, {len(forms)} forms):")
            for f in forms:
                recip = next((r for r in recips if r['id'] == f['recipient_id']), {})
                print(f"   Form {f['id'][:8]}... Type={f['form_type']} Amount=${f.get('nec_box1', 0) or 0:,.2f} Recipient={recip.get('name', 'Unknown')[:30]}")

if __name__ == "__main__":
    check_similar_recipients()
