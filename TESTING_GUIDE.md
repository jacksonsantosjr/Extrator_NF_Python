# Guia de Testes - Fiscal Document Extractor

## 1. Preparação do Ambiente

### 1.1. Criar Ambiente Virtual

```bash
cd c:\Users\jackson.junior\.gemini\antigravity\playground\exo-planetary\fiscal-extractor-app

# Criar ambiente virtual
python -m venv venv

# Ativar ambiente virtual
venv\Scripts\activate
```

### 1.2. Instalar Dependências

```bash
# Instalar todas as dependências
pip install -r requirements.txt

# Verificar instalação
pip list
```

### 1.3. Instalar Tesseract OCR

**Importante:** Necessário apenas se for testar documentos escaneados.

1. Baixe o instalador: https://github.com/UB-Mannheim/tesseract/wiki
2. Execute o instalador (recomendado: `C:\Program Files\Tesseract-OCR`)
3. Durante a instalação, marque **Portuguese language pack**
4. Anote o caminho de instalação

### 1.4. Configurar Variáveis de Ambiente

```bash
# Copiar arquivo de exemplo
copy .env.example .env
```

Edite o arquivo `.env` e configure:

```env
# Se Tesseract não estiver no PATH do sistema
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Nível de log (DEBUG para testes detalhados)
LOG_LEVEL=DEBUG

# Diretório de saída
OUTPUT_DIR=./output
```

### 1.5. Configurar Mapeamento de CNPJs

Edite `config/filiais.json` com CNPJs reais da sua organização:

```json
{
  "12.345.678/0001-90": {
    "coligada": "1",
    "filial": "01",
    "nome": "Matriz São Paulo"
  },
  "98.765.432/0001-00": {
    "coligada": "2",
    "filial": "05",
    "nome": "Filial Rio de Janeiro"
  }
}
```

---

## 2. Testes Unitários

### 2.1. Executar Testes Básicos

```bash
# Executar todos os testes
python -m pytest tests/ -v

# Ou usar unittest
python -m unittest discover tests -v
```

### 2.2. Testar Modelos Individualmente

```bash
# Testar apenas modelos
python tests/test_models.py
```

**Resultado esperado:**
```
test_address_to_string ... ok
test_entity_cnpj_validation ... ok
test_fiscal_document_creation ... ok
test_cnpj_normalization ... ok
test_lookup_existing_cnpj ... ok
test_lookup_nonexistent_cnpj ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.XXXs

OK
```

---

## 3. Testes de Integração

### 3.1. Preparar Documentos de Teste

Crie uma pasta de testes:

```bash
mkdir test_documents
```

**Tipos de documentos necessários:**
1. ✅ **PDF com texto nativo** (NF-e ou NFS-e gerada digitalmente)
2. ✅ **PDF escaneado** (documento físico digitalizado)
3. ✅ **Arquivo ZIP** contendo múltiplos PDFs
4. ❌ **Arquivo inválido** (para testar tratamento de erros)

### 3.2. Teste Manual via Python Console

Crie um script de teste `test_extraction.py`:

