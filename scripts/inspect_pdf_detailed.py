"""
Detailed inspection of PDF pages to find the actual recipient data.
"""
import sys
import fitz  # PyMuPDF

def inspect_pages_detailed(pdf_path: str):
    doc = fitz.open(pdf_path)

    print(f"Total pages: {doc.page_count}\n")

    # Extract key info from each page
    page_info = []

    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()

        # Look for dollar amounts (the compensation amount)
        import re
        amounts = re.findall(r'\$[\d,]+\.\d{2}', text)
        # Also look for amounts without $ sign that look like money
        bare_amounts = re.findall(r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', text)

        # Look for TIN patterns (masked or full)
        tins = re.findall(r'\*{3}-\*{2}-\d{4}', text)  # Masked: ***-**-1234
        full_tins = re.findall(r'\d{3}-\d{2}-\d{4}', text)  # Full SSN
        ein_tins = re.findall(r'\d{2}-\d{7}', text)  # EIN format

        # Get all text blocks with their positions
        blocks = page.get_text("blocks")

        # Find text that looks like names (capitalized words)
        names = []
        for block in blocks:
            block_text = block[4] if len(block) > 4 else ""
            # Look for lines that could be names (mixed case, no numbers at start)
            lines = block_text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and len(line) > 3 and not line[0].isdigit() and not line.startswith('$'):
                    # Skip common form text
                    if not any(skip in line.lower() for skip in ['form', 'copy', 'irs', 'tax', 'payer', 'recipient', 'box', 'instructions', 'nonemployee']):
                        if any(c.isupper() for c in line) and any(c.islower() for c in line):
                            names.append(line[:50])

        page_info.append({
            'page': i + 1,
            'amounts': amounts + bare_amounts,
            'tins': tins + full_tins + ein_tins,
            'possible_names': names[:3]  # First 3 possible names
        })

    # Print summary
    print("Page-by-page analysis:\n")
    for info in page_info:
        amounts_str = ', '.join(info['amounts'][:2]) if info['amounts'] else 'None found'
        tins_str = ', '.join(info['tins'][:1]) if info['tins'] else 'None found'
        names_str = info['possible_names'][0] if info['possible_names'] else 'Unknown'

        print(f"Page {info['page']:2d}: Amount={amounts_str:20s} TIN={tins_str:15s} Name={names_str}")

    # Check for exact duplicates
    print("\n\nChecking for duplicate content...")
    seen_content = {}
    for i in range(doc.page_count):
        page = doc[i]
        # Get page content hash
        text = page.get_text()
        content_hash = hash(text)

        if content_hash in seen_content:
            print(f"  Page {i+1} is DUPLICATE of Page {seen_content[content_hash]}")
        else:
            seen_content[content_hash] = i + 1

    doc.close()

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Ken.TTS\Downloads\1099s_Flea_Markets_of_Madi_71_forms (3).pdf"
    inspect_pages_detailed(pdf_path)
