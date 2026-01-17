"""
Check for duplicate 1099 forms in the database.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client

def check_duplicates():
    client = get_supabase_client()

    # Get all forms with their recipient info
    forms = client.table('forms_1099').select(
        'id, filer_id, recipient_id, operating_year_id, form_type, nec_box1, created_at'
    ).order('created_at').execute().data

    print(f"Total forms in database: {len(forms)}")

    # Group by (filer_id, recipient_id, operating_year_id, form_type)
    seen = {}
    duplicates = []

    for form in forms:
        key = (form['filer_id'], form['recipient_id'], form['operating_year_id'], form['form_type'])
        if key in seen:
            duplicates.append({
                'original': seen[key],
                'duplicate': form
            })
        else:
            seen[key] = form

    print(f"Unique form combinations: {len(seen)}")
    print(f"Duplicates found: {len(duplicates)}")

    if duplicates:
        print("\n--- Duplicate Details ---")
        # Get recipient names for context
        recipient_ids = list(set([d['duplicate']['recipient_id'] for d in duplicates]))
        recipients = client.table('recipients').select('id, name, tin').in_('id', recipient_ids).execute().data
        recip_map = {r['id']: r for r in recipients}

        for i, dup in enumerate(duplicates[:10]):  # Show first 10
            recip = recip_map.get(dup['duplicate']['recipient_id'], {})
            print(f"\n{i+1}. {recip.get('name', 'Unknown')} (TIN: ***-**-{recip.get('tin', '')[-4:] if recip.get('tin') else '????'})")
            print(f"   Original:  ID={dup['original']['id'][:8]}... Amount=${dup['original'].get('nec_box1', 0) or 0:,.2f} Created={dup['original']['created_at']}")
            print(f"   Duplicate: ID={dup['duplicate']['id'][:8]}... Amount=${dup['duplicate'].get('nec_box1', 0) or 0:,.2f} Created={dup['duplicate']['created_at']}")

        if len(duplicates) > 10:
            print(f"\n... and {len(duplicates) - 10} more duplicates")

        # Check if duplicates have same created_at (batch insert)
        same_time = sum(1 for d in duplicates if d['original']['created_at'] == d['duplicate']['created_at'])
        diff_time = len(duplicates) - same_time

        print(f"\nDuplicates created at same time: {same_time}")
        print(f"Duplicates created at different times: {diff_time}")

        if diff_time > same_time:
            print("\n>>> Most duplicates were created at DIFFERENT times - likely re-imported the file")
        else:
            print("\n>>> Most duplicates were created at SAME time - likely a bug in the import process")

    return duplicates

if __name__ == "__main__":
    check_duplicates()
