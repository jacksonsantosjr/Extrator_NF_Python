"""
Debug para ver texto OCR e seção TOMADOR.
"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from tkinter import Tk, filedialog
import re

def find_tesseract_cmd():
    import shutil
    user_home = Path(os.path.expanduser("~"))
    common_paths = [
        user_home / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for path in common_paths:
        if path.exists():
            return str(path)
    return shutil.which("tesseract")

def main():
    root = Tk()
    root.withdraw()
    pdf_path = filedialog.askopenfilename(
        title="Selecione a NF 2756",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        return
    
    # Read PDF and do OCR
    tesseract_cmd = find_tesseract_cmd()
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    
    import fitz
    from PIL import Image
    import io
    
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = pdf_doc[0]
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    ocr_text = pytesseract.image_to_string(img, lang='por')
    pdf_doc.close()
    
    print(f"\n{'='*60}")
    print("🔍 TEXTO OCR DA PRIMEIRA PÁGINA:")
    print(f"{'='*60}")
    print(ocr_text)
    
    print(f"\n{'='*60}")
    print("🔍 ANÁLISE DA SEÇÃO TOMADOR:")
    print(f"{'='*60}")
    
    # Find TOMADOR section (as the code does it)
    text_upper = ocr_text.upper()
    start_pos = text_upper.find('TOMADOR')
    
    if start_pos != -1:
        # Skip to next line after label
        start_pos += len('TOMADOR')
        newline_pos = ocr_text.find('\n', start_pos)
        if newline_pos != -1 and newline_pos < start_pos + 50:
            start_pos = newline_pos + 1
        
        # Find end
        end_pos = len(ocr_text)
        for label in ['VALORES', 'DISCRIMINA', 'SERVIÇO', 'LOCAL', 'DADOS']:
            pos = text_upper.find(label, start_pos)
            if pos != -1 and pos < end_pos:
                end_pos = pos
        
        section = ocr_text[start_pos:end_pos]
        print(f"Seção TOMADOR (pos {start_pos}:{end_pos}):")
        print(f"'{section}'")
        
        # Test CNPJ patterns
        print(f"\n📊 TESTE DE PADRÕES DE CNPJ:")
        
        cnpj_patterns = [
            (r'CNPJ\s*[:\s]+(\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2})', "Específico com label"),
            (r'\b(\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2})\b', "Genérico"),
            (r'\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b', "Formatado padrão"),
        ]
        
        for pattern, name in cnpj_patterns:
            match = re.search(pattern, section, re.IGNORECASE)
            if match:
                print(f"✅ '{name}': {match.group(1)}")
            else:
                print(f"❌ '{name}': Não encontrou")
        
        # Show all potential CNPJ-like strings
        print(f"\n📝 Strings que parecem CNPJ na seção:")
        all_cnpjs = re.findall(r'\d{2}[.\s]*\d{3}[.\s]*\d{3}[/.\s]*\d{4}[-.\s]*\d{2}', section)
        for cnpj in all_cnpjs:
            print(f"  - '{cnpj}'")
    else:
        print("❌ Seção TOMADOR não encontrada!")

if __name__ == "__main__":
    main()