```python
"""Script de teste manual para extração"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from models import Settings, CNPJMapper
from core import HybridExtractor

# Configuração
config_dir = Path("config")
settings = Settings.load_from_toml(config_dir / "settings.toml")
cnpj_mapper = CNPJMapper(config_dir / "filiais.json")

# Criar extrator
extractor = HybridExtractor(
    cnpj_mapper=cnpj_mapper,
    min_text_length=settings.processing.min_text_length,
    tesseract_cmd=None,  # Ou caminho do Tesseract
    ocr_language="por",
    ocr_dpi=300,
    pdf_page_limit=0,
)

# Testar com um PDF
test_pdf = Path("test_documents/exemplo.pdf")

if test_pdf.exists():
    with open(test_pdf, "rb") as f:
        pdf_bytes = f.read()
    
    print(f"Testando: {test_pdf.name}")
    doc, time_taken = extractor.extract(pdf_bytes, test_pdf.name)
    
    print(f"\n{'='*60}")
    print(f"Status: {doc.processing_status.value}")
    print(f"Tipo: {doc.document_type.value}")
    print(f"Número: {doc.numero}")
    print(f"Chave: {doc.chave_acesso}")
    print(f"Emitente CNPJ: {doc.emitente.cnpj if doc.emitente else 'N/A'}")
    print(f"Destinatário CNPJ: {doc.destinatario.cnpj if doc.destinatario else 'N/A'}")
    print(f"Valor Total: R$ {doc.valores.valor_total if doc.valores else 'N/A'}")
    print(f"Coligada: {doc.coligada}")
    print(f"Filial: {doc.filial}")
    print(f"Tempo: {time_taken:.2f}s")
    print(f"Escaneado: {'Sim' if doc.is_scanned else 'Não'}")
    print(f"Itens extraídos: {len(doc.itens)}")
    
    if doc.error_message:
        print(f"\n⚠️ Erro: {doc.error_message}")
    
    print(f"{'='*60}\n")
else:
    print(f"❌ Arquivo não encontrado: {test_pdf}")
```

Execute:

```bash
python test_extraction.py
```

---

## 4. Teste da Aplicação Completa

### 4.1. Executar a Aplicação

```bash
python src/main.py
```

**O que deve acontecer:**
- Uma janela Flet deve abrir
- Interface com tema escuro (padrão)
- Área de upload visível

### 4.2. Checklist de Testes da UI

#### Teste 1: Upload de Arquivo Único
- [ ] Clique na área de upload
- [ ] Selecione um PDF de teste
- [ ] Verifique se o arquivo aparece na lista
- [ ] Clique em "Processar Documentos"
- [ ] Observe a barra de progresso
- [ ] Verifique a mensagem de conclusão

**Resultado esperado:**
- Diálogo mostrando "✅ Sucesso: 1"
- Arquivo Excel gerado em `output/`

#### Teste 2: Upload de Múltiplos Arquivos
- [ ] Selecione 5-10 PDFs simultaneamente
- [ ] Todos devem aparecer na lista
- [ ] Processar e observar concorrência (3 simultâneos)
- [ ] Verificar tempo total

#### Teste 3: Upload de ZIP
- [ ] Selecione um arquivo ZIP contendo PDFs
- [ ] Processar
- [ ] Verificar se todos os PDFs internos foram extraídos

#### Teste 4: Cancelamento
- [ ] Selecione vários arquivos
- [ ] Inicie o processamento
- [ ] Clique em "Cancelar" durante o processamento
- [ ] Verifique se o processo para graciosamente

#### Teste 5: Tratamento de Erros
- [ ] Tente processar um arquivo não-PDF
- [ ] Tente processar um PDF corrompido
- [ ] Verifique se a aplicação não trava
- [ ] Verifique mensagens de erro no diálogo

#### Teste 6: Tema Claro/Escuro
- [ ] Clique no ícone de tema (sol/lua)
- [ ] Verifique se a interface muda
- [ ] Teste processamento em ambos os temas

#### Teste 7: Limpar Lista
- [ ] Adicione vários arquivos
- [ ] Clique no botão "Limpar lista"
- [ ] Verifique se a lista fica vazia

---

## 5. Validação do Excel Gerado

### 5.1. Abrir Arquivo Excel

Navegue até `output/` e abra o arquivo mais recente:
```
relatorio_fiscal_YYYYMMDD_HHMMSS.xlsx
```

### 5.2. Checklist de Validação

**Aba "Documentos Fiscais":**
- [ ] Cabeçalho formatado (azul, negrito, branco)
- [ ] Filtros ativos
- [ ] Primeira linha congelada
- [ ] Colunas com largura adequada
- [ ] Dados corretos:
  - [ ] Status
  - [ ] Nome do arquivo
  - [ ] Número do documento
  - [ ] CNPJs formatados (XX.XXX.XXX/XXXX-XX)
  - [ ] Datas no formato correto
  - [ ] Valores monetários
  - [ ] Coligada e Filial preenchidos

