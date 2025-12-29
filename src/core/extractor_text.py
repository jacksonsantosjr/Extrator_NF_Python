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
                
                # Extract retentions (NFS-e only)
                if doc.document_type == DocumentType.NFSE and doc.valores:
                    retentions = self._extract_retentions(full_text)
                    doc.valores.pis_retido = retentions.get('pis_retido')
                    doc.valores.cofins_retido = retentions.get('cofins_retido')
                    doc.valores.csll_retida = retentions.get('csll_retida')
                    doc.valores.ir = retentions.get('irrf_retido')
                    doc.valores.inss = retentions.get('inss_retido')
                    doc.valores.iss_retido = retentions.get('iss_retido')
                
                doc.itens = self._extract_items(pdf)

                
                # POST-EXTRACTION RULES:
                # Rule 1: IPI only exists in NF-e, never in NFS-e
                if doc.document_type == DocumentType.NFSE and doc.valores:
                    doc.valores.ipi = None
                
                # Rule 2: ISS only exists in NFS-e, never in NF-e
                # ISS is a service tax, NF-e is for merchandise operations
                if doc.document_type == DocumentType.NFE and doc.valores:
                    doc.valores.iss = None
                    doc.valores.iss_retido = None
                
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
        """Extract monetary values using spatial extraction with regex fallback"""
        valores = TaxValues()
        
        # Expanded keywords for spatial extraction
        VALOR_TOTAL_KEYWORDS = [
            'Valor Total', 'Total da Nota', 'Valor a Pagar', 'VALOR NF',
            'Total Geral', 'Valor Total Nota', 'TOTAL', 'Vl Total',
            'Valor Líquido', 'Líquido', 'Total Líquido'
        ]
        VALOR_SERVICOS_KEYWORDS = [
            'Valor dos Serviços', 'Total Serviços', 'Base de Cálculo',
            'Valor Produtos', 'Vl Serviços', 'Base Cálculo ISS',
            'Valor Total dos Serviços', 'VALOR DOS SERVIÇOS'
        ]
        ISS_KEYWORDS = [
            'Valor do ISS', 'ISSQN Devido', 'ISS Retido', 'Valor ISS',
            'ISSQN', 'ISS a Reter', 'ISS'
        ]
        DESCONTO_KEYWORDS = ['Desconto', 'Descontos', 'Desc.', 'Total Descontos']
        PIS_KEYWORDS = ['PIS', 'PIS Retido', 'Valor PIS']
        COFINS_KEYWORDS = ['COFINS', 'COFINS Retido', 'Valor COFINS']
        IR_KEYWORDS = ['IR', 'IRRF', 'IR Retido', 'Imposto de Renda']
        INSS_KEYWORDS = ['INSS', 'INSS Retido', 'Valor INSS']
        CSLL_KEYWORDS = ['CSLL', 'CSLL Retida', 'Valor CSLL']
        ICMS_KEYWORDS = ['ICMS', 'Valor ICMS', 'ICMS Total']
        IPI_KEYWORDS = ['IPI', 'Valor IPI', 'IPI Total']
        
        # 1. Spatial Extraction (for text-based PDFs)
        if pdf:
            # Total
            v = self._extract_value_spatial(pdf, VALOR_TOTAL_KEYWORDS)
            if v: valores.valor_total = v
            
            # Serviços
            v = self._extract_value_spatial(pdf, VALOR_SERVICOS_KEYWORDS)
            if v: valores.valor_servicos = v
            
            # Valor Líquido (if different from total)
            v = self._extract_value_spatial(pdf, ['Valor Líquido', 'Líquido a Receber', 'Total Líquido'])
            if v: valores.valor_liquido = v
            
            # ISS
            v = self._extract_value_spatial(pdf, ISS_KEYWORDS)
            if v: valores.iss = v
            
            # Desconto
            v = self._extract_value_spatial(pdf, DESCONTO_KEYWORDS)
            if v: valores.desconto = v
            
            # PIS
            v = self._extract_value_spatial(pdf, PIS_KEYWORDS)
            if v: valores.pis = v
            
            # COFINS
            v = self._extract_value_spatial(pdf, COFINS_KEYWORDS)
            if v: valores.cofins = v
            
            # IR
            v = self._extract_value_spatial(pdf, IR_KEYWORDS)
            if v: valores.ir = v
            
            # INSS
            v = self._extract_value_spatial(pdf, INSS_KEYWORDS)
            if v: valores.inss = v
            
            # CSLL (apenas retenção, não valor devido - extraído em _extract_retentions)
            # ICMS
            v = self._extract_value_spatial(pdf, ICMS_KEYWORDS)
            if v: valores.icms = v
            
            # IPI
            v = self._extract_value_spatial(pdf, IPI_KEYWORDS)
            if v: valores.ipi = v
        
        # 2. Regex Extraction (always run to fill in missing values)
        # This covers OCR documents and fills gaps from spatial extraction
        valores = self._extract_valores_regex(text, valores)
        
        # 3. FINAL FALLBACK: Ensure valor_total, valor_servicos are both populated
        # Based on web version behavior: these columns should have values
        if valores.valor_total and not valores.valor_servicos:
            valores.valor_servicos = valores.valor_total
        elif valores.valor_servicos and not valores.valor_total:
            valores.valor_total = valores.valor_servicos
        
        # NOTE: valor_liquido should NOT fallback to valor_total
        # It should be extracted from document or calculated from retentions
             
        return valores
    
    def _extract_valores_regex(self, text: str, valores: TaxValues) -> TaxValues:
        """
        Extract monetary values using regex patterns.
        This is the primary method for OCR documents where spatial positioning is lost.
        Patterns based on analysis of 157 real documents (766 unique labels found).
        
        IMPORTANT RULES:
        1. Separate ISS DEVIDO from ISS RETIDO - they go to different columns
        2. Patterns must be more specific to avoid false positives
        3. Fallback: if valor_total exists but not valor_servicos, copy it (and vice-versa)
        """
        
        def extract_value(patterns: List[str], text: str, min_value: float = 0.01) -> Optional[float]:
            """Try multiple patterns and return first match with value > min_value"""
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                if match:
                    value_str = match.group(1)
                    parsed = self._parse_monetary_value(value_str)
                    if parsed and parsed >= min_value:
                        return parsed
            return None
        
        # =======================================================================
        # VALOR TOTAL patterns (based on real documents)
        # Must be specific to avoid capturing partial values
        # =======================================================================
        total_patterns = [
            r'VALOR\s*TOTAL\s*(?:DO\s*)?(?:SERVIÇO|NOTA|DOCUMENTO)[^\d]*R?\$?\s*([\d.,]+)',
            r'VALOR\s*(?:DA\s*)?(?:NOTA|FATURA|DOCUMENTO)\s*R?\$?\s*([\d.,]+)',
            r'TOTAL\s*(?:DA\s*)?NOTA[^\d]*R?\$?\s*([\d.,]+)',
            r'VALOR\s*BRUTO(?:\s*(?:DA\s*)?NOTA)?[^\d]*R?\$?\s*([\d.,]+)',
            r'VALOR\s*DOCUMENTO\s*R?\$?\s*([\d.,]+)',
            r'VALOR\s*A\s*PAGAR[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.valor_total:
            valores.valor_total = extract_value(total_patterns, text)
        
        # =======================================================================
        # VALOR SERVIÇOS patterns
        # =======================================================================
        servicos_patterns = [
            r'VALOR\s*(?:TOTAL\s*)?(?:DOS?\s*)?SERVIÇOS?[^\d]*=?\s*R?\$?\s*([\d.,]+)',
            r'SERVIÇOS?\s*\(R\$\)[^\d]*([\d.,]+)',
            r'TOTAL\s*(?:DOS?\s*)?SERVIÇOS[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.valor_servicos:
            valores.valor_servicos = extract_value(servicos_patterns, text)
        
        # =======================================================================
        # VALOR LÍQUIDO patterns  
        # Specific patterns that exclude "Total" indicators
        # =======================================================================
        liquido_patterns = [
            r'VALOR\s*LÍQUIDO\s*(?:DA\s*)?(?:NOTA|NFS-?E|DOCUMENTO)?[^\d]*R?\$?\s*([\d.,]+)',
            r'LÍQUIDO\s*(?:A\s*)?(?:RECEBER|PAGAR)?[^\d]*R?\$?\s*([\d.,]+)',
            r'VALOR\s*LIQUIDO[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.valor_liquido:
            valores.valor_liquido = extract_value(liquido_patterns, text)
        
        # =======================================================================
        # BASE DE CÁLCULO patterns
        # =======================================================================
        base_patterns = [
            r'BASE\s*(?:DE\s*)?CÁLCULO[^\d]*R?\$?\s*([\d.,]+)',
            r'B\.\s*CÁLCULO[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.valor_servicos:
            base_value = extract_value(base_patterns, text)
            if base_value:
                valores.valor_servicos = base_value
        
        # =======================================================================
        # ISS DEVIDO patterns (NOT RETIDO)
        # CRITICAL: Must exclude patterns with "RETIDO", "RETENÇÃO", "A RETER"
        # =======================================================================
        iss_devido_patterns = [
            # Patterns that specifically indicate "devido" (not retained)
            r'VALOR\s*(?:DO\s*)?ISS(?:QN)?\s*(?:DEVIDO)?[^\d]*\(R\$\)[^\d]*([\d.,]+)',
            r'ISS(?:QN)?\s*DEST[AE]\s*NFS-?E[^\d]*R?\$?\s*([\d.,]+)',
            r'ISS(?:QN)?\s*DEVIDO[^\d]*R?\$?\s*([\d.,]+)',
            r'ISS(?:QN)?\s*APURADO[^\d]*R?\$?\s*([\d.,]+)',
            # Generic ISS but only if not followed by RETIDO
            r'(?<!RETIDO\s)VALOR\s*(?:DO\s*)?ISS(?:QN)?(?!\s*RETID)[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.iss:
            valores.iss = extract_value(iss_devido_patterns, text, min_value=1.0)
        
        # =======================================================================
        # DESCONTO patterns
        # =======================================================================
        desconto_patterns = [
            r'(?:\(-\)\s*)?DESCONTO(?:\s*INCONDICIONADO)?[^\d]*R?\$?\s*([\d.,]+)',
            r'DESCONTOS?\s*(?:INCONDICIONADOS)?[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.desconto:
            valores.desconto = extract_value(desconto_patterns, text, min_value=0.01)
        
        # =======================================================================
        # PIS patterns - DISABLED
        # NOTE: PIS extraction disabled - patterns were too loose and capturing
        # incorrect values. For NFS-e, PIS is always RETIDO, not DEVIDO.
        # =======================================================================
        # PIS patterns disabled - capturing incorrect values
        
        # =======================================================================
        # COFINS patterns - DISABLED
        # NOTE: COFINS extraction disabled - patterns were too loose.
        # For NFS-e, COFINS is always RETIDO, not DEVIDO.
        # =======================================================================
        # COFINS patterns disabled - NF-e uses spatial extraction, NFS-e uses COFINS RETIDO
        
        # =======================================================================
        # IRRF patterns (IR Retido na Fonte)
        # Pattern: "IRRF (1,50%)R$ 47,25" -> capture 47,25 (value after R$)
        # OCR variations: "IRRF (1,50$)RS 47" with $ instead of % and RS instead of R$
        # =======================================================================
        irrf_patterns = [
            # IRRF (X,XX% or X,XX$)R$ or RS VALUE - handles OCR variations
            r'IRRF\s*\([^)]*[%$]?\)\s*R[S$]?\s*([0-9][0-9.,]*)',
            r'IR\s*\([^)]*[%$]?\)\s*R[S$]?\s*([0-9][0-9.,]*)',
            # IR RETIDO R$ VALUE
            r'IR\s*RETIDO\s*[^\d]*R[S$]?\s*([0-9][0-9.,]*)',
            # IRRF standalone with value
            r'IRRF\s+R[S$]?\s*([0-9][0-9.,]*)',
        ]
        if not valores.ir:
            valores.ir = extract_value(irrf_patterns, text, min_value=1.0)
        
        # =======================================================================
        # INSS RETIDO patterns
        # =======================================================================
        inss_patterns = [
            # INSS RETIDO VALUE
            r'INSS\s*RETIDO\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            # INSS (X%) R$ VALUE
            r'INSS\s*\([^)]*%?\)\s*R?\$\s*([0-9][0-9.,]*)',
            # Retenção de 11% INSS R$ VALUE
            r'RETENÇÃO\s*(?:DE\s*)?11%?\s*INSS\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
        ]
        if not valores.inss:
            valores.inss = extract_value(inss_patterns, text, min_value=10.0)
        
        # =======================================================================
        # PIS RETIDO patterns (for NFS-e)
        # =======================================================================
        pis_retido_patterns = [
            r'PIS\s*RETIDO\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'RETENÇÃO\s*(?:NA\s*FONTE\s*)?(?:DE\s*)?PIS\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
        ]
        if not valores.pis_retido:
            valores.pis_retido = extract_value(pis_retido_patterns, text, min_value=0.01)
        
        # =======================================================================
        # COFINS RETIDO patterns (for NFS-e)
        # =======================================================================
        cofins_retido_patterns = [
            r'COFINS\s*RETIDO[S]?\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'RETENÇÃO\s*(?:NA\s*FONTE\s*)?(?:DE\s*)?COFINS\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
        ]
        if not valores.cofins_retido:
            valores.cofins_retido = extract_value(cofins_retido_patterns, text, min_value=0.01)
        
        # =======================================================================
        # CSLL RETIDA patterns (for NFS-e)
        # =======================================================================
        csll_retida_patterns = [
            r'CSLL\s*RETIDA?\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'RETENÇÃO\s*(?:DE\s*)?CSLL\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
        ]
        if not valores.csll_retida:
            valores.csll_retida = extract_value(csll_retida_patterns, text, min_value=0.01)
        
        # =======================================================================
        # ISS RETIDO / ISSQN RETIDO patterns
        # =======================================================================
        iss_retido_patterns = [
            r'ISS\s*RETIDO\s*(?:NA\s*FONTE)?\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'ISSQN\s*RETIDO\s*(?:NA\s*FONTE)?\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
        ]
        if not valores.iss_retido:
            valores.iss_retido = extract_value(iss_retido_patterns, text, min_value=1.0)
        
        # =======================================================================
        # ICMS patterns (NF-e only)
        # =======================================================================
        icms_patterns = [
            r'VALOR\s*(?:DO\s*)?ICMS\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'ICMS\s*\(R\$\)\s*[^\d]*([0-9][0-9.,]*)',
        ]
        if not valores.icms:
            valores.icms = extract_value(icms_patterns, text, min_value=1.0)
        
        # =======================================================================
        # IPI patterns (NF-e only, cleared for NFS-e in caller)
        # =======================================================================
        ipi_patterns = [
            r'VALOR\s*(?:DO\s*)?IPI\s*[^\d]*R?\$?\s*([0-9][0-9.,]*)',
            r'IPI\s*\(R\$\)\s*[^\d]*([0-9][0-9.,]*)',
        ]
        if not valores.ipi:
            valores.ipi = extract_value(ipi_patterns, text, min_value=1.0)
        
        # =======================================================================
        # OUTRAS RETENÇÕES patterns
        # =======================================================================
        retencoes_patterns = [
            r'(?:OUTRAS|TOTAL)\s*RETENÇÕES[^\d]*R?\$?\s*([\d.,]+)',
        ]
        if not valores.outras_retencoes:
            valores.outras_retencoes = extract_value(retencoes_patterns, text, min_value=0.01)
        
        # NOTE: Fallback logic moved to _extract_valores() method
        
        # =======================================================================
        # FALLBACK LOGIC: Ensure both valor_total and valor_servicos are populated
        # Rule: If one exists but not the other, copy the value
        # =======================================================================
        if valores.valor_total and not valores.valor_servicos:
            valores.valor_servicos = valores.valor_total
        elif valores.valor_servicos and not valores.valor_total:
            valores.valor_total = valores.valor_servicos
        
        logger.debug(f"Extracted valores via regex: total={valores.valor_total}, servicos={valores.valor_servicos}, liquido={valores.valor_liquido}, iss={valores.iss}")
        
        return valores

    def _extract_retentions(self, text: str) -> Dict[str, Optional[float]]:
        """
        Extract tax retention values (valores retidos na fonte).
        
        Uses proximity-based search to handle:
        - Labels without spaces (PIS/COFINSRetidos)
        - Values in adjacent lines (tabular layouts)
        - Multiple representations of same value
        
        Returns dict with keys: pis_retido, cofins_retido, csll_retida, irrf_retido, inss_retido, iss_retido
        """
        retentions = {
            'pis_retido': None,
            'cofins_retido': None,
            'csll_retida': None,
            'irrf_retido': None,
            'inss_retido': None,
            'iss_retido': None,
        }
        
        # 1. Try to find TRIBUTAÇÃO FEDERAL section (may fail due to OCR corruption)
        # Pattern tolerant to OCR errors: TRIBUT + any chars + FEDERAL
        trib_section = None
        trib_match = re.search(r'TRIBUT[^\n]{0,20}FEDERAL.*?(?=VALOR\s+TOTAL|DISCRIMINA|TOTAIS|INFORMA[ÇC]|$)', text, re.DOTALL | re.IGNORECASE)
        if trib_match:
            trib_section = trib_match.group(0)
            logger.debug(f"Found TRIBUTAÇÃO FEDERAL section: {len(trib_section)} chars")
        
        # Use full text as fallback
        search_text = trib_section if trib_section else text
        
        # 2. Try consolidated PIS/COFINS FIRST (most reliable for TOTVS layout)
        consolidated_pis_cofins = self._extract_consolidated_pis_cofins(text)
        if consolidated_pis_cofins:
            # Split proportionally: PIS 0.65%, COFINS 3% (total 3.65%)
            retentions['pis_retido'] = round(consolidated_pis_cofins * 0.178, 2)  # 0.65/3.65
            retentions['cofins_retido'] = round(consolidated_pis_cofins * 0.822, 2)  # 3/3.65
            logger.debug(f"Split consolidated PIS/COFINS {consolidated_pis_cofins}: PIS={retentions['pis_retido']}, COFINS={retentions['cofins_retido']}")
        
        # 3. Extract individual values (only if not found in consolidated)
        if not retentions['pis_retido']:
            retentions['pis_retido'] = self._extract_retention_value(search_text, 'PIS')
        if not retentions['cofins_retido']:
            retentions['cofins_retido'] = self._extract_retention_value(search_text, 'COFINS')
        
        retentions['csll_retida'] = self._extract_retention_value(search_text, 'CSLL')
        retentions['irrf_retido'] = self._extract_retention_value(search_text, 'IRRF')
        retentions['inss_retido'] = self._extract_retention_value(search_text, 'INSS')
        retentions['iss_retido'] = self._extract_retention_value(text, 'ISS', is_iss=True)
        
        # 4. Handle consolidated IRRF,CP,CSLL (if CSLL not found individually)
        if not retentions['csll_retida']:
            consolidated_csll = self._extract_consolidated_irrf_csll(text)
            if consolidated_csll:
                retentions['csll_retida'] = consolidated_csll
        
        logger.debug(f"Extracted retentions: {retentions}")
        return retentions

    def _extract_retention_value(self, text: str, tax_name: str, is_iss: bool = False) -> Optional[float]:
        """
        Extract retention value for a specific tax using proximity search.
        
        Handles:
        - Direct match: "PIS RETIDO 147,80"
        - Adjacent lines: "PIS RETIDO\n147,80"
        - Tabular: "PIS (R$)\n43,58"
        - Colado: "PISRetido 147,80"
        """
        # Patterns specific to each tax
        patterns = {
            'PIS': [
                rf'{tax_name}\s*(?:/PASEP)?\s+RETID[OA]\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'{tax_name}Retid[oa]\s*[:\s]*R?\$?\s*([\d\.,]+)',  # Colado
                rf'RETEN[ÇC][ÃA]O\s+(?:DE\s+)?{tax_name}\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
            'COFINS': [
                rf'{tax_name}\s+RETID[OA]\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'{tax_name}Retid[oa]\s*[:\s]*R?\$?\s*([\d\.,]+)',  # Colado
                rf'RETEN[ÇC][ÃA]O\s+(?:DE\s+)?{tax_name}\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
            'CSLL': [
                rf'{tax_name}\s+RETID[OA]\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'{tax_name}Retid[oa]\s*[:\s]*R?\$?\s*([\d\.,]+)',  # Colado
                rf'RETEN[ÇC][ÃA]O\s+(?:DE\s+)?{tax_name}\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
            'IRRF': [
                rf'{tax_name}\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'IR\s+RETIDO\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
            'INSS': [
                rf'{tax_name}\s+RETIDO\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'{tax_name}Retido\s*[:\s]*R?\$?\s*([\d\.,]+)',  # Colado
                rf'RETEN[ÇC][ÃA]O\s+(?:DE\s+)?{tax_name}\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
            'ISS': [
                rf'{tax_name}\s+RETIDO\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'{tax_name}\s+[Aa]\s+[Rr]ETER\s*[:\s]*R?\$?\s*([\d\.,]+)',
                rf'RETEN[ÇC][ÃA]O\s+(?:DE\s+)?{tax_name}(?:QN)?\s*[:\s]*R?\$?\s*([\d\.,]+)',
            ],
        }
        
        # Try direct patterns first
        for pattern in patterns.get(tax_name, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value_str = match.group(1)
                value = self._parse_monetary_value(value_str)
                if value and value > 0:
                    logger.debug(f"Found {tax_name} retido via pattern: {value}")
                    return value
        
        # Proximity search: find label, then search nearby for value
        label_patterns = [
            rf'{tax_name}\s*(?:/PASEP)?\s*[\(\[]?R\$[\)\]]?',  # "PIS (R$)" or "PIS [R$]"
            rf'{tax_name}\s+RETID[OA]',
            rf'{tax_name}Retid[oa]',  # Colado
        ]
        
        for label_pattern in label_patterns:
            label_match = re.search(label_pattern, text, re.IGNORECASE)
            if label_match:
                # Search in next 200 characters (2-3 lines)
                context_start = label_match.end()
                context_end = min(len(text), context_start + 200)
                context = text[context_start:context_end]
                
                # Find first monetary value
                value_match = re.search(r'R?\$?\s*([\d\.]+[,]\d{2})', context)
                if value_match:
                    value_str = value_match.group(1)
                    value = self._parse_monetary_value(value_str)
                    if value and value > 0:
                        logger.debug(f"Found {tax_name} retido via proximity: {value}")
                        return value
        
        return None

    def _extract_consolidated_pis_cofins(self, text: str) -> Optional[float]:
        """Extract consolidated PIS/COFINS retention value."""
        
        # STRATEGY: In TOTVS layout, labels and values are in separate lines
        # Line N:   "IRRF,CP,CSLL-Retidos PIS/COFINSRetidos ValorLíquidodaNFS-e"
        # Line N+1: "R$67,05 R$244,72 R$6.392,87"
        # We need to find the position of "PIS/COFINSRetidos" in label line,
        # then extract the value at the same position in the next line
        
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            # Find line with PIS/COFINSRetidos label
            if re.search(r'PIS/COFINS\s*Retid[OAoa]s?', line, re.IGNORECASE):
                # Count position of this label (how many labels before it)
                # Split by spaces and count labels before PIS/COFINS
                label_match = re.search(r'PIS/COFINS\s*Retid[OAoa]s?', line, re.IGNORECASE)
                if not label_match:
                    continue
                
                # Get text before PIS/COFINSRetidos
                text_before = line[:label_match.start()]
                
                # Count how many "Retid" labels are before (each represents a column)
                labels_before = len(re.findall(r'Retid[OAoa]s?', text_before, re.IGNORECASE))
                
                # Position is labels_before (0-indexed)
                position = labels_before
                
                # Get next line (values line)
                if i + 1 < len(lines):
                    values_line = lines[i + 1]
                    
                    # Extract all monetary values from values line
                    values = re.findall(r'R?\$?\s*([\d\.]+[,]\d{2})', values_line)
                    
                    # Get value at the same position
                    if position < len(values):
                        value_str = values[position]
                        value = self._parse_monetary_value(value_str)
                        if value and value > 0:
                            logger.debug(f"Found consolidated PIS/COFINS at position {position}: {value}")
                            return value
        
        # FALLBACK: Try direct patterns (for other layouts)
        patterns = [
            r'PIS/COFINS\s*[-]?\s*RETID[OA]S?\s*[:\s]*R?\$?\s*([\d\.,]+)',
            r'PIS/COFINSRetid[oa]s?\s*[:\s]*R?\$?\s*([\d\.,]+)',
            r'PIS/COFINSRetid[OA]s?\s*[:\s]*R?\$?\s*([\d\.,]+)',
            r'Reten[çc][ãa]o\s*do\s*PIS/COFINS\s*[:\s]*R?\$?\s*([\d\.,]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value_str = match.group(1)
                value = self._parse_monetary_value(value_str)
                if value and value > 0:
                    logger.debug(f"Found consolidated PIS/COFINS via fallback pattern: {value}")
                    return value
        
        return None

    def _extract_consolidated_irrf_csll(self, text: str) -> Optional[float]:
        """Extract CSLL from consolidated IRRF,CP,CSLL retention."""
        
        # Same logic as PIS/COFINS - labels and values in separate lines
        # IRRF,CP,CSLL-Retidos is FIRST label (position 0)
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            if re.search(r'IRRF\s*,\s*CP\s*,\s*CSLL\s*[-]?\s*Retid[OAoa]s?', line, re.IGNORECASE):
                if i + 1 < len(lines):
                    values_line = lines[i + 1]
                    values = re.findall(r'R?\$?\s*([\d\.]+[,]\d{2})', values_line)
                    
                    if len(values) > 0:
                        value_str = values[0]  # First value = CSLL
                        value = self._parse_monetary_value(value_str)
                        if value and value > 0:
                            logger.debug(f"Found CSLL at position 0: {value}")
                            return value
        
        # Fallback patterns
        patterns = [
            r'IRRF\s*,\s*CP\s*,\s*CSLL\s*[-]?\s*RETID[OA]S?\s*[:\s]*R?\$?\s*([\d\.,]+)',
            r'IRRF,CP,CSLL[-]?Retid[oa]s?\s*[:\s]*R?\$?\s*([\d\.,]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value_str = match.group(1)
                value = self._parse_monetary_value(value_str)
                if value and value > 0:
                    logger.debug(f"Found CSLL via fallback: {value}")
                    return value
        
        return None

    def _extract_items(self, pdf: pdfplumber.PDF) -> List[ServiceItem]:
        """Extract service items (Placeholder)"""
        return []
