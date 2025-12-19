"""
Processing orchestrator - manages concurrent file processing.
"""
from typing import List, Tuple, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from pathlib import Path
import threading
from loguru import logger

from models import (
    FiscalDocument,
    BatchProcessingResult,
    ProcessingResult,
    ProcessingStatus,
    ProcessingError,
    ProgressUpdate
)
from utils import FileHandler
from core.extractor import HybridExtractor


class ProcessingOrchestrator:
    """
    Orchestrates concurrent processing of fiscal documents.
    Manages thread pool, progress tracking, and cancellation.
    """
    
    def __init__(self,
                 extractor: HybridExtractor,
                 max_workers: int = 3,
                 progress_callback: Optional[Callable[[ProgressUpdate], None]] = None):
        """
        Initialize orchestrator.
        
        Args:
            extractor: Hybrid extractor instance
            max_workers: Maximum concurrent processing tasks
            progress_callback: Optional callback for progress updates
        """
        self.extractor = extractor
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        
        # Cancellation flag
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
    
    def process_files(self, file_paths: List[Path]) -> BatchProcessingResult:
        """
        Process multiple files concurrently.
        
        Args:
            file_paths: List of file paths (PDFs or ZIPs)
        
        Returns:
            BatchProcessingResult with all processing results
        """
        # Reset cancellation flag
        self._cancel_flag.clear()
        
        # Prepare files (extract PDFs from ZIPs)
        logger.info(f"Preparing {len(file_paths)} files for processing")
        pdf_files = FileHandler.prepare_files_for_processing(file_paths)
        
        if not pdf_files:
            logger.warning("No valid PDF files to process")
            return BatchProcessingResult(total_files=0)
        
        # Initialize batch result
        batch_result = BatchProcessingResult(total_files=len(pdf_files))
        
        logger.info(f"Starting concurrent processing of {len(pdf_files)} PDFs (max workers: {self.max_workers})")
        
        # Process files concurrently
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_file = {}
            for idx, (filename, pdf_bytes) in enumerate(pdf_files):
                if self._cancel_flag.is_set():
                    logger.info("Processing cancelled before submission")
                    break
                
                future = executor.submit(self._process_single_file, filename, pdf_bytes, idx, len(pdf_files))
                future_to_file[future] = filename
            
            # Collect results as they complete
            for future in as_completed(future_to_file):
                if self._cancel_flag.is_set():
                    logger.info("Processing cancelled, skipping remaining results")
                    # Cancel pending futures
                    for f in future_to_file:
                        f.cancel()
                    break
                
                filename = future_to_file[future]
                
                try:
                    result = future.result()
                    batch_result.add_result(result)
                    
                except Exception as e:
                    logger.error(f"Unexpected error processing {filename}: {e}")
                    error_result = ProcessingResult(
                        filename=filename,
                        status=ProcessingStatus.ERROR,
                        error=ProcessingError(
                            filename=filename,
                            error_type=type(e).__name__,
                            error_message=str(e)
                        )
                    )
                    batch_result.add_result(error_result)
        
        # Finalize batch
        batch_result.finalize()
        
        logger.info(f"Batch processing complete: {batch_result.successful} successful, "
                   f"{batch_result.failed} failed, {batch_result.cancelled} cancelled "
                   f"(total time: {batch_result.total_time_seconds:.2f}s)")
        
        return batch_result
    
    def _process_single_file(self, 
                            filename: str, 
                            pdf_bytes: bytes,
                            index: int,
                            total: int) -> ProcessingResult:
        """
        Process a single PDF file.
        
        Args:
            filename: File name
            pdf_bytes: PDF content bytes
            index: Current file index
            total: Total number of files
        
        Returns:
            ProcessingResult
        """
        # Check cancellation before starting
        if self._cancel_flag.is_set():
            logger.info(f"Skipping {filename} due to cancellation")
            return ProcessingResult(
                filename=filename,
                status=ProcessingStatus.CANCELLED
            )
        
        # Send progress update
        self._send_progress(
            filename=filename,
            index=index,
            total=total,
            status=ProcessingStatus.PROCESSING,
            message=f"Processando {filename}..."
        )
        
        try:
            # Extract document
            document, processing_time = self.extractor.extract(pdf_bytes, filename, check_cancel=self.is_cancelled)
            
            # Check cancellation after processing
            if self._cancel_flag.is_set():
                logger.info(f"Cancelling {filename} after processing")
                return ProcessingResult(
                    filename=filename,
                    status=ProcessingStatus.CANCELLED
                )
            
            # Create result
            result = ProcessingResult(
                filename=filename,
                status=document.processing_status,
                document=document,
                processing_time_seconds=processing_time
            )
            
            if document.error_message:
                result.error = ProcessingError(
                    filename=filename,
                    error_type="ExtractionError",
                    error_message=document.error_message
                )
            
            # Send completion update
            self._send_progress(
                filename=filename,
                index=index + 1,
                total=total,
                status=document.processing_status,
                message=f"Concluído: {filename}"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"Error processing {filename}: {e}", exc_info=True)
            
            return ProcessingResult(
                filename=filename,
                status=ProcessingStatus.ERROR,
                error=ProcessingError(
                    filename=filename,
                    error_type=type(e).__name__,
                    error_message=str(e)
                )
            )
    
    def cancel(self):
        """Cancel ongoing processing"""
        logger.warning("Cancellation requested")
        self._cancel_flag.set()
    
    def is_cancelled(self) -> bool:
        """Check if processing is cancelled"""
        return self._cancel_flag.is_set()
    
    def _send_progress(self, 
                      filename: str,
                      index: int,
                      total: int,
                      status: ProcessingStatus,
                      message: str):
        """Send progress update via callback"""
        if self.progress_callback:
            update = ProgressUpdate(
                current_file=filename,
                current_index=index,
                total_files=total,
                status=status,
                message=message
            )
            
            try:
                self.progress_callback(update)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
