"""
Inspect specific pages from a PDF to see what's on them.
"""
import sys
import fitz  # PyMuPDF

def inspect_pages(pdf_path: str, pages: list):
    doc = fitz.open(pdf_path)

    for page_num in pages:
        if page_num < 1 or page_num > doc.page_count:
            print(f"Page {page_num} out of range (1-{doc.page_count})")
            continue

        page = doc[page_num - 1]  # 0-indexed
        text = page.get_text()

        print(f"\n{'='*60}")
        print(f"PAGE {page_num}")
        print(f"{'='*60}")

        # Print first 2000 chars of text
        print(text[:2000])

    doc.close()

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Ken.TTS\Downloads\1099s_Flea_Markets_of_Madi_71_forms (3).pdf"
    pages = [18, 27]  # The duplicate pages
    inspect_pages(pdf_path, pages)
