"""
Configuration models and loaders.
"""
from typing import Dict, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import tomli
import json
from loguru import logger


class AppConfig(BaseModel):
    """Application configuration"""
    name: str = "Fiscal Document Extractor"
    version: str = "1.0.0"
    theme: str = "dark"


class ProcessingConfig(BaseModel):
    """Processing configuration"""
    max_concurrent_files: int = Field(3, ge=1, le=10)
    pdf_page_limit: int = Field(0, ge=0)
    min_text_length: int = Field(50, ge=10)


class PerformanceConfig(BaseModel):
    """Performance targets"""
    target_text_pdf_seconds: int = 5
    target_scanned_pdf_seconds: int = 60
    target_pdfs_per_hour: int = 100


class OCRConfig(BaseModel):
    """OCR configuration"""
    language: str = "por"
    enable_preprocessing: bool = True
    dpi: int = Field(300, ge=72, le=600)

class ExportConfig(BaseModel):
    """Excel export configuration"""
    auto_fit_columns: bool = True
    apply_filters: bool = True
    freeze_header_row: bool = True


class LLMConfig(BaseModel):
    """Local LLM configuration"""
    enabled: bool = True
    model_name: str = "llama3:8b"
    base_url: str = "http://localhost:11434"
    confidence_threshold: float = 0.8


class Settings(BaseModel):
    """Complete application settings"""
    app: AppConfig = Field(default_factory=AppConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    @classmethod
    def load_from_toml(cls, config_path: Path) -> "Settings":
        """Load settings from TOML file"""
        try:
            with open(config_path, "rb") as f:
                data = tomli.load(f)
            return cls(**data)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}. Using defaults.")
            return cls()


class FilialMapping(BaseModel):
    """Mapping of CNPJ to Coligada/Filial"""
    coligada: str
    filial: str
    nome: str


class CNPJMapper:
    """Manages CNPJ to Coligada/Filial mappings"""
    
    def __init__(self, mapping_path: Path):
        self.mapping_path = mapping_path
        self.mappings: Dict[str, FilialMapping] = {}
        self.load_mappings()
    
    def load_mappings(self):
        """Load CNPJ mappings from JSON file"""
        try:
            with open(self.mapping_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for cnpj, info in data.items():
                # Normalize CNPJ (remove formatting)
                cnpj_normalized = self._normalize_cnpj(cnpj)
                self.mappings[cnpj_normalized] = FilialMapping(**info)
            
            logger.info(f"Loaded {len(self.mappings)} CNPJ mappings")
        except Exception as e:
            logger.error(f"Failed to load CNPJ mappings from {self.mapping_path}: {e}")
    
    def lookup(self, cnpj: Optional[str]) -> Optional[FilialMapping]:
        """
        Lookup mapping for a given CNPJ.
        Returns None if not found.
        """
        if not cnpj:
            return None
        
        cnpj_normalized = self._normalize_cnpj(cnpj)
        mapping = self.mappings.get(cnpj_normalized)
        
        if not mapping:
            logger.warning(f"CNPJ not found in mappings: {cnpj}")
        
        return mapping
    
    @staticmethod
    def _normalize_cnpj(cnpj: str) -> str:
        """Remove all non-numeric characters from CNPJ"""
        import re
        return re.sub(r'\D', '', cnpj)


class EnvironmentSettings(BaseSettings):
    """Environment variables"""
    tesseract_cmd: Optional[str] = None
    log_level: str = "INFO"
    output_dir: str = "./output"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
