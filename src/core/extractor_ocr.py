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
            
            # Use text extractor to parse the OCR'd text
            # (reusing all the regex patterns and logic)
            temp_doc = self.text_extractor.extract(
                self._create_text_pdf(ocr_text),
                filename
            )
            
            # Copy extracted data
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
            
        except Exception as e:
            logger.error(f"Error in OCR extraction for {filename}: {e}")
            doc.error_message = str(e)
        
        return doc
    
    def _pdf_to_text_ocr(self, pdf_bytes: bytes, page_limit: int = 0) -> str:
        """
        Convert PDF to text using OCR.
        
        Args:
            pdf_bytes: PDF file bytes
            page_limit: Maximum pages to process
        
        Returns:
            Extracted text from all pages
        """
        full_text = ""
        
        try:
            # Open PDF with PyMuPDF
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            total_pages = len(pdf_document)
            pages_to_process = total_pages if page_limit == 0 else min(page_limit, total_pages)
            
            logger.info(f"Processing {pages_to_process} pages with OCR (DPI: {self.dpi})")
            
            for page_num in range(pages_to_process):
                page = pdf_document[page_num]
                
                # Render page to image
                pix = page.get_pixmap(dpi=self.dpi)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_data))
                
                # Preprocess if enabled
                if self.enable_preprocessing:
                    image = self._preprocess_image(image)
                
                # Perform OCR with optimized config for fiscal documents
                # PSM 4 = Assume a single column of text of variable sizes
                # This works better for NFS-e layouts than PSM 6
                page_text = pytesseract.image_to_string(
                    image,
                    lang=self.language,
                    config='--psm 4 --oem 3'  # PSM 4 + LSTM engine
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
        Applies grayscale, auto-contrast, and light sharpening.
        """
        try:
            # Convert to grayscale
            image = image.convert('L')
            
            # Apply auto-contrast to improve readability
            from PIL import ImageOps
            image = ImageOps.autocontrast(image, cutoff=1)
            
            # Light sharpening to improve text edges
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.5)  # Slight sharpening
            
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
