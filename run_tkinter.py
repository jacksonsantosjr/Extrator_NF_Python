"""
Fiscal Document Extractor - CustomTkinter Launcher
"""
import sys
from pathlib import Path
import tempfile
import customtkinter as ctk

# Add src directory to Python path
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from loguru import logger
from models import Settings, CNPJMapper, EnvironmentSettings
from core import HybridExtractor, ProcessingOrchestrator
from utils import ExcelReporter
from ui.app_tkinter import FiscalExtractorAppTk

def setup_logging(log_level: str = "INFO"):
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    logger.add(str(logs_dir / "app_tk_{time:YYYY-MM-DD}.log"), level=log_level)

def cleanup_temp_dir(path: Path):
    """Clean up temporary directory on startup"""
    try:
        if path.exists():
            for item in path.glob("*"):
                if item.is_file():
                    item.unlink()
            logger.info(f"Cleaned up temp directory: {path}")
    except Exception as e:
        logger.warning(f"Failed to clean temp dir: {e}")

def find_tesseract_cmd() -> str:
    """Auto-detect Tesseract installation path (works for any user)"""
    import os
    import shutil
    
    # 1. Check if tesseract is in PATH
    tesseract_in_path = shutil.which("tesseract")
    if tesseract_in_path:
        logger.info(f"Tesseract found in PATH: {tesseract_in_path}")
        return tesseract_in_path
    
    # 2. Check common installation paths (dynamically for current user)
    user_home = Path(os.path.expanduser("~"))
    common_paths = [
        # User-specific AppData installation
        user_home / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        user_home / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe",
        # System-wide installations
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    
    for path in common_paths:
        if path.exists():
            logger.info(f"Tesseract found at: {path}")
            return str(path)
    
    logger.warning("Tesseract not found! OCR for scanned PDFs will not work.")
    return None

def main():
    # Load configurations
    config_dir = project_root / "config"
    settings = Settings.load_from_toml(config_dir / "settings.toml")
    env_settings = EnvironmentSettings()
    
    setup_logging(env_settings.log_level)
    logger.info("Starting Fiscal Document Extractor (CustomTkinter)")
    
    cnpj_mapper = CNPJMapper(config_dir / "filiais.json")
    
    cnpj_mapper = CNPJMapper(config_dir / "filiais.json")
    
    # Auto-detect Tesseract if not specified in .env
    tesseract_cmd = env_settings.tesseract_cmd or find_tesseract_cmd()
    
    # Use system temp dir to avoid double saving (User request)
    # The user only wants to see the file where they explicitly save it via the UI.
    output_dir = Path(tempfile.gettempdir()) / "FiscalExtractor_Temp"
    cleanup_temp_dir(output_dir) # Clean previous session files
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    extractor = HybridExtractor(
        cnpj_mapper=cnpj_mapper,
        min_text_length=settings.processing.min_text_length,
        tesseract_cmd=tesseract_cmd,
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
    app = FiscalExtractorAppTk(
        orchestrator=orchestrator,
        excel_reporter=excel_reporter,
        output_dir=output_dir,
        icon_path=project_root / "icons8-tarefa-100.png"
    )
    
    app.mainloop()

if __name__ == "__main__":
    main()
