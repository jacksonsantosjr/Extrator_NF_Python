"""
Script de debug para verificar o fluxo is_text_based na NF 2756.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

import pdfplumber
from tkinter import Tk, filedialog

def main():
    root = Tk()
    root.withdraw()
    pdf_path = filedialog.askopenfilename(
        title="Selecione a NF 2756 para debug",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        print("Nenhum arquivo selecionado.")
        return
    
    print(f"\n{'='*60}")
    print(f"Arquivo: {pdf_path}")
    print(f"{'='*60}")
    
    # Read PDF bytes
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    import io
    
    # Check what pdfplumber extracts
    print("\n🔍 Verificando extração com pdfplumber:")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if len(pdf.pages) > 0:
            text = pdf.pages[0].extract_text() or ""
            text_length = len(text.strip())
            
            print(f"Texto extraído (length={text_length}):")
            print(f"'{text[:200]}...' " if len(text) > 200 else f"'{text}'")
            
            # Check is_text_based logic (min_text_length = 50)
            min_text_length = 50
            is_text_based = text_length >= min_text_length
            
            print(f"\n📊 Análise:")
            print(f"  - Comprimento do texto: {text_length}")
            print(f"  - Mínimo requerido: {min_text_length}")
            print(f"  - is_text_based: {is_text_based}")
            
            if is_text_based:
                print(f"\n⚠️  PROBLEMA: PDF está sendo classificado como 'text-based'")
                print(f"    mas o texto extraído pode estar incompleto/corrompido!")
            else:
                print(f"\n✅ PDF será processado via OCR (is_text_based=False)")
    
    # Check what chars are in the extracted text
    if text:
        print(f"\n📝 Caracteres únicos no texto: {set(text[:100])}")

if __name__ == "__main__":
    main()
