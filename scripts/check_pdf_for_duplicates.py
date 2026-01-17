"""
Check a PDF file for duplicate pages by comparing text content.
Usage: py -3.12 scripts/check_pdf_for_duplicates.py <path_to_pdf>
"""
import sys
import fitz  # PyMuPDF

def check_pdf_duplicates(pdf_path: str):
    print(f"Checking PDF for duplicates: {pdf_path}\n")

    doc = fitz.open(pdf_path)
    print(f"Total pages: {doc.page_count}")

    # Extract text from each page and look for duplicates
    page_texts = {}
    page_names = {}  # Store recipient name from each page
    duplicates = []

    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()

        # Try to extract recipient name (usually near top of form)
        lines = text.split('\n')
        recipient_name = "Unknown"
        for j, line in enumerate(lines):
            # Look for name after "RECIPIENT'S name" or similar
            if 'name' in line.lower() and j + 1 < len(lines):
                candidate = lines[j + 1].strip()
                if candidate and len(candidate) > 2 and not candidate.startswith('$'):
                    recipient_name = candidate
                    break

        # Also try to find TIN for more unique identification
        tin_last4 = ""
        for line in lines:
            if line.strip().endswith(')') and '***' in line:
                # Masked TIN like "***-**-1234"
                tin_last4 = line.strip()[-5:-1] if len(line.strip()) > 5 else ""
                break

        page_key = f"{recipient_name}|{tin_last4}"
        page_names[i + 1] = f"{recipient_name} ({tin_last4})" if tin_last4 else recipient_name

        # Use a hash of the text content for exact duplicate detection
        text_hash = hash(text.strip())

        if text_hash in page_texts:
            original_page = page_texts[text_hash]
            duplicates.append({
                'original': original_page,
                'duplicate': i + 1,
                'name': page_names[i + 1]
            })
        else:
            page_texts[text_hash] = i + 1

    total_pages = doc.page_count
    doc.close()

    if duplicates:
        print(f"\n*** DUPLICATES FOUND: {len(duplicates)} ***\n")
        for dup in duplicates:
            print(f"  Page {dup['duplicate']} is duplicate of Page {dup['original']}")
            print(f"    Recipient: {dup['name']}")
    else:
        print(f"\nNo duplicates found! All {total_pages} pages are unique.")

    # Also list first 10 and last 5 recipients
    print(f"\nFirst 10 recipients:")
    for i in range(1, min(11, len(page_names) + 1)):
        print(f"  {i:2d}. {page_names.get(i, 'Unknown')}")

    if len(page_names) > 15:
        print(f"  ...")
        print(f"Last 5 recipients:")
        for i in range(len(page_names) - 4, len(page_names) + 1):
            print(f"  {i:2d}. {page_names.get(i, 'Unknown')}")

    return len(duplicates)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default to looking for recent PDF in Downloads
        import os
        downloads = os.path.expanduser("~/Downloads")
        pdfs = [f for f in os.listdir(downloads) if f.endswith('.pdf') and '1099' in f.lower()]
        if pdfs:
            pdfs.sort(key=lambda x: os.path.getmtime(os.path.join(downloads, x)), reverse=True)
            pdf_path = os.path.join(downloads, pdfs[0])
            print(f"Using most recent 1099 PDF: {pdfs[0]}\n")
        else:
            print("Usage: py -3.12 scripts/check_pdf_for_duplicates.py <path_to_pdf>")
            sys.exit(1)
    else:
        pdf_path = sys.argv[1]

    check_pdf_duplicates(pdf_path)
