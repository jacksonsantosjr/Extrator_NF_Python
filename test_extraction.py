"""
Script de teste manual para extração de documentos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from models import Settings, CNPJMapper
from core import HybridExtractor


def test_single_file(pdf_path: Path):
    """Testa extração de um único arquivo"""
    
    # Configuração
    config_dir = Path("config")
    settings = Settings.load_from_toml(config_dir / "settings.toml")
    cnpj_mapper = CNPJMapper(config_dir / "filiais.json")
    
    # Criar extrator
    extractor = HybridExtractor(
        cnpj_mapper=cnpj_mapper,
        min_text_length=settings.processing.min_text_length,
        tesseract_cmd=None,  # Ou caminho do Tesseract se necessário
        ocr_language="por",
        ocr_dpi=300,
        pdf_page_limit=0,
    )
    
    # Testar extração
    if not pdf_path.exists():
        print(f"❌ Arquivo não encontrado: {pdf_path}")
        return
    
    print(f"\n{'='*70}")
    print(f"Testando: {pdf_path.name}")
    print(f"{'='*70}\n")
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    
    doc, time_taken = extractor.extract(pdf_bytes, pdf_path.name)
    
    # Exibir resultados
    print(f"📄 INFORMAÇÕES DO DOCUMENTO")
    print(f"   Status: {doc.processing_status.value}")
    print(f"   Tipo: {doc.document_type.value}")
    print(f"   Número: {doc.numero or 'N/A'}")
    print(f"   Série: {doc.serie or 'N/A'}")
    print(f"   Chave de Acesso: {doc.chave_acesso or 'N/A'}")
    print(f"   Data Emissão: {doc.data_emissao or 'N/A'}")
    
    print(f"\n🏢 EMITENTE")
    if doc.emitente:
        print(f"   CNPJ: {doc.emitente.cnpj or 'N/A'}")
        print(f"   Razão Social: {doc.emitente.razao_social or 'N/A'}")
    else:
        print(f"   Não extraído")
    
    print(f"\n🏢 DESTINATÁRIO")
    if doc.destinatario:
        print(f"   CNPJ: {doc.destinatario.cnpj or 'N/A'}")
        print(f"   Razão Social: {doc.destinatario.razao_social or 'N/A'}")
    else:
        print(f"   Não extraído")
    
    print(f"\n💰 VALORES")
    if doc.valores:
        print(f"   Valor Total: R$ {doc.valores.valor_total or 'N/A'}")
        print(f"   Valor Serviços: R$ {doc.valores.valor_servicos or 'N/A'}")
        print(f"   ISS: R$ {doc.valores.iss or 'N/A'}")
    else:
        print(f"   Não extraído")
    
    print(f"\n🏭 MAPEAMENTO")
    print(f"   Coligada: {doc.coligada or 'N/A'}")
    print(f"   Filial: {doc.filial or 'N/A'}")
    
    print(f"\n📊 ITENS/SERVIÇOS")
    print(f"   Total de itens: {len(doc.itens)}")
    if doc.itens:
        for i, item in enumerate(doc.itens[:3], 1):  # Mostrar apenas 3 primeiros
            print(f"   Item {i}: {item.descricao or 'N/A'}")
        if len(doc.itens) > 3:
            print(f"   ... e mais {len(doc.itens) - 3} itens")
    
    print(f"\n⚙️ PROCESSAMENTO")
    print(f"   Tempo: {time_taken:.2f}s")
    print(f"   Escaneado (OCR): {'Sim' if doc.is_scanned else 'Não'}")
    
    if doc.error_message:
        print(f"\n⚠️ ERRO")
        print(f"   {doc.error_message}")
    
    print(f"\n{'='*70}\n")
    
    # Resumo
    if doc.processing_status.value == "Concluído":
        print("✅ Extração bem-sucedida!")
    else:
        print("❌ Extração com erros")


if __name__ == "__main__":
    # Exemplo de uso
    test_file = Path("test_documents/exemplo.pdf")
    
    if len(sys.argv) > 1:
        test_file = Path(sys.argv[1])
    
    test_single_file(test_file)
    
    print("\n💡 Dica: Execute com um arquivo específico:")
    print("   python test_extraction.py caminho/para/seu/arquivo.pdf")
