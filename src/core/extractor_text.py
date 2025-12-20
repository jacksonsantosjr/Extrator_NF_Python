import io
from typing import Optional, Dict, Any, List, Tuple
import re
from datetime import datetime
import pdfplumber
from loguru import logger
from models import FiscalDocument, Entity, Address, TaxValues, ServiceItem, DocumentType
from core.ollama_service import extract_with_ollama, is_ollama_available
class TextExtractor:
    """Extracts data from text-based PDFs with robust fallbacks"""
    
    # Brazilian state codes for validation
    BRAZILIAN_STATES = {'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 
                        'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 
                        'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'}
    
    def __init__(self, min_text_length: int = 50):
        self.min_text_length = min_text_length
    
    def is_text_based(self, pdf_bytes: bytes) -> bool:
        """Determine if PDF is text-based or scanned image."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if len(pdf.pages) > 0:
                    text = pdf.pages[0].extract_text() or ""
                    return len(text.strip()) >= self.min_text_length
        except Exception as e:
            logger.error(f"Error checking PDF type: {e}")
        return False
    
    def extract(self, pdf_bytes: bytes, filename: str, check_cancel: callable = None) -> FiscalDocument:
        """Extract fiscal document data from text-based PDF."""
        doc = FiscalDocument(filename=filename)
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                # Extract text from all pages
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    full_text += page_text + "\n"
                
                if not full_text.strip():
                    raise ValueError("No text content found in PDF")
                
                # Verificar cancelamento
                if check_cancel and check_cancel():
                    logger.info(f"Extração cancelada para {filename}")
                    doc.error_message = "Cancelado pelo usuário"
                    return doc
                
                # EXTRAÇÃO RÁPIDA POR REGEX (sem IA - Ollama não está funcionando)
                doc.document_type = self._detect_document_type(full_text)
                
                # PRIORIDADE 1: Extrair número do nome do arquivo (mais confiável)
                doc.numero = self._extract_numero_from_filename(filename)
                if doc.numero:
                    logger.info(f"Número '{doc.numero}' extraído do nome do arquivo")
                
                # PRIORIDADE 2: Se não encontrou no filename, tentar no texto
                if not doc.numero:
                    doc.numero = self._extract_numero(full_text, pdf)
                
                doc.serie = self._extract_serie(full_text)
                doc.chave_acesso = self._extract_chave_acesso(full_text)
                doc.data_emissao = self._extract_data_emissao(full_text)
                doc.data_saida_entrada = self._extract_data_saida_entrada(full_text)
                doc.data_competencia = self._extract_data_competencia(full_text)
                doc.emitente = self._extract_emitente(full_text, pdf=pdf)
                doc.destinatario = self._extract_destinatario(full_text, pdf=pdf)
                doc.valores = self._extract_valores(full_text, pdf)
                doc.itens = self._extract_items(pdf)
                
                doc.is_scanned = False
                
        except Exception as e:
            logger.error(f"Error extracting from {filename}: {e}")
            doc.error_message = str(e)
        
        return doc
    
    def _fill_missing_from_ai(self, doc: FiscalDocument, ai_result: dict):
        """Preenche apenas campos faltantes com resultado da IA."""
        # Número
        if not doc.numero:
            num = ai_result.get("numeroDocumento")
            if num:
                num_clean = str(num).replace(" ", "").replace("-", "").replace(".", "")
                # Validar: não aceitar chave de acesso ou CNPJ
                if len(num_clean) <= 10 and len(num_clean) != 14:
                    doc.numero = num
                    logger.info(f"Número '{num}' preenchido via IA")
        
        # Emitente
        if not doc.emitente or not doc.emitente.razao_social:
            emitente_data = ai_result.get("emitente", {})
            if emitente_data and emitente_data.get("nomeRazaoSocial"):
                if not doc.emitente:
                    doc.emitente = Entity()
                doc.emitente.razao_social = emitente_data.get("nomeRazaoSocial")
                if not doc.emitente.cnpj and emitente_data.get("cnpjCpf"):
                    doc.emitente.cnpj = emitente_data.get("cnpjCpf")
                logger.info(f"Emitente preenchido via IA: {doc.emitente.razao_social}")
        
        # Destinatário
        if not doc.destinatario or not doc.destinatario.razao_social:
            dest_data = ai_result.get("destinatarioTomador", {})
            if dest_data and dest_data.get("nomeRazaoSocial"):
                if not doc.destinatario:
                    doc.destinatario = Entity()
                doc.destinatario.razao_social = dest_data.get("nomeRazaoSocial")
                if not doc.destinatario.cnpj and dest_data.get("cnpjCpf"):
                    doc.destinatario.cnpj = dest_data.get("cnpjCpf")
                logger.info(f"Destinatário preenchido via IA: {doc.destinatario.razao_social}")
    
    def _map_ai_result_to_document(self, ai_result: dict, filename: str) -> FiscalDocument:
        """Mapeia resultado da IA para FiscalDocument."""
        doc = FiscalDocument(filename=filename)
        
        # Tipo de documento
        tipo = ai_result.get("tipoDocumento", "")
        if "NFS" in str(tipo).upper():
            doc.document_type = DocumentType.NFSE
        elif "NF-E" in str(tipo).upper() or "NFE" in str(tipo).upper():
            doc.document_type = DocumentType.NFE
        else:
            doc.document_type = DocumentType.UNKNOWN
        
        # Número e chave
        doc.numero = ai_result.get("numeroDocumento")
        doc.chave_acesso = ai_result.get("chaveAcessoNFe")
        
        # VALIDAÇÃO: Rejeitar números que parecem ser chave de acesso ou CNPJ
        if doc.numero:
            num_clean = str(doc.numero).replace(" ", "").replace("-", "").replace(".", "")
            if len(num_clean) == 44:
                logger.warning(f"Número '{doc.numero}' parece ser chave de acesso (44 dígitos). Ignorando.")
                doc.numero = None
            elif len(num_clean) == 14:
                logger.warning(f"Número '{doc.numero}' parece ser CNPJ (14 dígitos). Ignorando.")
                doc.numero = None
            elif len(num_clean) > 10:
                logger.warning(f"Número '{doc.numero}' é muito longo ({len(num_clean)} dígitos). Ignorando.")
                doc.numero = None
        
        # Datas
        data_emissao = ai_result.get("dataEmissao")
        if data_emissao:
            try:
                doc.data_emissao = datetime.strptime(data_emissao, "%Y-%m-%d").date()
            except: pass
        
        data_saida = ai_result.get("dataSaidaEntrada")
        if data_saida:
            try:
                doc.data_saida_entrada = datetime.strptime(data_saida, "%Y-%m-%d").date()
            except: pass
        
        # Emitente
        emitente_data = ai_result.get("emitente", {})
        if emitente_data:
            doc.emitente = Entity(
                cnpj=emitente_data.get("cnpjCpf"),
                razao_social=emitente_data.get("nomeRazaoSocial")
            )
            if emitente_data.get("enderecoCompleto"):
                doc.emitente.endereco = Address()
                doc.emitente.endereco.logradouro = emitente_data.get("enderecoCompleto")
        
        # Destinatário
        dest_data = ai_result.get("destinatarioTomador", {})
        if dest_data:
            doc.destinatario = Entity(
                cnpj=dest_data.get("cnpjCpf"),
                razao_social=dest_data.get("nomeRazaoSocial")
            )
            if dest_data.get("enderecoCompleto"):
                doc.destinatario.endereco = Address()
                doc.destinatario.endereco.logradouro = dest_data.get("enderecoCompleto")
        
        # Valores
        valores_data = ai_result.get("valores", {})
        if valores_data:
            doc.valores = TaxValues(
                valor_total=valores_data.get("totalDocumento"),
                valor_liquido=valores_data.get("valorLiquidoDocumento")
            )
        
        return doc
    
    def _detect_document_type(self, text: str) -> DocumentType:
        """Detect if document is NF-e or NFS-e"""
        text_upper = text.upper()
        
        # NFS-e patterns
        nfse_patterns = ['NFS-E', 'NOTA FISCAL DE SERVIÇO', 'NOTA FISCAL DE SERVIÇOS', 
                         'NOTA DE SERVIÇO', 'NFSE', 'PRESTADOR DE SERVIÇO']
        if any(p in text_upper for p in nfse_patterns):
            return DocumentType.NFSE
        
        # NF-e patterns
        nfe_patterns = ['NF-E', 'NOTA FISCAL ELETRÔNICA', 'NOTA FISCAL ELETRONICA',
                        'DANFE', 'NFE']
        if any(p in text_upper for p in nfe_patterns):
            return DocumentType.NFE
        
        return DocumentType.UNKNOWN
    
    # ==================== NUMBER EXTRACTION ====================
    def _is_potential_date(self, val: str) -> bool:
        """Semantic check: Does this string look like a date?"""
        val = val.strip()
        clean_val = val.replace('/', '').replace('.', '').replace('-', '')
        
        if not clean_val.isdigit():
            return False
            
        # 8 digits: DDMMYYYY
        if len(clean_val) == 8:
            try:
                d = int(clean_val[:2])
                m = int(clean_val[2:4])
                y = int(clean_val[4:])
                if 1 <= d <= 31 and 1 <= m <= 12 and 2000 <= y <= 2030:
                    return True
            except: pass
            
        # 7 digits: DMMYYYY
        if len(clean_val) == 7:
            try:
                d = int(clean_val[:1])
                m = int(clean_val[1:3])
                y = int(clean_val[3:])
                if 1 <= d <= 9 and 1 <= m <= 12 and 2000 <= y <= 2030:
                    return True
            except: pass
            
        return False
    def _extract_numero(self, text: str, pdf: Optional[pdfplumber.PDF] = None) -> Optional[str]:
        """Extract document number with multiple patterns"""
        
        # 1. Try SPATIAL Extraction first
        if pdf:
            val = self._extract_text_spatial(pdf, [
                'Número da NFS-e', 'Número da Nota', 'Nº da Nota', 
                'Número do Documento', 'Nº do Documento', 'DANFE N',
                'NFS-e N', 'Nota Fiscal N'
            ], r'(\d{3,})')
            
            if val:
                match = re.search(r'(\d{3,})', val)
                if match:
                    candidate_num = match.group(1)
                    if not self._is_potential_date(candidate_num):
                        logger.debug(f"Spatial extraction found number: {candidate_num}")
                        return candidate_num
                    else:
                        logger.warning(f"Spatial extraction rejected candidate '{candidate_num}' because it looks like a Date.")
        patterns = [
            # [FIX] NFS-e São Paulo: número de 8 dígitos com zeros à esquerda SOZINHO em uma linha
            # Texto OCR: linha 5 "00000833" ou "00026358" - número isolado na própria linha
            r'(?:\n|^)\s*(00\d{6})\s*(?:\n|$)',
            
            # [FIX] NFS-e Guarulhos RENOSUL: "NFS-e 96148" ou "NFS-e\n96148" (número direto após label)
            # Texto OCR: linha 6 "NFS-e 96148" - formato mais simples sem "nº" ou ":"
            r'NFS-e\s+(\d{5,6})',
            
            # [FIX] NFS-e Barueri FORPONTO: "Número da Nota" seguido de número 6 dígitos em linha separada
            # Texto OCR: linha 10 "Número da Nota Série da Nota" ... linha 14 "002544"
            # O número aparece SOZINHO em uma linha, começando com 00
            r'N[úu]mero\s+da\s+Nota[^\n]*\n(?:[^\n]*\n){0,5}\s*(00\d{4,6})\s*$',
            
            # [FIX] NFS-e Barueri: Número vem DEPOIS do código de autenticidade na mesma linha
            # Texto: "493Q.0820.8311.1890799-S 000016" - captura os 6 dígitos após o código
            r'[A-Z0-9]{3,4}[A-Z]?\.\d{4}\.\d{4}\.\d+-[A-Z]\s+(\d{5,8})',
            
            # [FIX] NFS-e Barueri alternativo: "Série da Nota" seguido de número em próxima linha
            r'S[ée]rie\s+da\s+Nota\s*\n[^\n]*?(\d{6})',
            
            # [FIX] NFS-e Itapevi (DURACAP): "Número Nota Fiscal:" seguido de número
            # PRIORIDADE ALTA: Preferir "Número Nota Fiscal" sobre "Número RPS"
            r'N[úu]mero\s+Nota\s+Fiscal[:\s]+(\d{5,8})',
            
            # [FIX] NFS-e Itapevi (DURACAP) OCR: "Fatura Nro 128137" na linha de resumo
            # Texto OCR: "Nota Fiscal Fatura Fatura Nro 128137 | Valor R$"
            r'Fatura\s+Nro\s+(\d{5,8})',
            
            # [FIX] NFS-e Itapevi (DURACAP) OCR alternativo: RPS seguido de Nota Fiscal na mesma linha
            # Texto OCR: "128417 128148] 04/12/2025" - captura o segundo número (Nota Fiscal)
            r'\d{5,6}\s+(\d{5,6})\]',
            
            # [FIX] NFS-e São Paulo OTUS: "Número da Nota\n00002219" (número em linha separada)
            # PRIORIDADE ALTA para evitar capturar RPS
            r'N[úu]mero\s+da\s+Nota\s*\n\s*(\d{5,})',
            
            # [FIX] OCR NFS-e SP: número após "SÃO PAULO" com possíveis artefatos OCR antes dos dígitos
            # Texto OCR: 'SÃO PAULO """"no02227' - captura dígitos após quaisquer caracteres
            r'SÃO\s+PAULO[^\d\n]*(\d{5,8})',
            
            # [FIX] NFS-e Recife DPI 600: número completo de 8 dígitos após "Número da Nota"
            # Texto OCR: "Múumero da Mota\nAt ] 00016668" - número na linha seguinte
            r'[MN][úu][úu]?mero\s+d[ae]\s+[MN]ota[^\d]*(\d{8})',
            
            # [FIX] NFS-e Recife DPI 400: número fragmentado com espaço "0001 668" após PREFEITURA
            # Texto OCR: "PREFEITURA DO 0001 668 —" - captura os dígitos e concatena
            r'PREFEITURA.*?(\d{3,4})\s+(\d{3,5})',
            
            r'[\[\(](\d{6,8})\s*\n.*(?:Data|Emissão)',
            
            # NFS-e Caieiras: "Número da Nota/Série 2.757/NFE" (número com separador de milhar + série)
            r'N[úu]mero\s+da\s+Nota/?S[ée]rie\s*[:\s]*(\d{1,3}(?:\.\d{3})*)/\w+',
            
            # [FIX] NFS-e Itatiba: Labels colados sem espaços "NúmerodaNFS-e" seguido de número
            # O texto aparece como: "NúmerodaNFS-e CompetênciadaNFS-e...\n183 01/12/2025"
            r'N[úu]merodaNFS-?e[^\d]*(\d{3,})',
            
            # [FIX] NFS-e São Paulo POWER TEC: "NúmerodaNota" (label colado) seguido de número
            # Texto OCR: linha 3 "|NúmerodaNota |" e linha 4 "PREFEITURA...SÃO PAULO 00000835"
            r'N[úu]merodaNota[^\d]*(\d{5,8})',
            # Aceita "Nota 144", "NF 144", "Documento 144" - MAS NÃO "RPS"
            r'(?:N[úu]mero|N[º°]|Doc|N\.|NF|Nota|Documento)\s*[:\.]\s*(\d{3,10})',
            
            r'NFS-e\s*n[º°o]\s*[:\s]*(\d{3,})',
            r'DANFE\s*N[º°o]\s*[:\s]*(\d{3,})',
            r'N[º°o]\s*do\s*documento\s*[:\s]*(\d{3,})',
            r'N[úu]mero\s*do\s*Documento\s*[:\s]*(\d{3,})',
            r'N[úu]mero\s*Nota\s*Fiscal\s*[:\s]*(\d{3,})',
            
            r'N[úu]mero\s+da\s+Nota[^\d]*(\d{3,})',
            r'N[úu]mero da Nota\s*(\d{3,})',
            r'Numero da Nota\s*(\d{3,})',
            r'N[úu]mero\s+(?:da\s+)?Nota\s+Fiscal[:\s]*(\d{3,})',
            r'N[úu]mero\s+(?:da\s+)?NFS-?e[:\s]*(\d{3,})',
            r'N[úu]mero\s+Nota[:\s]*(\d{3,})',
            
            # GENERIC PATTERNS (require 5+ digits normally, but prioritized explicit ones above)
            r'N[úuÚU]MERO[^\d]*(\d{5,})', 
            r'N[úu]mero[:\s]*(\d{5,})',
            r'N[º°5oO0][:\s]*(\d{5,})',
            r'N\.?[\sº°5oO0][:\s]*(\d{5,})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # [FIX] Suporte a múltiplos grupos de captura (ex: número fragmentado "0001 668")
                if len(match.groups()) > 1:
                    # Concatenar todos os grupos (para padrões como Recife)
                    num = ''.join(g for g in match.groups() if g)
                    # [FIX] Recife: Se o resultado tem 7 dígitos, pad para 8 (padrão NFS-e Recife)
                    if len(num) == 7 and num.startswith('000'):
                        num = num.zfill(8)  # 0001668 -> 00001668
                else:
                    num = match.group(1).strip()
                
                # Remover separador de milhar (ex: 2.757 -> 2757)
                num = num.replace('.', '')
                

                
                # [FIX] Validações de tamanho
                if len(num) == 44: continue  # Chave de Acesso
                if len(num) == 14: continue  # CNPJ
                if len(num) > 10: continue   # Muito longo para ser número de nota
                if len(num) == 4 and num.startswith('20'): continue # Ano
                if len(num) < 3: continue # Muito curto
                
                if self._is_potential_date(num):
                    logger.debug(f"Regex matched '{num}' but it looks like a Date. Skipping.")
                    continue
                
                logger.debug(f"Matched numero '{num}' with pattern: {pattern[:50]}...")
                return num
        
        # [FIX] Fallback OCR Salvador: número após "SALVADOR" com letras OCR corrompidas
        # Texto OCR: 'SALVADOR  [ooo0s74o ?' onde 'ooo0s74o' = '00008740'
        # Texto OCR: 'SALVADOR  [mo00s7ss ?' onde 'mo00s7ss' = '00008739'
        # IMPORTANTE: Número da nota aparece em colchetes na primeira linha
        # Incluir: m (parece 00), o (parece 0), s (parece 8/3/9), n (parece 0)
        salvador_match = re.search(r'SALVADOR[^\n]*?[\[\(]([moOnOs0-9]{6,10})[\s\?\]]', text, re.IGNORECASE)
        if salvador_match:
            ocr_num = salvador_match.group(1)
            # Converter letras confundidas com dígitos
            # Primeira passagem: substituições diretas
            ocr_num = ocr_num.replace('o', '0').replace('O', '0')
            ocr_num = ocr_num.replace('n', '0').replace('N', '0')
            ocr_num = ocr_num.replace('m', '0').replace('M', '0')  # m parece 00 mas conta como 1 char
            ocr_num = ocr_num.replace('s', '8').replace('S', '8')  # s geralmente é 8
            # Se ainda não é só dígitos, tentar s→3 ou s→9
            if not ocr_num.isdigit():
                ocr_num = ocr_num.replace('s', '3').replace('S', '3')
            if ocr_num.isdigit() and len(ocr_num) >= 6:
                logger.debug(f"Matched numero '{ocr_num}' with Salvador OCR fallback")
                return ocr_num
        
        # [FIX] Fallback: Se nenhum padrão encontrou o número, usar RPS como guia
        # Retorna "RPS-XXXX" para ajudar na identificação manual
        rps_match = re.search(r'RPS\s*N[º°]?\s*(\d{1,6})', text, re.IGNORECASE)
        if rps_match:
            rps_num = rps_match.group(1)
            logger.debug(f"Using RPS fallback: RPS-{rps_num}")
            return f"RPS-{rps_num}"
        
        return None
    
    def _extract_numero_from_filename(self, filename: str) -> Optional[str]:
        """Try to extract document number from filename as a fallback"""
        # Remover extensão e caminho
        import os
        base_name = os.path.splitext(os.path.basename(filename))[0]
        
        patterns = [
            # Padrão específico: número_data (ex: 144_09122025)
            r'[\s\-_](\d{3,6})_\d{6,8}(?:$|\s)',  # "...144_09122025"
            
            # Padrão: número seguido de underscore ou hífen e data
            r'(\d{3,6})_\d{6,8}',  # "144_09122025"
            
            # Padrão com prefixo NF/Nota
            r'(?:NF|Nota|NFS-?e)[_\-\s]*(\d{3,})',
            
            # Número no FINAL do nome antes de underscore+data
            r'-\s*(\d{3,6})_',  # "- 144_"
            
            # Número de 3+ dígitos seguido de underscore
            r'(\d{3,6})_',  # "144_"
            
            # Número no início
            r'^(\d{3,6})[\s_\-]',  # "144 " ou "144_" ou "144-"
        ]
        
        current_year = datetime.now().year
        years = [str(y) for y in range(2020, current_year + 2)]
        
        for pattern in patterns:
            matches = re.findall(pattern, base_name, re.IGNORECASE)
            for match in matches:
                num = match.strip()
                
                # Validações de tamanho
                if len(num) == 44: continue  # Chave de Acesso
                if len(num) == 14: continue  # CNPJ
                if len(num) > 10: continue   # Muito longo
                if len(num) == 8 and num.startswith('0'): continue  # Data DDMMYYYY
                if num in years: continue
                if len(num) < 3: continue
                
                if self._is_potential_date(num):
                    continue
                    
                logger.debug(f"Extracted number '{num}' from filename '{base_name}' using pattern: {pattern}")
                return num
        return None
    
    def _extract_serie(self, text: str) -> Optional[str]:
        patterns = [r'S[ée]rie[:\s]+(\d+)', r'S[ée]rie\s*(\d+)']
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def _extract_chave_acesso(self, text: str) -> Optional[str]:
        label_patterns = [r'(?:Chave\s+(?:de\s+)?Acesso|Chave\s+NFe)[:\s]*([\d\s\.]{44,60})']
        for pattern in label_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                digits = re.sub(r'\D', '', match.group(1))
                if len(digits) == 44: return digits
        
        continuous = re.search(r'\b(\d{44})\b', text)
        if continuous: return continuous.group(1)
        
        blocks = re.search(r'(\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4})', text)
        if blocks:
            digits = re.sub(r'\D', '', blocks.group(1))
            if len(digits) == 44: return digits
        return None
    
    # ==================== DATE EXTRACTION ====================
    def _extract_date_near_label(self, text: str, labels: List[str]) -> Optional[datetime.date]:
        date_pattern = r'(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})'
        for label in labels:
            pattern = rf'{label}[:\s]*{date_pattern}'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100:
                        return datetime(year, month, day).date()
                except ValueError: continue
        return None
    
    def _extract_data_emissao(self, text: str) -> Optional[datetime.date]:
        labels = [
            r'Data\s+e\s+Hora\s+(?:de\s+)?Emiss[ãa]o', r'Data\s+e\s+Hora\s+(?:da\s+)?emiss[ãa]o\s+(?:da\s+)?NFS-?e',
            r'DATA\s+DE\s+EMISS[ÃA]O', r'Emitida\s+em', r'Data\s+do\s+documento', r'Data\s+Emiss[ãa]o',
            r'Emiss[ãa]o', r'Dt\.?\s*Emiss', r'Data\s+da\s+Emiss[ãa]o',
        ]
        lines = text.splitlines()
        header_text = "\n".join(lines[:20])
        date_in_header = self._extract_date_near_label(header_text, labels)
        if date_in_header: return date_in_header
        date_pattern = r'(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})'
        for line in lines[:10]:
             if len(line.strip()) < 100:
                match = re.search(date_pattern, line)
                if match:
                    try:
                        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        if 1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2030:
                            return datetime(year, month, day).date()
                    except: pass
        return self._extract_date_near_label(text, labels)
    
    def _extract_data_saida_entrada(self, text: str) -> Optional[datetime.date]:
        labels = [r'Data\s+(?:de\s+)?Sa[ií]da', r'Sa[ií]da[/\\]?Entrada', r'Data\s+E/S', r'Data\s+Entrada']
        return self._extract_date_near_label(text, labels)
    
    def _extract_data_competencia(self, text: str) -> Optional[datetime.date]:
        labels = [r'(?:Data\s+(?:de\s+)?)?Compet[êe]ncia', r'M[êe]s\s+Refer[êe]ncia']
        return self._extract_date_near_label(text, labels)
    
    # ==================== ENTITY EXTRACTION ====================
    def _find_all_cnpjs(self, text: str) -> List[str]:
        pattern = r'\b\d{2}\.?\d{3}\.?\d{3}/?\.?\d{4}-?\d{2}\b'
        matches = re.findall(pattern, text)
        return [re.sub(r'\D', '', m) for m in matches if len(re.sub(r'\D', '', m)) == 14]
    
    def _check_name_blacklist(self, name: str) -> bool:
        """[FIX] Validação centralizada de nomes"""
        if not name: return True
        name_upper = name.upper()
        if 'E-MAIL' in name_upper: return False
        if 'CNPJ' in name_upper: return False
        if name_upper == 'EMPRESARIAL': return False
        if name_upper == 'NOME': return False
        if len(name) < 4: return False
        if name.isdigit(): return False
        # [FIX] Rejeitar nomes que contêm fragmentos de labels (artefatos OCR)
        if 'RAZÃO SOCIAL' in name_upper or 'RAZAO SOCIAL' in name_upper: return False
        if 'NOME/' in name_upper or '/NOME' in name_upper: return False
        if 'MOMEI' in name_upper: return False  # OCR de "Nome/" corrompido
        return True
    def _extract_emitente(self, text: str, **kwargs) -> Optional[Entity]:
        entity = Entity()
        found_reliable_name = False
        
        # 0. Spatial
        if 'pdf' in kwargs and kwargs['pdf']:
             pdf = kwargs['pdf']
             spatial_name = self._extract_text_spatial(
                 pdf, ['Nome / Nome Empresarial', 'Razão Social'], r'([A-ZÀ-Ú\s\.]+)', force_vertical=True)
             
             if spatial_name and self._check_name_blacklist(spatial_name):
                 entity.razao_social = spatial_name
                 found_reliable_name = True
        
        # 1. Section
        section = self._find_section(text, 
            # [FIX] Usar label completo 'PRESTADOR DE SERVIÇOS' com prioridade
            start_labels=['PRESTADOR DE SERVIÇOS', 'EMITENTE', 'PRESTADOR', 'DADOS DO PRESTADOR'],
            # [FIX] Usar 'TOMADOR DE SERVIÇOS' como end_label completo
            end_labels=['TOMADOR DE SERVIÇOS', 'DESTINAT', 'TOMADOR', 'DADOS DO TOMADOR', 'VALORES', 'ITENS', 'DISCRIMINAÇÃO']
        )
        
        # [FIX] NFS-e Guarulhos: Verificar padrão "Prestador do Serviço NOME" ANTES de processar seção
        # Alguns layouts têm nome na mesma linha do label, não na seção
        prestador_inline_match = re.search(r'Prestador\s+do\s+Servi[çc]o\s+([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.&\-]{3,30}?)(?:\n|$)', text, re.IGNORECASE)
        prestador_inline_name = prestador_inline_match.group(1).strip() if prestador_inline_match else None
        
        if section:
            section_entity = self._parse_entity_from_section(section)
            if section_entity.cnpj:
                # [FIX] Se razao_social é inválida (muito curta ou logo), buscar alternativa
                if section_entity.razao_social and len(section_entity.razao_social) < 12:
                    # Buscar linha com sufixo empresarial na seção
                    # Padrão: linha que começa com letra e termina com LTDA/ME/etc
                    for line in section.split('\n'):
                        line = line.strip()
                        # Ignorar linhas de label (começam com Nome, Razão, CPF, etc)
                        if re.match(r'^(?:Nome|Razão|Raz[ãa]o|CPF|CNPJ|Inscrição|Endereço)', line, re.IGNORECASE):
                            continue
                        if len(line) >= 15 and re.search(r'(?:LTDA|S\.?A\.?|ME|EPP|EIRELI|S/A)\b', line, re.IGNORECASE):
                            # Limpar caracteres extras no final (logos, pipes)
                            better_name = re.sub(r'\s*[|]\s*.*$', '', line).strip()
                            # Verificar se começa com letra e é razoável
                            if re.match(r'^[A-ZÀ-Ú]', better_name) and len(better_name) >= 15:
                                section_entity.razao_social = better_name[:100]
                                logger.info(f"Salvador fallback razao_social: {section_entity.razao_social}")
                                break
                    # [FIX] Guarulhos: Se ainda não achou nome bom, usar prestador inline
                    if len(section_entity.razao_social or '') < 12 and prestador_inline_name:
                        section_entity.razao_social = prestador_inline_name
                        logger.info(f"Guarulhos inline razao_social: {section_entity.razao_social}")
                        
                # [FIX] Guarulhos: Verificar se razao_social parece um bairro/localidade
                # Nomes como "CIDADE INDL SA" são provavelmente locais, não empresas
                if section_entity.razao_social and prestador_inline_name:
                    bad_keywords = ['CIDADE', 'BAIRRO', 'CENTRO', 'VILA', 'JARDIM', 'PARQUE']
                    if any(kw in section_entity.razao_social.upper() for kw in bad_keywords):
                        section_entity.razao_social = prestador_inline_name
                        logger.info(f"Guarulhos location-name fix: {section_entity.razao_social}")
                        
                if found_reliable_name: # Protege nome espacial
                    section_entity.razao_social = entity.razao_social
                return section_entity
            # [FIX] Mesmo sem CNPJ, preservar razão social da seção se encontrada
            if section_entity.razao_social and self._check_name_blacklist(section_entity.razao_social):
                entity.razao_social = section_entity.razao_social
                found_reliable_name = True  # Proteger contra sobrescrita pelo fallback
            if section_entity.endereco:
                entity.endereco = section_entity.endereco
        # 2. Global CNPJ
        cnpj_patterns = [
            r'CPF/CNPJ[:\s]*([\d\.\/-]+)', r'CNPJ/CPF[:\s]*([\d\.\/-]+)', r'CNPJ[:\s]*([\d\.\/-]+)',
            r'(?:CNPJ\s+(?:do\s+)?(?:Emitente|Prestador))[:\s]*([\d\.\/-]+)',
            r'(?:Prestador|Emitente)[:\s]*CNPJ[:\s]*([\d\.\/-]+)',
        ]
        for pattern in cnpj_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                cnpj = re.sub(r'\D', '', match.group(1))
                if len(cnpj) in [11, 14]:
                    entity.cnpj = cnpj
                    break
        
        if not entity.cnpj:
            all_cnpjs = self._find_all_cnpjs(text)
            if all_cnpjs: entity.cnpj = all_cnpjs[0]
        # 3. Regex Fallback (Only if we don't have a reliable name from Spatial)
        if not found_reliable_name and not entity.razao_social:
            name_patterns = [
                # [FIX] NFS-e ADL: nome antes de "Nº:" ou variações OCR (N5:, No:, N0:) na mesma linha
                # Texto OCR DPI 400: "A DE L SIQUEIRA ME Nº: 7354" 
                # Texto OCR DPI 200: "+ 4 DE L SIQUEIRA ME N5: 7354" (começa corrompido)
                r'(?:\n|^).{0,3}([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.&\-]{5,50}?)\s*N[º°5oO0]:\s*\d+',
                
                # [FIX] NFS-e Guarulhos RENOSUL: nome na MESMA LINHA após "Prestador do Serviço"
                # Texto OCR: "Prestador do Serviço RENOSUL\n" - nome direto após label até quebra de linha
                r'Prestador\s+do\s+Servi[çc]o\s+([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.&\-]{3,30}?)(?:\n|$)',
                
                # Padrão NFS-e SP: linha após "Nome/NomeEmpresarial" contém "CNPJ_parcialNOME"
                # Ex: "35.600.304FABIOLUIZSANTOSSILVA"
                r'Nome/?NomeEmpresarial[^\n]*\n[\d\.\-/]+([A-Z][A-Z]+(?:[A-Z]+)*)\s',
                
                # Padrão alternativo: CNPJ.NNN seguido de nome em maiúsculas
                r'\d{2}\.\d{3}\.\d{3}([A-Z][A-Z]+(?:[A-Z]+)*)\s',
                
                # Padrão NFS-e SP: "Nome / Nome Empresarial: CNPJ NOME"
                r'Nome\s*/?\.?\s*Nome\s+Empresarial[:\s]*[\d\.\-/]+\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]+)',
                
                # Padrão: linha seguinte após "EMITENTE DA NFS-e" ou "Prestador do Serviço"
                r'(?:EMITENTE|PRESTADOR)[^\n]*\n[^\n]*\n\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]{5,})',
                
                r'Nome\s*/\s*Nome\s+Empresarial[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\&\-]+)',
                r'(?:Raz[ãa]o\s+Social|Nome\s+(?:do\s+)?(?:Emitente|Prestador))[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\&\-]+)',
                r'(?:Prestador|Emitente)[:\s]*(?:Raz[ãa]o\s+Social)?[:\s]*([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]{5,})',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    # Limpar números iniciais que podem ser CNPJ parcial
                    name = re.sub(r'^[\d\.\-/]+', '', name).strip()
                    # Adicionar espaços antes de maiúsculas (para nomes colados)
                    if name.isupper() and ' ' not in name and len(name) > 10:
                        # Inserir espaços antes de cada maiúscula (exceto a primeira)
                        name = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', name)
                        # Se ainda não tem espaços, é provavelmente tudo maiúsculo colado
                        if ' ' not in name:
                            # Nome pode estar colado, mas manteremos assim
                            pass
                    if self._check_name_blacklist(name):
                        entity.razao_social = name.split('\n')[0].strip()[:100]
                        logger.info(f"Extracted razao_social: {entity.razao_social}")
                        break
        
        if section and not entity.endereco:
            entity.endereco = self._extract_address(section)
        
        return entity if entity.cnpj or entity.razao_social else None
    
    def _extract_destinatario(self, text: str, **kwargs) -> Optional[Entity]:
        entity = Entity()
        found_reliable_name = False
        if 'pdf' in kwargs and kwargs['pdf']:
             pdf = kwargs['pdf']
             spatial_name = self._extract_text_spatial(
                 pdf, ['Nome / Nome Empresarial do Tomador', 'Razão Social do Tomador', 'Tomador de Serviços', 'Destinatário'], 
                 r'([A-ZÀ-Ú\s\.]+)', force_vertical=True)
             if spatial_name and self._check_name_blacklist(spatial_name):
                 entity.razao_social = spatial_name
                 found_reliable_name = True
        section = self._find_section(text,
            # [FIX] Usar label completo 'TOMADOR DE SERVIÇOS' com prioridade para evitar cortar em 'SERVIÇOS'
            start_labels=['TOMADOR DE SERVIÇOS', 'DESTINAT', 'TOMADOR', 'DADOS DO TOMADOR', 'CLIENTE'],
            # [FIX] Remover 'SERVIÇOS' para evitar cortar seção 'TOMADOR DE SERVIÇOS' prematuramente
            end_labels=['INTERMEDIÁRIO', 'VALORES', 'ITENS', 'DISCRIMINAÇÃO', 'PRODUTOS', 'TOTAL']
        )
        if section:
            section_entity = self._parse_entity_from_section(section)
            if section_entity.cnpj: return section_entity
            # [FIX] Mesmo sem CNPJ, preservar razão social da seção se encontrada
            if section_entity.razao_social and self._check_name_blacklist(section_entity.razao_social):
                entity.razao_social = section_entity.razao_social
                found_reliable_name = True  # Proteger contra sobrescrita pelo fallback
        
        cnpj_patterns = [
            r'(?:CNPJ\s+(?:do\s+)?(?:Destinat[áa]rio|Tomador|Cliente))[\s:]*([d\.\/-]+)',
            r'(?:Destinat[áa]rio|Tomador)[:\s]*CNPJ[:\s]*([\d\.\/-]+)',
            r'(?:CPF/CNPJ\s+(?:do\s+)?(?:Tomador|Cliente))[:\s]*([\d\.\/-]+)',
        ]
        for pattern in cnpj_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                cnpj = re.sub(r'\D', '', match.group(1))
                if len(cnpj) in [11, 14]:
                    entity.cnpj = cnpj
                    break
        
        if not entity.cnpj:
            all_cnpjs = self._find_all_cnpjs(text)
            if len(all_cnpjs) >= 2: entity.cnpj = all_cnpjs[1]
        
        if not found_reliable_name and not entity.razao_social:
            name_patterns = [
                r'(?:Raz[ãa]o\s+Social|Nome\s+(?:do\s+)?(?:Destinat[áa]rio|Tomador|Cliente))[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\&\-]+)',
                r'(?:Destinat[áa]rio|Tomador)[:\s]*(?:Raz[ãa]o)?[:\s]*([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]{5,})',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    if self._check_name_blacklist(name):
                        entity.razao_social = name.split('\n')[0].strip()[:100]
                        break
        
        if section: entity.endereco = self._extract_address(section)
        return entity if entity.cnpj or entity.razao_social else None
    def _find_section(self, text: str, start_labels: List[str], end_labels: List[str]) -> Optional[str]:
        text_upper = text.upper()
        start_pos = -1
        found_label_len = 0
        for label in start_labels:
            pos = text_upper.find(label.upper())
            if pos != -1:
                start_pos = pos
                found_label_len = len(label)
                break
        if start_pos == -1: return None
        
        # Avançar para após o label
        start_pos += found_label_len
        
        # [FIX] NFS-e Barueri: NÃO pular para próxima linha se há nome empresarial na mesma linha
        # Verificar se o texto até o próximo newline contém sufixo empresarial (LTDA, S.A., etc.)
        newline_pos = text.find('\n', start_pos)
        if newline_pos != -1:
            same_line_text = text[start_pos:newline_pos]
            # Se a mesma linha contém sufixo empresarial, manter o texto
            has_company_name = bool(re.search(r'(?:LTDA|S\.?A\.?|ME|EPP|EIRELI|S/A)', same_line_text, re.IGNORECASE))
            if not has_company_name and newline_pos < start_pos + 50:
                start_pos = newline_pos + 1
        
        end_pos = len(text)
        for label in end_labels:
            pos = text_upper.find(label.upper(), start_pos)
            if pos != -1 and pos < end_pos: end_pos = pos
        section = text[start_pos:end_pos]
        logger.debug(f"_find_section found section (len={len(section)}): '{section[:100]}...' " if len(section) > 100 else f"_find_section found section (len={len(section)}): '{section}'")
        return section if len(section) > 20 else None
    
    def _parse_entity_from_section(self, section: str) -> Entity:
        entity = Entity()
        
        # Padrões de CNPJ - ordem de prioridade
        # [FIX] OCR às vezes lê ponto como vírgula e omite barra (ex: 15,572.1540001-25)
        cnpj_patterns = [
            # Padrão específico com label "CNPJ" ou "CPF/CNPJ" - muito flexível para OCR
            r'C(?:PF[/\\I])?CN?PJ?[:\s.]+(\d{2}[.,]?\d{3}[.,]?\d{3}[/\\]?\d{4}[-]?\d{2})',
            # Padrão genérico de CNPJ formatado (com separadores)
            r'\b(\d{2}[.,]\d{3}[.,]\d{3}[/\\]\d{4}[-]?\d{2})\b',
            # [FIX] Padrão OCR corrompido: números colados com vírgula/ponto (15,572.1540001-25)
            r'\b(\d{2}[.,]\d{3}[.,]?\d{3,4}\d{4}[-]?\d{2})\b',
        ]
        
        for pattern in cnpj_patterns:
            cnpj_match = re.search(pattern, section, re.IGNORECASE)
            if cnpj_match:
                entity.cnpj = re.sub(r'\D', '', cnpj_match.group(1))
                logger.debug(f"Found CNPJ in section: {entity.cnpj}")
                break
        
        razao_patterns = [
            # [FIX] NFS-e Barueri: Nome empresarial na 1ª linha da seção (sem label)
            # Captura linha iniciando com maiúscula, terminando com sufixo empresarial
            # PRIORIDADE MÁXIMA - padrão mais específico
            r'^\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]+(?:LTDA|S\.?A\.?|ME|EPP|EIRELI|S/A))\s*$',
            
            # [FIX] Alternativo: qualquer linha com sufixo empresarial
            r'([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]{5,}(?:LTDA|S\.?A\.?|ME|EPP|EIRELI|S/A))',
            
            # [FIX] NFS-e Salvador: nome empresa pode estar em linha após "Nome/Razão Social:"
            # Ex: "Nome/Razão Social: polo ir\nPITECNOLOGIA DA INFORMAÇÃO LTDA - ME"
            r'Nome/Raz[ãa]o\s+Social:[^\n]*\n([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]+(?:LTDA|S\.?A\.?|ME|EPP|EIRELI|S/A)[^\n]*)',
            
            # Padrão NFS-e SP: CNPJ.parcial seguido de nome colado (ex: 35.600.304FABIOLUIZSANTOSSILVA)
            r'\d{2}\.\d{3}\.\d{3}([A-Z][A-Z]+(?:[A-Z]+)*)\s',
            
            # [FIX] DANFSe v1.0 (Itatiba/BH): "Nome/NomeEmpresarial E-mail\nTOTVSS.A. email@..."
            # Captura nome colado em maiúsculas após label colado
            r'Nome/NomeEmpresarial\s+E-?mail\n([A-ZÀ-Ú][A-ZÀ-Ú0-9\.\,\-]+?)(?:\s+[A-Za-z0-9@\._-]+@|\n)',
            
            # [FIX] OCR NFS-e SP: caracteres extras antes de "Razão Social" (ex: "HNomesRazão", "MomeiRazão")
            # Ignora caracteres antes e captura nome após ":", "." ou espaços
            r'(?:Nome.?)?Raz[ãa]o\s+Social[:\.\s]+([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\.\&\-]+)',
            
            # Padrões genéricos - EXCLUIR "Nome Tomador" para evitar falsos positivos
            r'Raz[ãa]o\s+Social[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\&\-]+)',
        ]
        for pattern in razao_patterns:
            match = re.search(pattern, section, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Limpar números iniciais
                name = re.sub(r'^[\d\.\-/]+', '', name).strip()
                
                # [FIX] Remover artefatos OCR de labels no início do nome
                # IMPORTANTE: Só aplicar se o resultado for longo o suficiente (10+ chars)
                cleaned_name = re.sub(r'^.*?(?:Raz[ãa]o|Social|Nome|Razao)\s+(?:Social\s+)?', '', name, flags=re.IGNORECASE).strip()
                if len(cleaned_name) >= 10:
                    name = cleaned_name
                
                # [FIX] Inserir espaços antes de sufixos empresariais colados
                name = re.sub(r'([A-ZÀ-Ú])(S\.A\.|S\.A|SA|S/A)$', r'\1 \2', name, flags=re.IGNORECASE)
                name = re.sub(r'([A-ZÀ-Ú])(LTDA|ME|EPP|EIRELI)$', r'\1 \2', name, flags=re.IGNORECASE)
                
                # [FIX] Rejeitar nomes muito curtos e tentar próximo padrão
                if len(name) < 10:
                    logger.debug(f"Rejecting short name '{name}', trying next pattern")
                    continue
                
                # [FIX] Rejeitar nomes que são logos ou artefatos OCR comuns
                invalid_names = ['polo it', 'polo ir', 'poloit', 'logo']
                if name.lower().strip() in invalid_names:
                    logger.debug(f"Rejecting invalid/logo name '{name}', trying next pattern")
                    continue
                
                # [FIX] Nome deve ter sufixo empresarial ou ser longo o suficiente
                has_suffix = any(s in name.upper() for s in ['LTDA', 'S.A', 'SA', 'ME', 'EPP', 'EIRELI', 'S/A'])
                if has_suffix or len(name) >= 15:
                    entity.razao_social = name.split('\n')[0].strip()[:100]
                    logger.info(f"Parsed razao_social from section: {entity.razao_social}")
                    break
        
        entity.endereco = self._extract_address(section)
        return entity
    
    # ==================== ADDRESS EXTRACTION ====================
    def _extract_address(self, text: str) -> Optional[Address]:
        address = Address()
        log_patterns = [
            # [FIX] NFS-e Barueri: Endereço multi-linha começando com RUA/AVENIDA
            # Ex: "RUA POMPEIA , 368\nCHACARAS MARCO / CRUZ PRETA\nCEP 06419-140 - BARUERI - SP"
            r'((?:RUA|AVENIDA|AV\.?)\s+[A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\,\.\-]+?)(?=\n.*CNPJ|\n.*Inscrição|\n.*Telefone|$)',
            
            # Padrão NFS-e SP: linha após "Endereço Município CEP" contém endereço colado
            # Ex: "FABIODEALMEIDAMAGALHAES,120,JARDIMSANTOELIAS SãoPaulo-SP 5135370"
            r'Endere[çc]o\s+Munic[íi]pio\s+CEP\n([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\,\s\.\-]+?)(?:\s+[A-ZÀ-Ú][a-zà-ú]+(?:Paulo|Janeiro)?-?[A-Z]{2})',
            
            # Padrão genérico: endereço na mesma linha
            r'(?:Endere[çc]o|Logradouro)[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\,\-]+?)(?=\s*(?:N[°ºo]|Num|,|\n|Bairro|CEP|$))',
            r'(?:Rua|Avenida|Av\.|Travessa|Alameda)\s+([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\-]+?)(?=\s*(?:,|N[°º]|\n|$))',
        ]
        for pattern in log_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                val = match.group(1).strip().rstrip(',')
                if len(val) > 3:
                    address.logradouro = val[:100]
                    logger.debug(f"Extracted address: {address.logradouro}")
                    break
        
        num_patterns = [r'(?:N[°ºo]|Num(?:ero)?)[:\.\s]*(\d+[A-Z]?)']
        for pattern in num_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                address.numero = match.group(1)
                break
        
        bairro_patterns = [r'Bairro[:\s]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\s\.\-]+?)(?=\s*(?:Munic|Cidade|UF|CEP|\n|$))']
        for pattern in bairro_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                val = match.group(1).strip()
                if len(val) > 2:
                    address.bairro = val[:50]
                    break
        
        city_patterns = [r'(?:Munic[íi]pio|Cidade)[:\s]*([A-ZÀ-Ú][A-ZÀ-Ú\s\-]+?)(?=\s*(?:UF|Estado|CEP|/|\n|$))']
        for pattern in city_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                val = match.group(1).strip()
                if len(val) > 2:
                    address.municipio = val[:50]
                    break
        
        cep_match = re.search(r'CEP[:\s]*(\d{5}-?\d{3})', text, re.IGNORECASE)
        if cep_match: address.cep = cep_match.group(1)
        else:
            cep_match = re.search(r'\b(\d{5}-\d{3})\b', text)
            if cep_match: address.cep = cep_match.group(1)
        
        uf_patterns = [r'(?:UF|Estado)[:\s]*([A-Z]{2})\b']
        for pattern in uf_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                uf = match.group(1).upper()
                if uf in self.BRAZILIAN_STATES:
                    address.uf = uf
                    break
        
        if not address.uf:
            for state in self.BRAZILIAN_STATES:
                if re.search(rf'\b{state}\b', text):
                    address.uf = state
                    break
        
        has_data = any([address.logradouro, address.bairro, address.municipio, address.cep])
        return address if has_data else None
    
    # ==================== VALUE EXTRACTION ====================
    def _parse_monetary_value(self, value_str: str) -> Optional[float]:
        if not value_str: return None
        try:
            clean = value_str.replace('R$', '').strip()
            clean = clean.replace(' ', '')
            if ',' in clean and '.' in clean:
                clean = clean.replace('.', '').replace(',', '.')
            elif ',' in clean:
                clean = clean.replace(',', '.')
            return float(clean)
        except: return None
    def _extract_value_spatial(self, pdf: pdfplumber.PDF, keywords: List[str]) -> Optional[float]:
        val_str = self._extract_text_spatial(pdf, keywords, r'R?\$\s*([\d\.]+(?:,\d{2})?)')
        if val_str:
             match = re.search(r'R?\$\s*([\d\.]+(?:,\d{2})?)', val_str)
             if match: return self._parse_monetary_value(match.group(1))
        return None
    def _extract_text_spatial(self, pdf: pdfplumber.PDF, keywords: List[str], content_pattern: str, force_vertical: bool = False) -> Optional[str]:
        """
        Generic spatial extractor with PROXIMITY logic.
        1. Finds keyword.
        2. Scans both RIGHT and DOWN directions.
        3. Calculates distance to all valid matches.
        4. Returns the match consistently CLOSEST to the keyword.
        """
        best_match = None
        min_distance = float('inf')
        try:
            for page in pdf.pages:
                words = page.extract_words()
                # Sort: Top-down, Left-right
                words.sort(key=lambda w: (w['top'], w['x0']))
                
                for word in words:
                    # Check text match
                    if any(k.upper() in word['text'].upper() for k in keywords):
                        
                        candidates = []
                        # --- STRATEGY 1: LOOK RIGHT ---
                        if not force_vertical:
                            y_top = word['top'] - 3
                            y_bottom = word['bottom'] + 3
                            x_start_right = word['x1']
                            
                            right_text = ""
                            # Find the immediate text sequence to the right
                            current_sequence = []
                            for candidate in words:
                                if candidate['top'] >= y_top and candidate['bottom'] <= y_bottom:
                                    if candidate['x0'] > x_start_right:
                                        right_text += candidate['text'] + " "
                                        current_sequence.append(candidate)
                            
                            matches = re.finditer(content_pattern, right_text)
                            for m in matches:
                                 val = m.group(0) # or group(1) if capture group
                                 if 'R$' in content_pattern and not any(c.isdigit() for c in val): continue
                                 
                                 if current_sequence:
                                     dist = current_sequence[0]['x0'] - word['x1']
                                     candidates.append((val, dist, 'right'))
                        # --- STRATEGY 2: LOOK DOWN ---
                        x_start_down = word['x0'] - 10  # Tolerance left
                        x_end_down = word['x1'] + 150   # Wide tolerance right
                        y_start_down = word['bottom']
                        y_end_down = word['bottom'] + 35 # Look slightly deeper
                        
                        down_text = ""
                        down_sequence = []
                        for candidate in words:
                            if candidate['top'] >= y_start_down and candidate['top'] <= y_end_down:
                                cand_center = (candidate['x0'] + candidate['x1']) / 2
                                if cand_center >= x_start_down and cand_center <= x_end_down:
                                     down_text += candidate['text'] + " "
                                     down_sequence.append(candidate)
                        
                        matches = re.finditer(content_pattern, down_text)
                        for m in matches:
                             val = m.group(0)
                             if 'R$' in content_pattern and not any(c.isdigit() for c in val): continue
                             
                             if down_sequence:
                                 # Distance: Label Bottom to Word Top
                                 dist = down_sequence[0]['top'] - word['bottom']
                                 candidates.append((val, dist, 'down'))
                        # --- SELECTION ---
                        down_matches = [c for c in candidates if c[2] == 'down']
                        
                        # Filter bad matches logic
                        final_candidates = []
                        all_cands = candidates if not force_vertical else down_matches
                        
                        for val, dist, direction in all_cands:
                             if 'R$' not in content_pattern:
                                # Semantic validation for non-money fields
                                if len(val) == 8 and val.startswith('20'): continue
                                if '/' in val or '-' in val: continue
                             final_candidates.append((val, dist, direction))
                        
                        if final_candidates:
                             # Sort by distance
                             final_candidates.sort(key=lambda x: x[1])
                             top_match = final_candidates[0]
                             
                             if top_match[1] < min_distance:
                                 min_distance = top_match[1]
                                 best_match = top_match[0]
        except Exception as e:
            logger.error(f"Spatial extraction error: {e}")
        
        return best_match
    def _extract_valores(self, text: str, pdf: pdfplumber.PDF) -> TaxValues:
        """Extract monetary values"""
        valores = TaxValues()
        
        # 1. Spatial Extraction (Most Reliable)
        if pdf:
            # Total
            v = self._extract_value_spatial(pdf, ['Valor Total', 'Valor Líquido', 'Valor a Pagar'])
            if v: valores.valor_total = v
            
            # Serviços
            v = self._extract_value_spatial(pdf, ['Valor dos Serviços', 'Total Serviços'])
            if v: valores.valor_servicos = v
            elif valores.valor_total: valores.valor_servicos = valores.valor_total
            
            # ISS
            v = self._extract_value_spatial(pdf, ['Valor do ISS', 'ISSQN Devido'])
            if v: valores.iss = v
        # 2. Section/Regex Fallback (if spatial failed)
        if not valores.valor_total:
             # ... regex logic ...
             pass
             
        return valores
    def _extract_items(self, pdf: pdfplumber.PDF) -> List[ServiceItem]:
        """Extract service items (Placeholder)"""
        return []