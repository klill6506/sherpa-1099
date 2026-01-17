"""
Simulate the PDF batch generation to check for duplicates.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from collections import Counter

def simulate_pdf_batch():
    client = get_supabase_client()

    # Find Flea Markets filer
    filer = client.table('filers').select('id, name').ilike('name', '%flea%market%').execute().data[0]
    filer_id = filer['id']
    print(f"Filer: {filer['name']}")
    print(f"Filer ID: {filer_id}")

    # Step 1: Get form IDs (same as PDF endpoint)
    forms_result = client.table("forms_1099").select("id").eq("filer_id", filer_id).execute()
    form_ids = [f["id"] for f in forms_result.data]

    print(f"\nStep 1: Query returned {len(forms_result.data)} forms")
    print(f"        Unique form IDs: {len(set(form_ids))}")

    # Check for duplicate IDs
    id_counts = Counter(form_ids)
    dups = {k: v for k, v in id_counts.items() if v > 1}
    if dups:
        print(f"\n*** DUPLICATE FORM IDS FOUND: {len(dups)} ***")
        for fid, count in dups.items():
            print(f"  {fid[:8]}... appears {count} times")
    else:
        print("        No duplicate form IDs in query result")

    # Step 2: Simulate get_forms_batch
    print(f"\nStep 2: Simulating get_forms_batch with {len(form_ids)} IDs...")

    # Fetch forms
    forms_data = client.table("forms_1099").select("*").in_("id", form_ids).execute()
    forms_by_id = {f["id"]: f for f in forms_data.data}

    print(f"        Forms fetched: {len(forms_data.data)}")
    print(f"        Unique in dict: {len(forms_by_id)}")

    # Check recipient distribution
    recipient_ids = [f["recipient_id"] for f in forms_data.data]
    recip_counts = Counter(recipient_ids)
    multi_recips = {k: v for k, v in recip_counts.items() if v > 1}

    if multi_recips:
        print(f"\n*** RECIPIENTS WITH MULTIPLE FORMS: {len(multi_recips)} ***")
        for rid, count in multi_recips.items():
            recip = client.table('recipients').select('name').eq('id', rid).execute().data[0]
            forms_for_recip = [f for f in forms_data.data if f['recipient_id'] == rid]
            form_types = [f['form_type'] for f in forms_for_recip]
            print(f"  {recip['name']}: {count} forms ({', '.join(form_types)})")

    # Step 3: Check what gets assembled
    print(f"\nStep 3: Assembling results...")
    results = []
    for form_id in form_ids:
        form = forms_by_id.get(form_id)
        if form:
            results.append(form['id'])

    print(f"        Results list length: {len(results)}")
    print(f"        Unique in results: {len(set(results))}")

    result_counts = Counter(results)
    result_dups = {k: v for k, v in result_counts.items() if v > 1}
    if result_dups:
        print(f"\n*** DUPLICATES IN FINAL RESULTS: {len(result_dups)} ***")
        for fid, count in result_dups.items():
            form = forms_by_id[fid]
            recip = client.table('recipients').select('name').eq('id', form['recipient_id']).execute().data[0]
            print(f"  {recip['name']}: Form {fid[:8]}... appears {count} times")

    # List all recipients in order they would appear in PDF
    print(f"\n\nPDF ORDER (first 25 and last 5):")
    all_recipients = []
    for form_id in form_ids:
        form = forms_by_id.get(form_id)
        if form:
            recip = client.table('recipients').select('name').eq('id', form['recipient_id']).execute().data[0]
            all_recipients.append(recip['name'])

    for i, name in enumerate(all_recipients[:25], 1):
        print(f"  {i:2d}. {name}")
    if len(all_recipients) > 25:
        print(f"  ...")
        for i, name in enumerate(all_recipients[-5:], len(all_recipients)-4):
            print(f"  {i:2d}. {name}")

if __name__ == "__main__":
    simulate_pdf_batch()
