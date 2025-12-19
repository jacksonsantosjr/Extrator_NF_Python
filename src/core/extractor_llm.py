"""
LLM-based extraction using local Ollama instance.
"""
import json
import requests
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger

from models import FiscalDocument, ProcessingStatus, DocumentType, Entity, Address, TaxValues, ServiceItem

class LLMExtractor:
    """Extracts fiscal data using a local LLM via Ollama"""
    
    def __init__(self, model_name: str = "llama3:8b", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
        self.api_url = f"{base_url}/api/generate"
        
    def is_available(self) -> bool:
        """Check if Ollama is running and model is available"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                models = [m['name'] for m in response.json().get('models', [])]
                # Check for partial match (e.g. "llama3:8b" in "llama3:8b-instruct")
                return any(self.model_name in m for m in models)
        except Exception:
            return False
        return False

    def extract(self, text_content: str, filename: str) -> FiscalDocument:
        """
        Extract data from text using LLM.
        """
        doc = FiscalDocument(filename=filename)
        
        try:
            logger.info(f"Sending {filename} content to LLM ({self.model_name})...")
            
            prompt = self._build_prompt(text_content)
            
            response = requests.post(self.api_url, json={
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json" # Force JSON mode
            })
            
            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.text}")
                
            result = response.json()
            extracted_json = json.loads(result['response'])
            
            # Map JSON to FiscalDocument
            self._map_json_to_doc(extracted_json, doc)
            
            doc.processing_status = ProcessingStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            doc.processing_status = ProcessingStatus.ERROR
            doc.error_message = f"LLM Error: {str(e)}"
            
        return doc
    
    def _build_prompt(self, text: str) -> str:
        """Construct the extraction prompt"""
        return f"""
        Você é um assistente especializado em extração de dados de Notas Fiscais brasileiras (NF-e, NFS-e).
        Analise o texto abaixo extraído de um documento fiscal e retorne APENAS um JSON estritamente válido preenchendo os campos encontrados.
        Se um campo não for encontrado, use null.
        
        TEXTO DO DOCUMENTO:
        \"\"\"
        {text[:12000]} 
        \"\"\"
        (Texto truncado se muito longo)

        FORMATO JSON DESEJADO:
        {{
            "tipo_documento": "NFS-e" ou "NF-e",
            "numero": "string (ex: 123)",
            "serie": "string",
            "chave_acesso": "string (44 digitos)",
            "data_emissao": "YYYY-MM-DD",
            "data_competencia": "YYYY-MM-DD",
            "emitente": {{
                "cnpj": "string",
                "razao_social": "string",
                "endereco_completo": "string"
            }},
            "destinatario": {{
                "cnpj": "string",
                "razao_social": "string",
                "endereco_completo": "string"
            }},
            "valores": {{
                "valor_total": float,
                "valor_servicos": float,
                "base_calculo": float,
                "iss": float,
                "pis": float,
                "cofins": float,
                "inss": float,
                "ir": float,
                "csll": float,
                "valor_liquido": float
            }},
            "itens": [
                {{
                    "descricao": "string",
                    "quantidade": float,
                    "valor_unitario": float,
                    "valor_total": float
                }}
            ]
        }}
        """

    def _map_json_to_doc(self, data: Dict[str, Any], doc: FiscalDocument):
        """Map the LLM JSON response to the FiscalDocument model"""
        
        # Tipo
        if data.get("tipo_documento") == "NFS-e":
            doc.document_type = DocumentType.NFSE
        elif data.get("tipo_documento") == "NF-e":
            doc.document_type = DocumentType.NFE
            
        doc.numero = str(data.get("numero") or "")
        doc.serie = data.get("serie")
        doc.chave_acesso = data.get("chave_acesso")
        
        # Datas
        if data.get("data_emissao"):
            try:
                doc.data_emissao = datetime.strptime(data["data_emissao"], "%Y-%m-%d").date()
            except: pass
            
        if data.get("data_competencia"):
            try:
                doc.data_competencia = datetime.strptime(data["data_competencia"], "%Y-%m-%d").date()
            except: pass
            
        # Emitente
        emit = data.get("emitente", {})
        if emit:
            doc.emitente = Entity(
                cnpj=emit.get("cnpj"), 
                razao_social=emit.get("razao_social"),
                endereco=Address(logradouro=emit.get("endereco_completo")) # Simplificado
            )

        # Destinatario
        dest = data.get("destinatario", {})
        if dest:
            doc.destinatario = Entity(
                cnpj=dest.get("cnpj"), 
                razao_social=dest.get("razao_social"),
                endereco=Address(logradouro=dest.get("endereco_completo")) 
            )

        # Valores
        vals = data.get("valores", {})
        if vals:
            doc.valores = TaxValues(
                valor_total=vals.get("valor_total"),
                valor_servicos=vals.get("valor_servicos"),
                base_calculo=vals.get("base_calculo"),
                iss=vals.get("iss"),
                pis=vals.get("pis"),
                cofins=vals.get("cofins"),
                inss=vals.get("inss"),
                ir=vals.get("ir"),
                csll=vals.get("csll"),
                valor_liquido=vals.get("valor_liquido")
            )

        # Itens
        items = data.get("itens", [])
        for item in items:
            doc.itens.append(ServiceItem(
                descricao=str(item.get("descricao", "")),
                quantidade=item.get("quantidade"),
                valor_unitario=item.get("valor_unitario"),
                valor_total=item.get("valor_total")
            ))
