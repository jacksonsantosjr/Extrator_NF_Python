# Fiscal Document Extractor

Aplicação desktop stand-alone para extração automatizada de dados de Notas Fiscais Eletrônicas (NF-e, NFS-e) brasileiras.

## Características

- ✅ Processamento em lote de PDFs e arquivos ZIP
- ✅ Extração inteligente (texto + OCR para documentos escaneados)
- ✅ Mapeamento automático de CNPJ para Coligada/Filial
- ✅ Exportação para Excel formatado
- ✅ Interface moderna com tema claro/escuro
- ✅ Processamento concorrente (até 3 arquivos simultâneos)
- ✅ Sem necessidade de banco de dados

## Requisitos

- Python 3.11 ou superior
- Tesseract OCR instalado no sistema

### Instalação do Tesseract (Windows)

1. Baixe o instalador: https://github.com/UB-Mannheim/tesseract/wiki
2. Execute o instalador e anote o caminho de instalação
3. Configure a variável `TESSERACT_CMD` no arquivo `.env` se necessário

## Instalação

```bash
# Clone o repositório
git clone <repository-url>
cd fiscal-extractor-app

# Crie um ambiente virtual
python -m venv venv
venv\Scripts\activate  # Windows

# Instale as dependências
pip install -r requirements.txt

# Configure o ambiente
copy .env.example .env
# Edite .env conforme necessário
```

## Configuração

### Mapeamento de CNPJs

Edite o arquivo `config/filiais.json` para adicionar os CNPJs da sua organização:

```json
{
  "12.345.678/0001-90": {
    "coligada": "1",
    "filial": "01",
    "nome": "Matriz São Paulo"
  }
}
```

### Configurações Gerais

Ajuste as configurações em `config/settings.toml`:
- Limite de processamento concorrente
- Limite de páginas por PDF
- Configurações de OCR
- Preferências de exportação

## Uso

```bash
python src/main.py
```

1. Arraste arquivos PDF ou ZIP para a área de upload
2. Aguarde o processamento
3. Baixe o arquivo Excel gerado

## Estrutura do Projeto

```
fiscal-extractor-app/
├── assets/          # Recursos visuais
├── config/          # Arquivos de configuração
├── src/
│   ├── core/        # Lógica de negócio
│   ├── models/      # Modelos de dados
│   ├── ui/          # Interface gráfica
│   └── utils/       # Utilitários
├── tests/           # Testes automatizados
└── main.py          # Ponto de entrada
```

## Build para Distribuição

```bash
pyinstaller build_exe.spec
```

O executável será gerado em `dist/FiscalExtractor.exe`.

## Licença

Proprietary - Uso interno apenas
