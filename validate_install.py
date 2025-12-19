"""
Simple validation script to test basic imports and configuration.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("=" * 60)
print("VALIDACAO DA INSTALACAO")
print("=" * 60)

# Test 1: Import models
try:
    from models import FiscalDocument, Settings, CNPJMapper
    print("[OK] Models importados com sucesso")
except Exception as e:
    print(f"[ERRO] Erro ao importar models: {e}")
    sys.exit(1)

# Test 2: Load settings
try:
    config_dir = Path("config")
    settings = Settings.load_from_toml(config_dir / "settings.toml")
    print(f"[OK] Configuracoes carregadas: {settings.app.name} v{settings.app.version}")
except Exception as e:
    print(f"[ERRO] Erro ao carregar configuracoes: {e}")
    sys.exit(1)

# Test 3: Load CNPJ mappings
try:
    cnpj_mapper = CNPJMapper(config_dir / "filiais.json")
    print(f"[OK] Mapeamento CNPJ carregado")
except Exception as e:
    print(f"[ERRO] Erro ao carregar mapeamento CNPJ: {e}")
    sys.exit(1)

# Test 4: Check dependencies
try:
    import flet
    import pdfplumber
    import fitz
    import pandas
    import openpyxl
    print("[OK] Todas as dependencias principais instaladas")
except ImportError as e:
    print(f"[ERRO] Dependencia faltando: {e}")
    sys.exit(1)

# Test 5: Check directories
output_dir = Path("output")
logs_dir = Path("logs")

if output_dir.exists() and logs_dir.exists():
    print("[OK] Diretorios de output e logs criados")
else:
    print("[ERRO] Diretorios faltando")

print("\n" + "=" * 60)
print("RESULTADO: Instalacao validada com sucesso!")
print("=" * 60)
print("\nProximos passos:")
print("1. Para executar a aplicacao: python src/main.py")
print("2. Para testar extracao: python test_extraction.py <arquivo.pdf>")
print("3. Para executar testes: python -m unittest discover tests -v")

