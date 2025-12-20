"""
OCR-based PDF extraction using Tesseract.
"""
from typing import Optional
import io
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import fitz  # PyMuPDF
from loguru import logger

from models import FiscalDocument
from core.extractor_text import TextExtractor


class OCRExtractor:
    """Extracts data from scanned/image-based PDFs using OCR"""
    
    def __init__(self, 
                 tesseract_cmd: Optional[str] = None,
                 language: str = "por",
                 dpi: int = 300,
                 enable_preprocessing: bool = True):
        """
        Initialize OCR extractor.
        
        Args:
            tesseract_cmd: Path to tesseract executable (if not in PATH)
            language: Tesseract language code (por = Portuguese)
            dpi: DPI for PDF rasterization
            enable_preprocessing: Apply image preprocessing for better OCR
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        self.language = language
        self.dpi = dpi
        self.enable_preprocessing = enable_preprocessing
        
        # Reuse text extractor for parsing OCR'd text
        self.text_extractor = TextExtractor()
    
    def extract(self, pdf_bytes: bytes, filename: str, page_limit: int = 0) -> FiscalDocument:
        """
        Extract fiscal document data from scanned PDF using OCR.
        
        Args:
            pdf_bytes: PDF file bytes
            filename: Original filename
            page_limit: Maximum pages to process (0 = unlimited)
        """
        doc = FiscalDocument(filename=filename, is_scanned=True)
        
        try:
            # Convert PDF pages to images and OCR
            ocr_text = self._pdf_to_text_ocr(pdf_bytes, page_limit)
            
            if not ocr_text.strip():
                raise ValueError("No text extracted from OCR")
            
            # Use text extractor to parse the OCR'd text (first pass with default DPI)
            temp_doc = self.text_extractor.extract(
                self._create_text_pdf(ocr_text),
                filename
            )
            
            # Copy extracted data from first pass
            doc.document_type = temp_doc.document_type
            doc.numero = temp_doc.numero
            doc.serie = temp_doc.serie
            doc.chave_acesso = temp_doc.chave_acesso
            doc.data_emissao = temp_doc.data_emissao
            doc.data_competencia = temp_doc.data_competencia
            doc.emitente = temp_doc.emitente
            doc.destinatario = temp_doc.destinatario
            doc.valores = temp_doc.valores
            doc.itens = temp_doc.itens
            
            # [FIX] Hybrid DPI: If destinatário CNPJ is missing, try second pass with different DPI
            # This happens when table data is not captured at DPI 400 but is at DPI 200
            needs_second_pass = (
                doc.destinatario is None or 
                (doc.destinatario and not doc.destinatario.cnpj)
            )
            
            # Log extraction results for debugging
            logger.debug(f"First pass results - destinatario: {doc.destinatario}, has_cnpj: {doc.destinatario.cnpj if doc.destinatario else 'N/A'}")
            
            if needs_second_pass:
                logger.debug(f"needs_second_pass=True, calling _detect_layout_for_dpi")
                recommended_dpi = self._detect_layout_for_dpi(ocr_text)
                logger.debug(f"recommended_dpi={recommended_dpi}, current_dpi={self.dpi}")
                if recommended_dpi > 0 and recommended_dpi != self.dpi:
                    logger.info(f"Second pass with DPI {recommended_dpi} to get missing destinatário")
                    # [FIX] Use dpi_override parameter instead of modifying self.dpi (thread-safety)
                    ocr_text_2 = self._pdf_to_text_ocr(pdf_bytes, page_limit, dpi_override=recommended_dpi)
                    
                    # Extract from second pass
                    temp_doc_2 = self.text_extractor.extract(
                        self._create_text_pdf(ocr_text_2),
                        filename
                    )
                    
                    logger.debug(f"Second pass results - destinatario: {temp_doc_2.destinatario}, has_cnpj: {temp_doc_2.destinatario.cnpj if temp_doc_2.destinatario else 'N/A'}")
                    
                    # Only fill in MISSING fields from second pass
                    if temp_doc_2.destinatario and temp_doc_2.destinatario.cnpj:
                        logger.info(f"Merging destinatario CNPJ from second pass: {temp_doc_2.destinatario.cnpj}")
                        if doc.destinatario is None:
                            doc.destinatario = temp_doc_2.destinatario
                        elif not doc.destinatario.cnpj:
                            doc.destinatario.cnpj = temp_doc_2.destinatario.cnpj
                            if not doc.destinatario.razao_social and temp_doc_2.destinatario.razao_social:
                                doc.destinatario.razao_social = temp_doc_2.destinatario.razao_social
                    else:
                        logger.warning(f"Second pass did not capture destinatario CNPJ")
            
        except Exception as e:
            logger.error(f"Error in OCR extraction for {filename}: {e}")
            doc.error_message = str(e)
        
        return doc
    
    def _detect_layout_for_dpi(self, text: str) -> int:
        """
        Detect layout from OCR text and return optimal DPI.
        Some layouts require higher DPI for accurate extraction.
        
        Returns:
            Recommended DPI for this layout (0 = use current)
        """
        text_upper = text.upper()
        
        # Recife layout: requires 600 DPI for proper number extraction
        if 'PREFEITURA' in text_upper and 'RECIFE' in text_upper:
            logger.debug("Detected Recife layout - recommending DPI 600")
            return 600
        
        # São Paulo layout: if number appears corrupted, try different DPI
        # Check if "SÃO PAULO" present but no 8-digit number starting with 00
        if 'PREFEITURA' in text_upper and 'SÃO PAULO' in text_upper:
            import re
            # Check if 8-digit number with leading zeros exists (00XXXXXX)
            has_sp_number = re.search(r'00\d{6}', text)
            if not has_sp_number:
                logger.debug("Detected São Paulo layout with missing number - recommending DPI 200")
                return 200  # Lower DPI works better for some scanned documents
        
        # NFS-e layouts with table data missing (ADL, etc.): 
        # If TOMADOR label present but no CNPJ data captured, retry with lower DPI
        if 'TOMADOR' in text_upper and 'NFS-E' in text_upper:
            import re
            # Check if there's actual CNPJ data after TOMADOR section
            tomador_pos = text_upper.find('TOMADOR')
            text_after_tomador = text[tomador_pos:tomador_pos + 500] if tomador_pos > 0 else ''
            has_tomador_cnpj = re.search(r'\d{2}[.,]\d{3}[.,]\d{3}[/\\]\d{4}[-]?\d{2}', text_after_tomador)
            if not has_tomador_cnpj:
                logger.debug("Detected NFS-e with missing TOMADOR data - recommending DPI 200")
                return 200
        
        return 0  # Use current DPI
    
    def _pdf_to_text_ocr(self, pdf_bytes: bytes, page_limit: int = 0, dpi_override: int = None) -> str:
        """
        Convert PDF to text using OCR.
        
        Args:
            pdf_bytes: PDF file bytes
            page_limit: Maximum pages to process
            dpi_override: Optional DPI to use instead of self.dpi (for thread-safety)
        
        Returns:
            Extracted text from all pages
        """
        full_text = ""
        
        # Use override DPI if provided (thread-safe), otherwise use instance DPI
        effective_dpi = dpi_override if dpi_override is not None else self.dpi
        
        try:
            # Open PDF with PyMuPDF
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            total_pages = len(pdf_document)
            pages_to_process = total_pages if page_limit == 0 else min(page_limit, total_pages)
            
            logger.info(f"Processing {pages_to_process} pages with OCR (DPI: {effective_dpi})")
            
            for page_num in range(pages_to_process):
                page = pdf_document[page_num]
                
                # Render page to image
                pix = page.get_pixmap(dpi=effective_dpi)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_data))
                
                # Preprocess if enabled
                if self.enable_preprocessing:
                    image = self._preprocess_image(image)
                
                # Perform OCR with optimized config for fiscal documents
                # PSM 4 = Assume a single column of text of variable sizes
                # OEM 3 = Default, based on what is available (LSTM preferred)
                page_text = pytesseract.image_to_string(
                    image,
                    lang=self.language,
                    config='--psm 4 --oem 3'
                )
                
                full_text += page_text + "\n"
                logger.debug(f"OCR page {page_num + 1}/{pages_to_process}: {len(page_text)} chars")
            
            pdf_document.close()
            
        except Exception as e:
            logger.error(f"Error in PDF to OCR conversion: {e}")
            raise
        
        return full_text
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR results.
        Conservative: grayscale, auto-contrast, moderate sharpening.
        """
        try:
            # Convert to grayscale
            image = image.convert('L')
            
            # Apply auto-contrast to improve readability
            from PIL import ImageOps
            image = ImageOps.autocontrast(image, cutoff=1)
            
            # Moderate sharpening to improve text edges
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.5)
            
        except Exception as e:
            logger.warning(f"Error in image preprocessing: {e}")
        
        return image
    
    @staticmethod
    def _create_text_pdf(text: str) -> bytes:
        """
        Create a minimal text-based PDF from string.
        This is a workaround to reuse TextExtractor's parsing logic.
        """
        # For simplicity, we'll just pass the text directly
        # The TextExtractor will work with it via a mock PDF
        # In practice, we could refactor TextExtractor to accept plain text
        
        # Create a simple PDF with the text
        pdf_document = fitz.open()
        page = pdf_document.new_page()
        page.insert_text((50, 50), text, fontsize=10)
        
        pdf_bytes = pdf_document.write()
        pdf_document.close()
        
        return pdf_bytes
