"""
Script de debug para testar OCR diretamente na NF 2756.
"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from PIL import Image
import fitz  # PyMuPDF
from tkinter import Tk, filedialog

def find_tesseract():
    """Auto-detect Tesseract"""
    import shutil
    
    # Check PATH
    tesseract_in_path = shutil.which("tesseract")
    if tesseract_in_path:
        return tesseract_in_path
    
    # Check common paths
    user_home = Path(os.path.expanduser("~"))
    common_paths = [
        user_home / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        user_home / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    
    for path in common_paths:
        if path.exists():
            return str(path)
    
    return None

def main():
    root = Tk()
    root.withdraw()
    pdf_path = filedialog.askopenfilename(
        title="Selecione a NF 2756 para debug OCR",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        print("Nenhum arquivo selecionado.")
        return
    
    print(f"\n{'='*60}")
    print(f"Arquivo: {pdf_path}")
    print(f"{'='*60}")
    
    # Check Tesseract
    tesseract_path = find_tesseract()
    if tesseract_path:
        print(f"\n✅ Tesseract encontrado: {tesseract_path}")
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    else:
        print("\n❌ Tesseract NÃO encontrado!")
        return
    
    # Open PDF with PyMuPDF and convert to image
    print("\n📄 Convertendo PDF para imagem...")
    try:
        pdf_doc = fitz.open(pdf_path)
        page = pdf_doc[0]
        
        # Render page at 300 DPI
        zoom = 300 / 72  # 300 DPI / default 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        print(f"✅ Imagem criada: {pix.width}x{pix.height} pixels")
        
        # Run OCR
        print("\n🔍 Executando OCR com Tesseract (Português)...")
        import pytesseract
        ocr_text = pytesseract.image_to_string(img, lang='por')
        
        print(f"\n📝 TEXTO EXTRAÍDO VIA OCR:")
        print("="*60)
        print(ocr_text)
        print("="*60)
        
        # Check for TOMADOR section
        if 'TOMADOR' in ocr_text.upper():
            print("\n✅ Seção TOMADOR encontrada!")
            
            # Try to find CNPJ
            import re
            cnpj_pattern = r'\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2}'
            cnpjs = re.findall(cnpj_pattern, ocr_text)
            if cnpjs:
                print(f"✅ CNPJs encontrados: {cnpjs}")
            else:
                print("❌ Nenhum CNPJ encontrado no texto OCR")
        else:
            print("\n❌ Seção TOMADOR não encontrada no texto OCR")
        
        pdf_doc.close()
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
