"""
Debug COMPLETO: Extrai e gera Excel, igual a UI.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level} | {message}")

from models import ProcessingStatus
from core.extractor_ocr import OCRExtractor
from utils import ExcelReporter
import os
from dotenv import load_dotenv

load_dotenv()

def debug_complete_flow(pdf_paths):
    """Simula extração e geração de Excel."""
    tesseract_cmd = os.getenv("TESSERACT_CMD")
    ocr_extractor = OCRExtractor(tesseract_cmd=tesseract_cmd, language="por", dpi=400)
    
    results = []
    
    for pdf_path in pdf_paths:
        pdf_file = Path(pdf_path)
        print(f"\n{'='*60}")
        print(f"Processando: {pdf_file.name}")
        print(f"{'='*60}")
        
        with open(pdf_file, "rb") as f:
            pdf_bytes = f.read()
        
        doc = ocr_extractor.extract(pdf_bytes, pdf_file.name, page_limit=2)
        doc.processing_status = ProcessingStatus.COMPLETED
        results.append(doc)
        
        print(f"  Resultado:")
        print(f"    Número: {doc.numero}")
        print(f"    Emitente: {doc.emitente.razao_social if doc.emitente else 'None'}")
        print(f"    Destinatário CNPJ: {doc.destinatario.cnpj if doc.destinatario else 'None'}")
        print(f"    Destinatário Razão: {doc.destinatario.razao_social if doc.destinatario else 'None'}")
    
    # Gerar Excel
    print(f"\n{'='*60}")
    print("GERANDO EXCEL")
    print(f"{'='*60}")
    
    output_dir = Path("debug_output")
    output_dir.mkdir(exist_ok=True)
    
    excel_reporter = ExcelReporter(output_dir=output_dir)
    report_path = excel_reporter.generate_report(results)
    
    print(f"\n✅ Relatório gerado: {report_path}")
    print(f"\nPor favor, abra o arquivo e verifique a coluna 'Destinatário CNPJ/CPF'")
    
    # Abrir automaticamente
    os.startfile(report_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python debug_complete.py <pdf1 ou diretório> [pdf2] ...")
    else:
        paths = []
        for arg in sys.argv[1:]:
            p = Path(arg)
            if p.is_dir():
                # Collect all PDFs from directory
                paths.extend(sorted(p.glob("*.pdf")))
            elif p.is_file() and p.suffix.lower() == ".pdf":
                paths.append(p)
        
        if paths:
            print(f"Processando {len(paths)} arquivo(s)...")
            debug_complete_flow([str(p) for p in paths])
        else:
            print("Nenhum arquivo PDF encontrado.")
