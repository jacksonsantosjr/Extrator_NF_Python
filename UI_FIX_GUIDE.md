# Guia de Correção de UI e Barra de Progresso

Este guia descreve as alterações necessárias para corrigir o "congelamento" da interface durante o processamento e adicionar uma barra de progresso fluida na versão CustomTkinter.

## Diagnóstico
O "congelamento" ocorre porque a interface gráfica não está recebendo sinais de vida do processador (Orchestrator). O processamento ocorre em background, mas sem reportar progresso, a tela fica estática até tudo acabar.

## Plano de Ação

Faremos 3 alterações no arquivo `src/ui/app_tkinter.py`:

1.  **Adicionar Barra de Progresso Visual:** Inserir o componente `CTkProgressBar` no rodapé.
2.  **Conectar o Callback (O "Coração"):** Ensinar o Orchestrator a enviar atualizações para a nossa fila de mensagens da UI.
3.  **Atualizar a Barra:** Ler essas mensagens e mover a barra azul.

---

### Passo 1: Adicionar Barra de Progresso
No método `_setup_ui`, dentro da área do rodapé (`footer_frame`):

```python
# Definir barra de progresso (inicialmente oculta ou zerada)
self.progress_bar = ctk.CTkProgressBar(self.footer_frame, height=15)
self.progress_bar.set(0)
self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 20))
```

### Passo 2: Injetar o Callback de Progresso
No método `_process_thread`, antes de iniciar o processamento, precisamos conectar nossa função de atualização ao Orchestrator.

```python
def _process_thread(self):
    self.update_queue.put(("status", "Iniciando..."))
    
    # 1. Definir função que o Orchestrator vai chamar a cada arquivo
    def sync_callback(update):
        # Coloca a atualização na fila para a UI ler
        self.update_queue.put(("progress", update))
    
    # 2. Conectar essa função ao Orchestrator
    self.orchestrator.progress_callback = sync_callback
    
    try:
        # 3. Rodar processamento (agora ele vai "falar" conosco)
        result = self.orchestrator.process_files(self.selected_files)
        # ... resto do código igual ...
```

### Passo 3: Atualizar a Interface
No loop de atualizações `_start_update_loop`, vamos tratar a mensagem de progresso para mover a barra:

```python
elif msg_type == "progress":
    # data é um objeto ProgressUpdate
    # Calcular porcentagem (0.0 a 1.0)
    percent = data.current_index / data.total_files
    self.progress_bar.set(percent)
    
    # Atualizar texto de status também
    # ... código existente de ícones ...
```

---
**Resultado Esperado:**
- A barra de carregamento avançará suavemente a cada arquivo processado.
- A interface não parecerá mais travada.
