#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de Teste de Extração de Retenções
Permite testar a extração em arquivos específicos e validar resultados
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.extractor_text import TextExtractor
from loguru import logger

# Configure logger para mostrar DEBUG
logger.remove()
logger.add(sys.stderr, level="INFO")


def test_single_file(pdf_path: str):
    """Testa extração de um arquivo específico."""
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"[ERRO] Arquivo não encontrado: {pdf_path}")
        return
    
    print("\n" + "="*80)
    print(f"TESTANDO: {pdf_path.name}")
    print("="*80)
    
    # Read PDF
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    # Extract
    extractor = TextExtractor()
    doc = extractor.extract(pdf_bytes, pdf_path.name)
    
    # Display results
    print(f"\n📄 Tipo: {doc.document_type.value}")
    print(f"📋 Número: {doc.numero}")
    print(f"📅 Data Emissão: {doc.data_emissao}")
    
    if doc.valores:
        print(f"\n💰 VALORES:")
        print(f"  Valor Total: R$ {doc.valores.valor_total or 'N/A'}")
        print(f"  Valor Líquido: R$ {doc.valores.valor_liquido or 'N/A'}")
        
        print(f"\n🔒 RETENÇÕES EXTRAÍDAS:")
        print(f"  PIS Retido:    R$ {doc.valores.pis_retido or '0,00' if doc.valores.pis_retido == 0 else doc.valores.pis_retido or 'NÃO ENCONTRADO'}")
        print(f"  COFINS Retido: R$ {doc.valores.cofins_retido or '0,00' if doc.valores.cofins_retido == 0 else doc.valores.cofins_retido or 'NÃO ENCONTRADO'}")
        print(f"  CSLL Retida:   R$ {doc.valores.csll_retida or '0,00' if doc.valores.csll_retida == 0 else doc.valores.csll_retida or 'NÃO ENCONTRADO'}")
        print(f"  IRRF Retido:   R$ {doc.valores.ir or '0,00' if doc.valores.ir == 0 else doc.valores.ir or 'NÃO ENCONTRADO'}")
        print(f"  INSS Retido:   R$ {doc.valores.inss or '0,00' if doc.valores.inss == 0 else doc.valores.inss or 'NÃO ENCONTRADO'}")
        print(f"  ISS Retido:    R$ {doc.valores.iss_retido or '0,00' if doc.valores.iss_retido == 0 else doc.valores.iss_retido or 'NÃO ENCONTRADO'}")
    
    print("\n" + "="*80)
    print("VALIDAÇÃO:")
    print("="*80)
    print("Por favor, verifique se os valores acima estão corretos.")
    print("Marque cada campo como:")
    print("  ✓ - Correto")
    print("  ✗ - Incorreto ou não encontrado (mas deveria)")
    print("  N/A - Não aplicável (documento não tem essa retenção)")
    print("\n")


def test_batch(folder_path: str, file_list: list):
    """Testa múltiplos arquivos."""
    
    folder = Path(folder_path)
    
    print("\n" + "="*80)
    print(f"TESTE EM LOTE - {len(file_list)} arquivos")
    print("="*80)
    
    results = []
    
    for filename in file_list:
        pdf_path = folder / filename
        if not pdf_path.exists():
            print(f"\n[AVISO] Arquivo não encontrado: {filename}")
            continue
        
        print(f"\n📄 {filename}")
        
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        extractor = TextExtractor()
        doc = extractor.extract(pdf_bytes, filename)
        
        if doc.valores:
            result = {
                'arquivo': filename,
                'pis': doc.valores.pis_retido,
                'cofins': doc.valores.cofins_retido,
                'csll': doc.valores.csll_retida,
                'irrf': doc.valores.ir,
                'inss': doc.valores.inss,
                'iss': doc.valores.iss_retido,
            }
            results.append(result)
            
            # Display summary
            found = sum(1 for v in result.values() if v and isinstance(v, (int, float)) and v > 0)
            print(f"  Retenções encontradas: {found}/6")
        else:
            print(f"  [ERRO] Valores não extraídos")
    
    # Summary table
    print("\n" + "="*80)
    print("RESUMO")
    print("="*80)
    print(f"{'Arquivo':<40} {'PIS':<10} {'COFINS':<10} {'CSLL':<10} {'IRRF':<10} {'INSS':<10} {'ISS':<10}")
    print("-"*80)
    
    for r in results:
        print(f"{r['arquivo'][:38]:<40} "
              f"{str(r['pis'] or '-'):<10} "
              f"{str(r['cofins'] or '-'):<10} "
              f"{str(r['csll'] or '-'):<10} "
              f"{str(r['irrf'] or '-'):<10} "
              f"{str(r['inss'] or '-'):<10} "
              f"{str(r['iss'] or '-'):<10}")


def main():
    """Menu principal."""
    
    print("\n" + "="*80)
    print("TESTE DE EXTRAÇÃO DE RETENÇÕES FISCAIS")
    print("="*80)
    print("\nEscolha uma opção:")
    print("1. Testar arquivo único (detalhado)")
    print("2. Testar lote de arquivos (resumo)")
    print("3. Testar arquivo TOTVS específico")
    print("\n")
    
    choice = input("Opção: ").strip()
    
    base_folder = r"C:\Users\jackson.junior\Downloads\Conferência de Notas Fiscais"
    
    if choice == "1":
        filename = input("\nNome do arquivo (ex: NF TOTVS CENSO 6.704,64.pdf): ").strip()
        pdf_path = Path(base_folder) / filename
        test_single_file(str(pdf_path))
    
    elif choice == "2":
        print("\nArquivos sugeridos para teste:")
        suggested_files = [
            "NF TOTVS CENSO 6.704,64.pdf",
            "NF BGM - VCCL 1.pdf",
            "NF. 114831 - VERZANI.pdf",
            "NF. 114888 - VERZANI - 746249.pdf",
            "NF. 1763 - REAMBIENT.pdf",
            "NF. 1764 - REMABIENT.pdf",
            "NF BRY CENSO.pdf",
            "NF VSB_dezembro 25.pdf",
            "NF 3998 - Sta. Brigida - Dez 2025.pdf",
            "10166 Caieiras 0001-74.pdf",
        ]
        
        for i, f in enumerate(suggested_files, 1):
            print(f"  {i}. {f}")
        
        print("\nPressione ENTER para testar todos os sugeridos ou digite números separados por vírgula:")
        selection = input("Seleção: ").strip()
        
        if selection:
            indices = [int(x.strip())-1 for x in selection.split(',')]
            files_to_test = [suggested_files[i] for i in indices if 0 <= i < len(suggested_files)]
        else:
            files_to_test = suggested_files
        
        test_batch(base_folder, files_to_test)
    
    elif choice == "3":
        # Teste específico do arquivo TOTVS
        pdf_path = Path(base_folder) / "NF TOTVS CENSO 6.704,64.pdf"
        test_single_file(str(pdf_path))
        
        print("\n" + "="*80)
        print("VALORES ESPERADOS (conforme imagens fornecidas):")
        print("="*80)
        print("  PIS Retido:    R$ 43,58 (ou parte de R$ 244,72 consolidado)")
        print("  COFINS Retido: R$ 201,14 (ou parte de R$ 244,72 consolidado)")
        print("  CSLL Retida:   R$ 67,05")
        print("  PIS/COFINS consolidado: R$ 244,72")
        print("="*80)


if __name__ == "__main__":
    main()
