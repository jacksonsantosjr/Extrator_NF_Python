"""
Hybrid extraction engine - automatically chooses between text and OCR extraction.
"""
from typing import Tuple
import io
import logging
import re
from datetime import datetime
from loguru import logger
import threading
import pdfplumber
from typing import Callable, Optional

from models import FiscalDocument, ProcessingStatus, CNPJMapper, Entity
from core.extractor_text import TextExtractor
from core.extractor_ocr import OCRExtractor


class HybridExtractor:
    """
    Intelligent extractor that automatically detects PDF type
    and applies the appropriate extraction method.
    """
    
    def __init__(self,
                 cnpj_mapper: CNPJMapper,
                 min_text_length: int = 50,
                 tesseract_cmd: str = None,
                 ocr_language: str = "por",
                 ocr_dpi: int = 300,
                 pdf_page_limit: int = 0,
                 llm_enabled: bool = False,
                 llm_model: str = "llama3:8b",
                 llm_url: str = "http://localhost:11434"):
        """
        Initialize hybrid extractor.
        
        Args:
            cnpj_mapper: CNPJ to Coligada/Filial mapper
            min_text_length: Minimum text length to consider PDF as text-based
            tesseract_cmd: Path to Tesseract executable
            ocr_language: OCR language
            ocr_dpi: DPI for OCR rasterization
            pdf_page_limit: Maximum pages to process per PDF
            llm_enabled: Whether to enable LLM extraction
            llm_model: Ollama model name
            llm_url: Ollama API URL
        """
        self.cnpj_mapper = cnpj_mapper
        self.pdf_page_limit = pdf_page_limit
        self.llm_enabled = llm_enabled
        
        self.text_extractor = TextExtractor(min_text_length=min_text_length)
        self.ocr_extractor = OCRExtractor(
            tesseract_cmd=tesseract_cmd,
            language=ocr_language,
            dpi=ocr_dpi
        )
        
        if llm_enabled:
            # Determine if we should use Vision or Text LLM based on model name
            is_vision_model = any(vm in llm_model for vm in ['llava', 'moondream', 'bakllava'])
            
            if is_vision_model:
                from core.extractor_vision import VisionExtractor
                logger.info(f"Initializing Vision Extractor with model: {llm_model}")
                self.vision_extractor = VisionExtractor(model_name=llm_model, base_url=llm_url)
                self.llm_extractor = None
                self._vision_lock = threading.Lock() # Serialize Vision access
            else:
                from core.extractor_llm import LLMExtractor
                logger.info(f"Initializing Text LLM Extractor with model: {llm_model}")
                self.llm_extractor = LLMExtractor(model_name=llm_model, base_url=llm_url)
                self.vision_extractor = None
                self._vision_lock = None
        else:
            self.llm_extractor = None
            self.vision_extractor = None
    
    def extract(self, pdf_bytes: bytes, filename: str, check_cancel: Optional[Callable[[], bool]] = None) -> Tuple[FiscalDocument, float]:
        """
        Extract fiscal document data using the appropriate method.
        
        Returns:
            Tuple of (FiscalDocument, processing_time_seconds)
        """
        start_time = datetime.now()
        
        logger.info(f"Starting extraction: {filename}")
        
        # Detect PDF type
        is_text_based = self.text_extractor.is_text_based(pdf_bytes)
        full_text_content = "" # Store text for LLM if needed
        
        try:
            if is_text_based:
                logger.info(f"{filename} is text-based, using direct extraction")
                doc = self.text_extractor.extract(pdf_bytes, filename, check_cancel=check_cancel)
                # Capture text for potential LLM fallback
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                     full_text_content = "\n".join([p.extract_text() or "" for p in pdf.pages])
            else:
                logger.info(f"{filename} is scanned, using OCR extraction")
                # OCR Extractor modified to return text ideally, or we capture it from doc metadata if we stored it
                # For now let's rely on OCR Extractor's result.
                doc = self.ocr_extractor.extract(pdf_bytes, filename, self.pdf_page_limit)
                
                # We need the raw text for LLM. Since OCRExtractor doesn't expose it easily in previous interface,
                # we might need to re-run OCR or refactor OCRExtractor. 
                # Strategy: We will refactor OCRExtractor later to be more efficient, 
                # but for now let's prioritize the "Need LLM?" check.
                # If LLM is needed, we might re-OCR inside LLM step or accept overhead.
                # Actually, let's just make OCRExtractor return text or store it in doc.
                # BETTER: Just check if doc is poor quality.

            # Check data quality
            is_poor_quality = self._is_extraction_poor(doc)
            
            if self.llm_enabled and is_poor_quality:
                logger.warning(f"Extraction quality poor for {filename}. Attempting AI enhancement...")
                
                if self.vision_extractor:
                    # Vision Fallback (Preferred for LLaVA/Moondream)
                    # Use lock to prevent concurrent Ollama calls (Timeout prevention)
                    # Acquire lock but check for cancellation inside waiting if possible? 
                    # Simpler: Acquire lock, THEN check cancel immediately.
                    with self._vision_lock:
                        if check_cancel and check_cancel():
                            logger.info(f"Cancellation detected before Vision execution for {filename}")
                            return doc, (datetime.now() - start_time).total_seconds()
                            
                        logger.info(f"Using Vision Extractor ({self.vision_extractor.model_name})...")
                        vision_doc = self.vision_extractor.extract(pdf_bytes, filename, check_cancel)
                        self._merge_docs(doc, vision_doc)
                    
                elif self.llm_extractor:
                    # Text LLM Fallback (Legacy/Text-only models)
                    if full_text_content or is_text_based:
                         llm_doc = self.llm_extractor.extract(full_text_content, filename)
                         self._merge_docs(doc, llm_doc)
                    else:
                        logger.warning("Text LLM enabled but no text content available for scanned document.")
            
            # Apply CNPJ mapping
            self._apply_mapping(doc)
            
            # Mark as completed
            if not doc.error_message:
                doc.processing_status = ProcessingStatus.COMPLETED
            else:
                doc.processing_status = ProcessingStatus.ERROR
            
        except Exception as e:
            logger.error(f"Extraction failed for {filename}: {e}")
            doc = FiscalDocument(
                filename=filename,
                processing_status=ProcessingStatus.ERROR,
                error_message=str(e)
            )
        
        # Calculate processing time
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        doc.processing_time_seconds = processing_time
        doc.processed_at = end_time
        
        logger.info(f"Completed {filename} in {processing_time:.2f}s (status: {doc.processing_status.value})")
        
        return doc, processing_time
    
    def _is_extraction_poor(self, doc: FiscalDocument) -> bool:
        """Check if regex extraction missed critical fields"""
        # Critical fields missing
        missing_critical = (
            not doc.valores or 
            not doc.valores.valor_total or 
            (not doc.emitente and not doc.destinatario)
        )
        return missing_critical

    def _merge_docs(self, target: FiscalDocument, source: FiscalDocument):
        """Merge source (LLM) into target (Regex) preserving existing data"""
        if not target.numero: target.numero = source.numero
        if not target.emitente: target.emitente = source.emitente
        if not target.destinatario: target.destinatario = source.destinatario
        
        # Merge values carefully
        if source.valores:
            if not target.valores:
                target.valores = source.valores
            else:
                if not target.valores.valor_total: target.valores.valor_total = source.valores.valor_total
                if not target.valores.iss: target.valores.iss = source.valores.iss
                # Prefer LLM for sub-values usually missed by regex
                target.valores.pis = source.valores.pis
                target.valores.cofins = source.valores.cofins
                target.valores.inss = source.valores.inss
                target.valores.ir = source.valores.ir
                target.valores.csll = source.valores.csll
                target.valores.valor_liquido = source.valores.valor_liquido

        if not target.itens and source.itens:
            target.itens = source.itens
    
    def _apply_mapping(self, doc: FiscalDocument):
        """Apply CNPJ to Coligada/Filial mapping and set Destinatário Name from filiais.json"""
        cnpj = doc.get_identifier_cnpj()
        
        if cnpj:
            mapping = self.cnpj_mapper.lookup(cnpj)
            if mapping:
                doc.coligada = mapping.coligada
                doc.filial = mapping.filial
                
                # Set Destinatário razão_social from mapping.nome (user requested)
                if mapping.nome:
                    if doc.destinatario:
                        doc.destinatario.razao_social = mapping.nome
                    else:
                        # Create destinatario entity with mapped name
                        doc.destinatario = Entity(cnpj=cnpj, razao_social=mapping.nome)
                
                logger.debug(f"Mapped CNPJ {cnpj} to Coligada {mapping.coligada}, Filial {mapping.filial}, Nome: {mapping.nome}")
            else:
                logger.warning(f"No mapping found for CNPJ: {cnpj}")
                doc.coligada = "N/A"
                doc.filial = "N/A"
        else:
            logger.warning(f"No CNPJ found in document {doc.filename}")
