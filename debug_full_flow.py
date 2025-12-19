"""
Script de debug que simula o fluxo completo da aplicação.
"""
import sys
from pathlib import Path
import os

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from tkinter import Tk, filedialog
from loguru import logger

# Setup logging to see all messages
logger.remove()
logger.add(sys.stderr, level="DEBUG")

def find_tesseract_cmd():
    """Auto-detect Tesseract installation path"""
    import shutil
    
    tesseract_in_path = shutil.which("tesseract")
    if tesseract_in_path:
        return tesseract_in_path
    
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
        title="Selecione a NF 2756 para debug COMPLETO",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        print("Nenhum arquivo selecionado.")
        return
    
    print(f"\n{'='*60}")
    print(f"Arquivo: {pdf_path}")
    print(f"{'='*60}")
    
    # Find tesseract
    tesseract_cmd = find_tesseract_cmd()
    print(f"\n✅ Tesseract CMD: {tesseract_cmd}")
    
    # Read PDF bytes
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    # Import components
    from core.extractor_text import TextExtractor
    from core.extractor_ocr import OCRExtractor
    
    # Initialize extractors
    text_extractor = TextExtractor(min_text_length=50)
    ocr_extractor = OCRExtractor(
        tesseract_cmd=tesseract_cmd,
        language="por",
        dpi=300
    )
    
    # Check if text-based
    is_text_based = text_extractor.is_text_based(pdf_bytes)
    print(f"\n📊 is_text_based: {is_text_based}")
    
    if is_text_based:
        print("➡️ Usando TextExtractor...")
        doc = text_extractor.extract(pdf_bytes, os.path.basename(pdf_path))
    else:
        print("➡️ Usando OCRExtractor...")
        doc = ocr_extractor.extract(pdf_bytes, os.path.basename(pdf_path), page_limit=0)
    
    # Print results
    print(f"\n{'='*60}")
    print("📋 RESULTADO DA EXTRAÇÃO:")
    print(f"{'='*60}")
    print(f"Número: {doc.numero}")
    print(f"Tipo: {doc.document_type}")
    print(f"Data Emissão: {doc.data_emissao}")
    print(f"Emitente CNPJ: {doc.emitente.cnpj if doc.emitente else 'N/A'}")
    print(f"Emitente Nome: {doc.emitente.razao_social if doc.emitente else 'N/A'}")
    print(f"Destinatário CNPJ: {doc.destinatario.cnpj if doc.destinatario else 'N/A'}")
    print(f"Destinatário Nome: {doc.destinatario.razao_social if doc.destinatario else 'N/A'}")
    print(f"Error: {doc.error_message if doc.error_message else 'None'}")

if __name__ == "__main__":
    main()
