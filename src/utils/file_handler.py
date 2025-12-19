"""
File handling utilities for PDF and ZIP files.
"""
from pathlib import Path
from typing import List, BinaryIO, Tuple
import zipfile
import io
from loguru import logger


class FileValidator:
    """Validates file types and formats"""
    
    # Magic bytes for file type detection
    PDF_MAGIC = b'%PDF'
    ZIP_MAGIC = b'PK\x03\x04'
    
    @staticmethod
    def is_pdf(file_path: Path) -> bool:
        """Check if file is a valid PDF"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4)
                return header == FileValidator.PDF_MAGIC
        except Exception as e:
            logger.error(f"Error checking PDF: {file_path} - {e}")
            return False
    
    @staticmethod
    def is_pdf_from_bytes(data: bytes) -> bool:
        """Check if byte data is a valid PDF"""
        return data[:4] == FileValidator.PDF_MAGIC
    
    @staticmethod
    def is_zip(file_path: Path) -> bool:
        """Check if file is a valid ZIP"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4)
                return header == FileValidator.ZIP_MAGIC
        except Exception as e:
            logger.error(f"Error checking ZIP: {file_path} - {e}")
            return False
    
    @staticmethod
    def validate_file(file_path: Path) -> Tuple[bool, str]:
        """
        Validate if file is supported (PDF or ZIP).
        Returns (is_valid, file_type)
        """
        if not file_path.exists():
            return False, "File does not exist"
        
        if not file_path.is_file():
            return False, "Not a file"
        
        if FileValidator.is_pdf(file_path):
            return True, "PDF"
        
        if FileValidator.is_zip(file_path):
            return True, "ZIP"
        
        return False, "Unsupported file type"


class ZIPExtractor:
    """Extracts PDF files from ZIP archives in-memory"""
    
    @staticmethod
    def extract_pdfs(zip_path: Path) -> List[Tuple[str, bytes]]:
        """
        Extract all PDF files from a ZIP archive.
        Returns list of (filename, pdf_bytes) tuples.
        """
        pdfs = []
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.filelist:
                    # Skip directories
                    if file_info.is_dir():
                        continue
                    
                    filename = file_info.filename
                    
                    # Check if it's a PDF by extension or magic bytes
                    if filename.lower().endswith('.pdf'):
                        try:
                            pdf_bytes = zip_ref.read(filename)
                            
                            # Verify it's actually a PDF
                            if FileValidator.is_pdf_from_bytes(pdf_bytes):
                                # Get just the filename without path
                                clean_filename = Path(filename).name
                                pdfs.append((clean_filename, pdf_bytes))
                                logger.debug(f"Extracted PDF from ZIP: {clean_filename}")
                            else:
                                logger.warning(f"File has .pdf extension but invalid format: {filename}")
                        except Exception as e:
                            logger.error(f"Error extracting {filename} from ZIP: {e}")
            
            logger.info(f"Extracted {len(pdfs)} PDFs from {zip_path.name}")
            
        except zipfile.BadZipFile:
            logger.error(f"Invalid ZIP file: {zip_path}")
        except Exception as e:
            logger.error(f"Error processing ZIP {zip_path}: {e}")
        
        return pdfs
    
    @staticmethod
    def extract_pdfs_from_bytes(zip_bytes: bytes, source_name: str = "archive") -> List[Tuple[str, bytes]]:
        """
        Extract PDFs from ZIP bytes (in-memory).
        Useful for processing uploaded files without disk I/O.
        """
        pdfs = []
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
                for file_info in zip_ref.filelist:
                    if file_info.is_dir():
                        continue
                    
                    filename = file_info.filename
                    
                    if filename.lower().endswith('.pdf'):
                        try:
                            pdf_bytes = zip_ref.read(filename)
                            
                            if FileValidator.is_pdf_from_bytes(pdf_bytes):
                                clean_filename = Path(filename).name
                                pdfs.append((clean_filename, pdf_bytes))
                        except Exception as e:
                            logger.error(f"Error extracting {filename}: {e}")
            
            logger.info(f"Extracted {len(pdfs)} PDFs from {source_name}")
            
        except Exception as e:
            logger.error(f"Error processing ZIP bytes from {source_name}: {e}")
        
        return pdfs


class FileHandler:
    """High-level file handling operations"""
    
    @staticmethod
    def prepare_files_for_processing(file_paths: List[Path]) -> List[Tuple[str, bytes]]:
        """
        Prepare files for processing.
        Handles both direct PDFs and ZIPs containing PDFs.
        Returns list of (filename, pdf_bytes) tuples.
        """
        files_to_process = []
        
        for file_path in file_paths:
            is_valid, file_type = FileValidator.validate_file(file_path)
            
            if not is_valid:
                logger.warning(f"Skipping invalid file: {file_path} - {file_type}")
                continue
            
            if file_type == "PDF":
                try:
                    with open(file_path, 'rb') as f:
                        pdf_bytes = f.read()
                    files_to_process.append((file_path.name, pdf_bytes))
                    logger.debug(f"Added PDF: {file_path.name}")
                except Exception as e:
                    logger.error(f"Error reading PDF {file_path}: {e}")
            
            elif file_type == "ZIP":
                pdfs = ZIPExtractor.extract_pdfs(file_path)
                files_to_process.extend(pdfs)
        
        logger.info(f"Prepared {len(files_to_process)} files for processing")
        return files_to_process
    
    @staticmethod
    def get_bytes_io(pdf_bytes: bytes) -> BinaryIO:
        """Convert PDF bytes to BytesIO object for processing"""
        return io.BytesIO(pdf_bytes)
