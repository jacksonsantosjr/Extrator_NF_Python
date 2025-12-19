"""
Data models for fiscal documents and their components.
"""
from datetime import date, datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import re


class DocumentType(str, Enum):
    """Type of fiscal document"""
    NFE = "NF-e"  # Nota Fiscal Eletrônica
    NFSE = "NFS-e"  # Nota Fiscal de Serviços Eletrônica
    UNKNOWN = "Desconhecido"


class ProcessingStatus(str, Enum):
    """Status of document processing"""
    PENDING = "Pendente"
    PROCESSING = "Processando"
    COMPLETED = "Concluído"
    ERROR = "Erro"
    CANCELLED = "Cancelado"


class Address(BaseModel):
    """Address information"""
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    cep: Optional[str] = None

    def to_string(self) -> str:
        """Convert address to formatted string"""
        parts = []
        if self.logradouro:
            parts.append(self.logradouro)
        if self.numero:
            parts.append(f"nº {self.numero}")
        if self.complemento:
            parts.append(self.complemento)
        if self.bairro:
            parts.append(self.bairro)
        if self.municipio and self.uf:
            parts.append(f"{self.municipio}/{self.uf}")
        if self.cep:
            parts.append(f"CEP: {self.cep}")
        return ", ".join(parts) if parts else ""


class Entity(BaseModel):
    """Represents an entity (Emitente or Destinatário)"""
    cnpj: Optional[str] = None
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    inscricao_estadual: Optional[str] = None
    inscricao_municipal: Optional[str] = None
    inscricao_municipal: Optional[str] = None
    endereco: Optional[Address] = None
    
    model_config = {"validate_assignment": True} 

    @field_validator('cnpj')
    @classmethod
    def validate_cnpj(cls, v: Optional[str]) -> Optional[str]:
        """Validate and format CNPJ"""
        if v is None:
            return v
        # Remove non-numeric characters
        cnpj_clean = re.sub(r'\D', '', v)
        if len(cnpj_clean) == 14:
            # User request: "Emitente/Destinatário CNPJ/CPF não devem ter ., /, -. E devem considerar o 0"
            # Return clean digits only. Excel will treat as string if we want leading zero, or we ensure reporter handles it.
            # Storing clean string "0123..." is safest.
            return cnpj_clean
        return cnpj_clean # Return clean even if length mismatch, or original? Let's return clean to be safe.


class TaxValues(BaseModel):
    """Tax and financial values"""
    valor_total: Optional[float] = Field(None, description="Total value")
    valor_servicos: Optional[float] = Field(None, description="Services value")
    base_calculo: Optional[float] = Field(None, description="Tax base")
    iss: Optional[float] = Field(None, description="ISS value")
    pis: Optional[float] = Field(None, description="PIS value")
    cofins: Optional[float] = Field(None, description="COFINS value")
    inss: Optional[float] = Field(None, description="INSS value")
    ir: Optional[float] = Field(None, description="IR value")
    csll: Optional[float] = Field(None, description="CSLL value")
    icms: Optional[float] = Field(None, description="ICMS value")
    ipi: Optional[float] = Field(None, description="IPI value")
    outras_retencoes: Optional[float] = Field(None, description="Other retentions")
    desconto: Optional[float] = Field(None, description="Discount")
    valor_liquido: Optional[float] = Field(None, description="Net value")


class ServiceItem(BaseModel):
    """Individual service or product item"""
    item_numero: Optional[int] = None
    codigo: Optional[str] = None
    descricao: Optional[str] = None
    quantidade: Optional[float] = None
    unidade: Optional[str] = None
    valor_unitario: Optional[float] = None
    valor_total: Optional[float] = None
    aliquota_iss: Optional[float] = None
    valor_iss: Optional[float] = None


class FiscalDocument(BaseModel):
    """Complete fiscal document data"""
    # File information
    filename: str
    file_path: Optional[str] = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    error_message: Optional[str] = None
    
    # Document identification
    document_type: DocumentType = DocumentType.UNKNOWN
    numero: Optional[str] = None
    serie: Optional[str] = None
    chave_acesso: Optional[str] = None
    data_emissao: Optional[date] = None
    data_emissao: Optional[date] = None
    data_saida_entrada: Optional[date] = None
    data_competencia: Optional[date] = None
    
    # Entities
    emitente: Optional[Entity] = None
    destinatario: Optional[Entity] = None
    
    # Financial data
    valores: Optional[TaxValues] = None
    
    # Items/Services
    itens: List[ServiceItem] = Field(default_factory=list)
    
    # Mapping (from CNPJ lookup)
    coligada: Optional[str] = None
    filial: Optional[str] = None
    
    # Processing metadata
    is_scanned: bool = False
    processing_time_seconds: Optional[float] = None
    processed_at: Optional[datetime] = None

    model_config = {"validate_assignment": True}

    @field_validator('chave_acesso')
    @classmethod
    def validate_chave_acesso(cls, v: Optional[str]) -> Optional[str]:
        """Validate access key format"""
        if v is None:
            return v
        # Remove non-numeric characters
        chave_clean = re.sub(r'\D', '', v)
        # NFe access key should have 44 digits
        if len(chave_clean) == 44:
            return chave_clean
        return v

    def get_identifier_cnpj(self) -> Optional[str]:
        """
        Get the CNPJ to use for mapping lookup.
        Priority: destinatario > emitente
        """
        if self.destinatario and self.destinatario.cnpj:
            return self.destinatario.cnpj
        if self.emitente and self.emitente.cnpj:
            return self.emitente.cnpj
        return None
