"""
Models for processing results and errors.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from .document import FiscalDocument, ProcessingStatus


class ProcessingError(BaseModel):
    """Error information for a failed processing"""
    filename: str
    error_type: str
    error_message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    traceback: Optional[str] = None


class ProcessingResult(BaseModel):
    """Result of processing a single file"""
    filename: str
    status: ProcessingStatus
    document: Optional[FiscalDocument] = None
    error: Optional[ProcessingError] = None
    processing_time_seconds: float = 0.0


class BatchProcessingResult(BaseModel):
    """Result of processing a batch of files"""
    total_files: int
    successful: int = 0
    failed: int = 0
    cancelled: int = 0
    
    results: List[ProcessingResult] = Field(default_factory=list)
    errors: List[ProcessingError] = Field(default_factory=list)
    
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    @property
    def total_time_seconds(self) -> float:
        """Calculate total processing time"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_files == 0:
            return 0.0
        return (self.successful / self.total_files) * 100
    
    def add_result(self, result: ProcessingResult):
        """Add a processing result and update counters"""
        self.results.append(result)
        
        if result.status == ProcessingStatus.COMPLETED:
            self.successful += 1
        elif result.status == ProcessingStatus.ERROR:
            self.failed += 1
            if result.error:
                self.errors.append(result.error)
        elif result.status == ProcessingStatus.CANCELLED:
            self.cancelled += 1
    
    def finalize(self):
        """Mark batch processing as complete"""
        self.end_time = datetime.now()


class ProgressUpdate(BaseModel):
    """Progress update for UI"""
    current_file: str
    current_index: int
    total_files: int
    status: ProcessingStatus
    message: str
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress as percentage"""
        if self.total_files == 0:
            return 0.0
        return (self.current_index / self.total_files) * 100
