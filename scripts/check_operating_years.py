"""
Check operating years and forms distribution.
"""
import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from collections import defaultdict

def check_operating_years():
    client = get_supabase_client()

    # Get all operating years
    years = client.table('operating_years').select('*').execute().data
    print(f"Operating years: {len(years)}")
    for y in years:
        print(f"  - {y['id'][:8]}... tax_year={y.get('tax_year')} is_current={y.get('is_current')}")

    # Get forms grouped by operating year
    forms = client.table('forms_1099').select('id, operating_year_id, filer_id, form_type, created_at').execute().data
    print(f"\nTotal forms: {len(forms)}")

    by_year = defaultdict(list)
    for f in forms:
        by_year[f['operating_year_id']].append(f)

    print(f"\nForms by operating year:")
    for year_id, year_forms in by_year.items():
        year = next((y for y in years if y['id'] == year_id), None)
        tax_year = year.get('tax_year') if year else 'Unknown'
        print(f"  - {tax_year}: {len(year_forms)} forms")

    # Check for duplicate recipient/filer combos across different operating years
    print("\n--- Same recipient in multiple years? ---")
    forms_full = client.table('forms_1099').select('id, filer_id, recipient_id, operating_year_id, form_type').execute().data

    by_recip_filer = defaultdict(list)
    for f in forms_full:
        key = (f['filer_id'], f['recipient_id'])
        by_recip_filer[key].append(f)

    multi_year = {k: v for k, v in by_recip_filer.items() if len(v) > 1}
    print(f"Recipient/Filer combos with multiple forms: {len(multi_year)}")

    for key, forms_list in list(multi_year.items())[:5]:
        recip = client.table('recipients').select('name').eq('id', key[1]).execute().data
        recip_name = recip[0]['name'] if recip else 'Unknown'
        print(f"\n  {recip_name}:")
        for f in forms_list:
            year = next((y for y in years if y['id'] == f['operating_year_id']), None)
            tax_year = year.get('tax_year') if year else 'Unknown'
            print(f"    - {f['form_type']} in year {tax_year}")

if __name__ == "__main__":
    check_operating_years()
