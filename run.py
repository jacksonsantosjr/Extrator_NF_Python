"""
Fiscal Document Extractor - Launcher Script

This script properly configures the Python path and launches the application.
Use this instead of running src/main.py directly to avoid import issues.

Usage:
    python run.py
    or
    venv\Scripts\python.exe run.py
"""
import sys
from pathlib import Path

# Add src directory to Python path
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# Now we can import everything properly
import flet as ft
from loguru import logger

from models import Settings, CNPJMapper, EnvironmentSettings
from core import HybridExtractor, ProcessingOrchestrator
from utils import ExcelReporter
from ui import FiscalExtractorApp


def setup_logging(log_level: str = "INFO"):
    """Configure logging"""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
    )
    
    # Create logs directory if it doesn't exist
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    logger.add(
        str(logs_dir / "app_{time:YYYY-MM-DD}.log"),
        rotation="1 day",
        retention="7 days",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}"
    )


def main(page: ft.Page):
    """Main application entry point"""
    
    # Load configurations
    config_dir = project_root / "config"
    settings = Settings.load_from_toml(config_dir / "settings.toml")
    env_settings = EnvironmentSettings()
    
    # Setup logging
    setup_logging(env_settings.log_level)
    logger.info("Starting Fiscal Document Extractor")
    
    # Load CNPJ mapper
    cnpj_mapper = CNPJMapper(config_dir / "filiais.json")
    
    # Create output directory
    output_dir = Path(env_settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    extractor = HybridExtractor(
        cnpj_mapper=cnpj_mapper,
        min_text_length=settings.processing.min_text_length,
        tesseract_cmd=env_settings.tesseract_cmd,
        ocr_language=settings.ocr.language,
        ocr_dpi=settings.ocr.dpi,
        pdf_page_limit=settings.processing.pdf_page_limit,
        llm_enabled=settings.llm.enabled,
        llm_model=settings.llm.model_name,
        llm_url=settings.llm.base_url,
    )
    
    orchestrator = ProcessingOrchestrator(
        extractor=extractor,
        max_workers=settings.processing.max_concurrent_files,
    )
    
    excel_reporter = ExcelReporter(output_dir=output_dir)
    
    # Create and run UI
    app = FiscalExtractorApp(
        orchestrator=orchestrator,
        excel_reporter=excel_reporter,
        output_dir=output_dir,
    )
    
    app.build(page)
    
    logger.info("Application UI initialized")


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("Fiscal Document Extractor")
        print("=" * 60)
        print("Iniciando aplicacao...")
        print("Aguarde a janela abrir...")
        print()
        
        ft.app(target=main)
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        print(f"\nERRO: {e}")
        print("\nVerifique o arquivo de log para mais detalhes.")
        sys.exit(1)