**Aba "Itens e Serviços":**
- [ ] Itens de cada documento listados
- [ ] Descrições completas
- [ ] Quantidades e valores corretos
- [ ] Vínculo com documento (nome do arquivo)

---

## 6. Testes de Performance

### 6.1. Teste de Volume

Prepare um lote de teste:
- 10 PDFs textuais
- 5 PDFs escaneados
- 2 arquivos ZIP

**Métricas a observar:**
- Tempo médio por PDF textual (meta: < 5s)
- Tempo médio por PDF escaneado (meta: < 60s)
- Taxa de sucesso (meta: > 95%)
- Uso de memória (observar no Gerenciador de Tarefas)

### 6.2. Teste de Concorrência

Configure `config/settings.toml`:

```toml
[processing]
max_concurrent_files = 1  # Testar sequencial
```

Processe 10 arquivos e anote o tempo.

Depois altere para:
```toml
max_concurrent_files = 3  # Testar concorrente
```

Processe os mesmos 10 arquivos e compare.

**Resultado esperado:** Redução de ~40-60% no tempo total.

---

## 7. Testes de Logs

### 7.1. Verificar Logs

Os logs são salvos em `logs/app_YYYY-MM-DD.log`

```bash
# Ver logs em tempo real
Get-Content logs/app_*.log -Wait -Tail 50
```

**O que verificar:**
- [ ] Início da aplicação registrado
- [ ] Carregamento de configurações
- [ ] Número de CNPJs carregados
- [ ] Detecção de tipo de PDF (texto/escaneado)
- [ ] Tempo de processamento por arquivo
- [ ] Erros detalhados (se houver)

---

## 8. Testes de Configuração

### 8.1. Teste de Limite de Páginas

Edite `config/settings.toml`:

```toml
[processing]
pdf_page_limit = 2  # Processar apenas 2 primeiras páginas
```

Teste com um PDF de 10+ páginas e verifique se apenas 2 páginas são processadas.

### 8.2. Teste de OCR

```toml
[ocr]
dpi = 150  # Baixa resolução (mais rápido, menos preciso)
```

vs

```toml
[ocr]
dpi = 600  # Alta resolução (mais lento, mais preciso)
```

Compare qualidade e tempo.

---

## 9. Checklist Final de Validação

Antes de considerar a aplicação pronta:

- [ ] Todos os testes unitários passam
- [ ] Extração de PDFs textuais funciona
- [ ] Extração de PDFs escaneados funciona (com Tesseract)
- [ ] Processamento de ZIPs funciona
- [ ] Mapeamento de CNPJ funciona
- [ ] Excel é gerado corretamente
- [ ] Interface não trava durante processamento
- [ ] Cancelamento funciona
- [ ] Erros são tratados graciosamente
- [ ] Logs são gerados
- [ ] Performance está dentro das metas

---

## 10. Troubleshooting Comum

### Problema: "Tesseract not found"
**Solução:** Configure `TESSERACT_CMD` no `.env`

### Problema: "No module named 'fitz'"
**Solução:** `pip install PyMuPDF`

### Problema: Excel não abre
**Solução:** Verifique se `openpyxl` está instalado

### Problema: UI não abre
**Solução:** 
```bash
pip install --upgrade flet
python src/main.py
```

### Problema: Extração retorna campos vazios
**Solução:** 
- Verifique o formato do PDF
- Ative `LOG_LEVEL=DEBUG` para ver detalhes
- Ajuste os padrões regex em `extractor_text.py`

---

## 11. Próximos Passos Após Testes

1. **Documentar resultados** dos testes
2. **Ajustar configurações** baseado nos resultados
3. **Refinar regex** para documentos específicos da sua organização
4. **Criar build executável**: `pyinstaller build_exe.spec`
5. **Testar executável** em máquina limpa (sem Python instalado)
