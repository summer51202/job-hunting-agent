"""Check text, page count, DOCX/PDF consistency and preserved source facts."""
import re
import unicodedata

from docx import Document
from pypdf import PdfReader


def canonical(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(re.findall(r'[a-z0-9][a-z0-9+#]*', text))


def audit(docx_path, pdf_path, *, expected_pages, source_bullets=(), cover_letter=False):
    doc = Document(docx_path)
    docx_text = '\n'.join(paragraph.text for paragraph in doc.paragraphs)
    pdf = PdfReader(pdf_path)
    pdf_text = [page.extract_text() or '' for page in pdf.pages]
    docx_canonical = canonical(docx_text)
    pdf_canonical = canonical('\n'.join(pdf_text))
    source_bullets = tuple(source_bullets)
    checks = {'pdf_pages': len(pdf.pages),
              'expected_pdf_pages': expected_pages,
              'all_pdf_pages_have_ats_text': all(canonical(page) for page in pdf_text),
              'docx_pdf_text_order_equal': docx_canonical == pdf_canonical,
              'source_bullets_preserved': all(canonical(bullet) in docx_canonical
                                              and canonical(bullet) in pdf_canonical
                                              for bullet in source_bullets),
              'source_bullets_count': len(source_bullets)}
    if cover_letter:
        checks['english_words'] = len(re.findall(r"[A-Za-z]+(?:[’'-][A-Za-z]+)*", docx_text))
    checks['passed'] = (len(pdf.pages) == expected_pages
                        and checks['all_pdf_pages_have_ats_text']
                        and checks['docx_pdf_text_order_equal']
                        and checks['source_bullets_preserved']
                        and (not cover_letter or 250 <= checks['english_words'] <= 350))
    return checks
