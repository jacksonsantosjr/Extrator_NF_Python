"""
Serviço de extração de dados usando Ollama (IA Local).
Replica o comportamento do Gemini da versão web.
"""
import requests
import json
import re
from typing import Optional, Dict, Any
from loguru import logger

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "phi3"  # Modelo rápido e eficiente

EXTRACTION_PROMPT = """Você é um especialista em extração de dados de documentos fiscais brasileiros.
Analise o texto abaixo e extraia as informações no formato JSON especificado.

REGRAS IMPORTANTES:
1. Responda APENAS com JSON válido, sem explicações
2. Use null para campos não encontrados
3. Valores monetários: números com ponto decimal (ex: 1234.56)
4. Datas: formato YYYY-MM-DD
5. CNPJ/CPF: apenas números, sem formatação

ATENÇÃO CRÍTICA - DIFERENÇA ENTRE NÚMERO E CHAVE DE ACESSO:
- O campo "numeroDocumento" é o NÚMERO DA NOTA (geralmente 1 a 10 dígitos, como "144", "12345", "900")
- Procure por labels como "Número da NFS-e", "Número", "Nº", "N°" seguido de poucos dígitos
- NUNCA coloque a Chave de Acesso (que tem EXATAMENTE 44 dígitos) no campo numeroDocumento
- A Chave de Acesso deve ir APENAS no campo "chaveAcessoNFe"
- Exemplo: Se o documento mostra "Número da NFS-e: 144", então numeroDocumento = "144"

ESTRUTURA JSON OBRIGATÓRIA:
{
  "tipoDocumento": "NFS-e" ou "NF-e Modelo 55" ou "Desconhecido",
  "numeroDocumento": "string com 1-10 dígitos ou null (NUNCA 44 dígitos)",
  "dataEmissao": "YYYY-MM-DD ou null",
  "dataSaidaEntrada": "YYYY-MM-DD ou null",
  "emitente": {
    "cnpjCpf": "somente números ou null",
    "nomeRazaoSocial": "string ou null",
    "enderecoCompleto": "string ou null"
  },
  "destinatarioTomador": {
    "cnpjCpf": "somente números ou null",
    "nomeRazaoSocial": "string ou null",
    "enderecoCompleto": "string ou null"
  },
  "valores": {
    "totalDocumento": number ou null,
    "valorLiquidoDocumento": number ou null
  },
  "chaveAcessoNFe": "exatamente 44 dígitos ou null"
}

--- TEXTO DO DOCUMENTO ---
{document_text}
--- FIM DO DOCUMENTO ---

Responda APENAS com o JSON:"""


def is_ollama_available() -> bool:
    """Verifica se o Ollama está rodando."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False


def extract_with_ollama(document_text: str, timeout: int = 120, check_cancel: callable = None) -> Optional[Dict[str, Any]]:
    """
    Extrai dados do documento usando Ollama/Phi3.
    
    Args:
        document_text: Texto extraído do PDF
        timeout: Timeout em segundos
        check_cancel: Função opcional que retorna True se o processamento foi cancelado
    
    Returns:
        Dict com dados extraídos ou None em caso de erro
    """
    # Limitar texto para evitar timeout (primeiros 6000 caracteres)
    text_truncated = document_text[:6000]
    prompt = EXTRACTION_PROMPT.replace("{document_text}", text_truncated)
    
    try:
        logger.info(f"Enviando para Ollama ({MODEL_NAME})...")
        
        # Usar streaming para permitir cancelamento durante a geração
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": True,  # Habilitar streaming para cancelamento
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1000
                }
            },
            timeout=timeout,
            stream=True
        )
        
        if response.status_code != 200:
            logger.error(f"Ollama retornou status {response.status_code}")
            return None
        
        # Coletar resposta em chunks (permite verificar cancelamento)
        result_text = ""
        for line in response.iter_lines():
            # Verificar cancelamento a cada chunk
            if check_cancel and check_cancel():
                logger.warning("Extração cancelada pelo usuário durante processamento Ollama")
                return None
            
            if line:
                try:
                    chunk = json.loads(line)
                    result_text += chunk.get("response", "")
                    
                    # Se finalizado, sair do loop
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
        
        logger.debug(f"Resposta bruta do Ollama: {result_text[:500]}...")
        
        # Extrair JSON da resposta
        json_data = _parse_json_from_response(result_text)
        
        if json_data:
            logger.info("Extração via Ollama concluída com sucesso!")
            return json_data
        else:
            logger.warning("Não foi possível parsear JSON da resposta do Ollama")
            return None
            
    except requests.exceptions.Timeout:
        logger.error("Timeout na requisição ao Ollama")
        return None
    except Exception as e:
        logger.error(f"Erro na extração via Ollama: {e}")
        return None


def _parse_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """Tenta extrair JSON válido da resposta do modelo."""
    text = response_text.strip()
    
    # Remover markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
    
    # Tentar encontrar JSON com regex
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    # Tentar parsear diretamente
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
