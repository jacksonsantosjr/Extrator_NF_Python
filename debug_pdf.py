"""
Script de debug para visualizar o texto extraído dos PDFs e identificar padrões.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

import pdfplumber
from tkinter import Tk, filedialog

def main():
    # Selecionar arquivo PDF
    root = Tk()
    root.withdraw()
    pdf_path = filedialog.askopenfilename(
        title="Selecione um PDF para debug",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        print("Nenhum arquivo selecionado.")
        return
    
    print(f"\n{'='*60}")
    print(f"Arquivo: {pdf_path}")
    print(f"{'='*60}\n")
    
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"
            print(f"--- PÁGINA {i+1} ---")
            print(page_text)
            print()
    
    print(f"\n{'='*60}")
    print("ANÁLISE DE PADRÕES:")
    print(f"{'='*60}")
    
    # Procurar padrões específicos
    import re
    
    # Procurar "Nome" ou "Empresarial"
    nome_matches = re.findall(r'.{0,50}(?:Nome|Empresarial|Razão|Social).{0,100}', full_text, re.IGNORECASE)
    if nome_matches:
        print("\n📌 Padrões com 'Nome/Empresarial/Razão/Social':")
        for m in nome_matches[:10]:
            print(f"  → {m.strip()}")
    
    # Procurar EMITENTE/PRESTADOR
    emitente_matches = re.findall(r'.{0,30}(?:EMITENTE|PRESTADOR).{0,150}', full_text, re.IGNORECASE)
    if emitente_matches:
        print("\n📌 Padrões com 'EMITENTE/PRESTADOR':")
        for m in emitente_matches[:5]:
            print(f"  → {m.strip()}")
    
    # Após CNPJ
    cnpj_matches = re.findall(r'(?:\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2}).{0,100}', full_text)
    if cnpj_matches:
        print("\n📌 Texto após CNPJ:")
        for m in cnpj_matches[:5]:
            print(f"  → {m.strip()}")

if __name__ == "__main__":
    main()
