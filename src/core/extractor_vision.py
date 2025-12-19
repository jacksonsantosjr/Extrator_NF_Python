"""
Vision-based extraction using local Ollama instance with LLaVA model.
"""
import base64
import json
import requests
import fitz  # PyMuPDF
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from loguru import logger

from models import FiscalDocument, Entity, Address, TaxValues, ServiceItem, DocumentType

class VisionExtractor:
    """Extracts fiscal data using multimodal LLM (LLaVA) via Ollama"""
    
    def __init__(self, model_name: str = "llava:7b", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
        self.api_url = f"{base_url}/api/generate"
        self.timeout = 120  # 120s timeout for GPU vision processing
        
    def is_available(self) -> bool:
        """Check if Ollama is running and vision model is available"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = [m['name'] for m in response.json().get('models', [])]
                # Check for llava, bakllava, moondream
                vision_models = ['llava', 'bakllava', 'moondream']
                available = any(any(vm in m for vm in vision_models) for m in models)
                if available:
                    # Update model name if exact match not found but variant exists
                    if self.model_name not in models:
                        for m in models:
                            if 'llava' in m:
                                self.model_name = m
                                logger.info(f"Using available vision model: {self.model_name}")
                                break
                return available
        except Exception as e:
            logger.warning(f"Ollama availability check failed: {e}")
            return False
        return False

    def extract(self, pdf_bytes: bytes, filename: str, check_cancel: Optional[Callable[[], bool]] = None) -> FiscalDocument:
        """
        Extract data from PDF using Vision LLM.
        """
        doc = FiscalDocument(filename=filename, is_scanned=True)
        
        try:
            # 1. Convert PDF pages to base64 images
            images_b64 = self._pdf_to_base64_images(pdf_bytes)
            
            if not images_b64:
                raise ValueError("Could not convert PDF to images")
                
            logger.info(f"Sending {len(images_b64)} page images to {self.model_name}...")
            
            if check_cancel and check_cancel():
                logger.info(f"Vision processing cancelled for {filename}")
                return doc

            # 2. Build prompt
            prompt = self._build_prompt()
            
            if check_cancel and check_cancel():
                return doc

            # 3. Call Ollama API
            response_json = self._call_ollama(images_b64, prompt)
            
            # 4. Parse response
            try:
                # Sanitize JSON if needed (remove markdown)
                clean_json = response_json.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean_json)
                
                # 5. Map to FiscalDocument
                self._map_json_to_doc(data, doc)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM JSON: {e}. Response: {response_json[:200]}...")
                doc.error_message = "Falha ao processar resposta da IA"
            
        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            doc.error_message = f"Erro Vision: {str(e)}"
            
        return doc
    
    def _pdf_to_base64_images(self, pdf_bytes: bytes, max_pages: int = 2) -> List[str]:
        """Convert PDF pages to base64 encoded images"""
        images = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            # Limit pages to avoid context window issues
            pages_to_process = min(max_pages, len(doc))
            
            for page_num in range(pages_to_process):
                page = doc[page_num]
                
                # DPI 200 is a good balance for LLaVA (readable but not huge)
                pix = page.get_pixmap(dpi=200) 
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode('utf-8')
                images.append(b64)
            
            doc.close()
        except Exception as e:
            logger.error(f"PDF to Image conversion error: {e}")
            
        return images

    def _call_ollama(self, images: List[str], prompt: str) -> str:
        """Call Ollama generate endpoint"""
        # For LLaVA, we typically send images with the user message
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "images": images,  # Ollama accepts list of base64 images
            "stream": False,
            "format": "json",  # Enforce JSON mode
            "options": {
                "temperature": 0.1,  # Low temperature for factual extraction
                "num_ctx": 4096      # Larger context for images
            }
        }
        
        response = requests.post(self.api_url, json=payload, timeout=self.timeout)
        
        if response.status_code != 200:
            raise Exception(f"Ollama API Error ({response.status_code}): {response.text}")
            
        return response.json().get('response', '')

    def _build_prompt(self) -> str:
        """Construct the extraction prompt"""
        return """
        Você é um especialista em extração de dados de documentos fiscais brasileiros (NF-e, NFS-e).
        Analise a imagem deste documento e extraia os dados abaixo em formato JSON.
        
        REGRAS:
        1. Responda APENAS com o JSON válido.
        2. Se um campo não existir ou estiver ilegível, use null.
        3. Valores monetários devem ser números (ex: 100.50).
        4. Datas devem ser YYYY-MM-DD.
        
        ESTRUTURA JSON DESEJADA:
        {
            "tipo_documento": "NFS-e" | "NF-e",
            "numero": "string (apenas dígitos)",
            "serie": "string",
            "chave_acesso": "string (44 dígitos)",
            "data_emissao": "YYYY-MM-DD",
            "emitente": {
                "cnpj": "string (apenas dígitos)",
                "razao_social": "string",
                "endereco": "string"
            },
            "destinatario": {
                "cnpj": "string (apenas dígitos)",
                "razao_social": "string"
            },
            "valores": {
                "valor_total": number,
                "valor_servicos": number,
                "iss": number,
                "pis": number,
                "cofins": number,
                "ir": number,
                "inss": number,
                "csll": number,
                "valor_liquido": number
            }
        }
        """

    def _map_json_to_doc(self, data: Dict[str, Any], doc: FiscalDocument):
        """Map JSON response to FiscalDocument"""
        
        # Type
        tipo = str(data.get("tipo_documento", "")).upper()
        if "NFS" in tipo:
            doc.document_type = DocumentType.NFSE
        elif "NF-E" in tipo or "DANFE" in tipo:
            doc.document_type = DocumentType.NFE
            
        doc.numero = str(data.get("numero") or "")
        doc.serie = str(data.get("serie") or "")
        doc.chave_acesso = data.get("chave_acesso")
        
        # Dates
        if data.get("data_emissao"):
            try:
                doc.data_emissao = datetime.strptime(data["data_emissao"], "%Y-%m-%d").date()
            except: pass
            
        # Emitente
        emit = data.get("emitente", {})
        if emit:
            doc.emitente = Entity(
                cnpj=str(emit.get("cnpj") or "").replace('.', '').replace('/', '').replace('-', ''),
                razao_social=emit.get("razao_social"),
                endereco=Address(logradouro=emit.get("endereco"))
            )
            
        # Destinatario
        dest = data.get("destinatario", {})
        if dest:
            doc.destinatario = Entity(
                cnpj=str(dest.get("cnpj") or "").replace('.', '').replace('/', '').replace('-', ''),
                razao_social=dest.get("razao_social")
            )
            
        # Values
        vals = data.get("valores", {})
        if vals:
            doc.valores = TaxValues(
                valor_total=vals.get("valor_total"),
                valor_servicos=vals.get("valor_servicos"),
                iss=vals.get("iss"),
                pis=vals.get("pis"),
                cofins=vals.get("cofins"),
                inss=vals.get("inss"),
                ir=vals.get("ir"),
                csll=vals.get("csll"),
                valor_liquido=vals.get("valor_liquido")
            )
