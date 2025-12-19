"""
Script de debug para verificar extração de destinatário/tomador.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

import pdfplumber
import re
from tkinter import Tk, filedialog

def main():
    root = Tk()
    root.withdraw()
    pdf_path = filedialog.askopenfilename(
        title="Selecione uma NFS-e de Caieiras para debug",
        filetypes=[("PDF files", "*.pdf")]
    )
    
    if not pdf_path:
        print("Nenhum arquivo selecionado.")
        return
    
    print(f"\n{'='*60}")
    print(f"Arquivo: {pdf_path}")
    print(f"{'='*60}")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"
    
    print("\n📄 TEXTO COMPLETO:")
    print(full_text)
    
    print(f"\n{'='*60}")
    print("🔍 ANÁLISE DA SEÇÃO TOMADOR:")
    print(f"{'='*60}")
    
    # Encontrar seção TOMADOR
    text_upper = full_text.upper()
    start_pos = text_upper.find('TOMADOR')
    if start_pos != -1:
        end_pos = len(full_text)
        for end_label in ['VALORES', 'DISCRIMINA', 'SERVIÇO', 'TOTAL', 'LOCAL']:
            pos = text_upper.find(end_label, start_pos + 7)
            if pos != -1 and pos < end_pos:
                end_pos = pos
        
        section = full_text[start_pos:end_pos]
        print(f"\n📌 Seção TOMADOR encontrada (pos {start_pos}-{end_pos}):")
        print(section)
        
        # Testar extração de CNPJ
        cnpj_match = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2}\b', section)
        if cnpj_match:
            cnpj = re.sub(r'\D', '', cnpj_match.group(0))
            print(f"\n✅ CNPJ encontrado: {cnpj}")
        else:
            print("\n❌ CNPJ NÃO encontrado na seção!")
            
        # Testar padrão específico
        cnpj_patterns = [
            r'CNPJ\s*[:\s]*(\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2})',
        ]
        for pattern in cnpj_patterns:
            match = re.search(pattern, section, re.IGNORECASE)
            if match:
                print(f"✅ Padrão '{pattern[:30]}...' encontrou: {match.group(1)}")
    else:
        print("❌ Seção TOMADOR não encontrada!")

if __name__ == "__main__":
    main()
