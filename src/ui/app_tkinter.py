
"""
CustomTkinter UI implementation for the Fiscal Document Extractor.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, PhotoImage
from pathlib import Path
from typing import List, Dict, Optional
import threading
from loguru import logger
import queue
import io

from models import ProcessingStatus
from core import ProcessingOrchestrator
from utils import ExcelReporter

class Colors:
    PRIMARY = ("#1f538d", "#1f538d")
    SECONDARY = ("#14375e", "#14375e")
    SUCCESS = ("#2ea043", "#2ea043")
    ERROR = ("#da3633", "#da3633")
    CARD_BG = ("#e2e8f0", "#1e293b") # Light: Slate-200, Dark: Slate-800
    BG = ("#f8fafc", "#0f172a")      # Light: Slate-50, Dark: Slate-900

class FileItemFrame(ctk.CTkFrame):
    """Frame representing a file in the list"""
    def __init__(self, master, file_path: Path, remove_callback, **kwargs):
        # Colors: Light Mode = Medium Gray (#bdbdbd), Dark Mode = Dark Gray (#374151)
        # User requested to match the header "Arquivos Carregados" tone (darker gray).
        super().__init__(master, fg_color=("#bdbdbd", "#374151"), corner_radius=8, **kwargs)
        self.file_path = file_path
        self.remove_callback = remove_callback

        # Icon
        # Text Color: Black (Light Mode), White (Dark Mode)
        self.lbl_icon = ctk.CTkLabel(self, text="📄" if file_path.suffix.lower() == '.pdf' else "📁", font=("Arial", 20), text_color=("black", "white"))
        self.lbl_icon.pack(side="left", padx=10, pady=10)

        # File Info
        self.info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.info_frame.pack(side="left", fill="x", expand=True, padx=5)

        self.lbl_name = ctk.CTkLabel(self.info_frame, text=file_path.name, font=("Segoe UI", 12, "bold"), anchor="w", text_color=("black", "white"))
        self.lbl_name.pack(fill="x")

        self.lbl_size = ctk.CTkLabel(self.info_frame, text=self._get_file_size_str(), font=("Segoe UI", 10), text_color=("gray", "silver"), anchor="w")
        self.lbl_size.pack(fill="x")

        # Status
        # Status color: Gray/Silver split
        self.lbl_status = ctk.CTkLabel(self, text="🕒", font=("Segoe UI", 16), text_color=("gray", "silver"))
        self.lbl_status.pack(side="left", padx=10)

        # Delete Button
        # Keep ERROR color (usually red) which works on both
        self.btn_delete = ctk.CTkButton(self, text="❌", width=30, height=30, fg_color="transparent", hover_color="#330000",
                                        command=lambda: remove_callback(self), text_color=Colors.ERROR)
        self.btn_delete.pack(side="right", padx=10)

    def _get_file_size_str(self):
        try:
            size_bytes = self.file_path.stat().st_size
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            else:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
        except:
            return "Unknown"

    def set_status(self, status: ProcessingStatus, message: str = ""):
        if status == ProcessingStatus.PENDING:
            self.lbl_status.configure(text="🕒", text_color="gray")
        elif status == ProcessingStatus.PROCESSING:
            self.lbl_status.configure(text="🔄", text_color=Colors.PRIMARY)
        elif status == ProcessingStatus.COMPLETED:
            self.lbl_status.configure(text="✅", text_color=Colors.SUCCESS)
        elif status == ProcessingStatus.ERROR or status == ProcessingStatus.CANCELLED:
            self.lbl_status.configure(text="⚠️", text_color=Colors.ERROR)
            
class FiscalExtractorAppTk(ctk.CTk):
    def __init__(self, orchestrator: ProcessingOrchestrator, excel_reporter: ExcelReporter, output_dir: Path, icon_path: Optional[Path] = None):
        super().__init__()
        self.orchestrator = orchestrator
        self.excel_reporter = excel_reporter
        self.output_dir = output_dir

        # Setup Window
        self.title("Extrator de Documentos Fiscais")
        # Center the window
        self._center_window(1000, 800)
        
        # Schedule icon update to ensure it applies after window is mapped
        if icon_path:
            self.after(200, lambda: self._set_icon(icon_path))

        ctk.set_appearance_mode("light") # Default Light Mode

    def _set_icon(self, icon_path: Path):
        """Helper to set window icon safely"""
        try:
            if icon_path.exists():
                logger.info(f"Setting icon from: {icon_path}")
                self._icon_img = PhotoImage(file=str(icon_path))
                self.iconphoto(False, self._icon_img)
                # Keep reference to avoid GC
                self.after(100, lambda: self.wm_iconphoto(False, self._icon_img))
            else:
                logger.warning(f"Icon file not found: {icon_path}")
        except Exception as e:
            logger.error(f"Error setting icon: {e}")
        ctk.set_default_color_theme("blue")
        
        self.selected_files: List[Path] = []
        self.file_frames: Dict[str, FileItemFrame] = {}
        
        # Queue for thread-safe UI updates
        self.update_queue = queue.Queue()
        
        # Processing state flag
        self.is_processing = False
        
        self._setup_ui()
        self._start_update_loop()

    def _center_window(self, width: int, height: int):
        """Centers the window on the screen."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        # Shift up slightly (50px) to avoid taskbar overlap and look better
        y = y - 50
        
        y = max(0, y)
        
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_ui(self):
        # Grid Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Header
        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=20)
        self.header_frame.grid_columnconfigure(0, weight=1) # Center content

        # Theme Switch
        # Using Icon-like button (Unicode)
        self.btn_theme = ctk.CTkButton(self.header_frame, text="🌙", width=40, height=40, 
                                       fg_color="transparent", hover_color=("#e5e7eb", "#374151"),
                                       text_color=("#374151", "#FDB813"), # Dark Gray for Moon (Light Mode), Amber for Sun (Dark Mode)
                                       font=("Segoe UI", 20),
                                       command=self.toggle_theme)
        self.btn_theme.grid(row=0, column=0, sticky="e", padx=30)
 
        # Title
        ctk.CTkLabel(self.header_frame, text="Extrator de Dados de Notas Fiscais", font=("Segoe UI", 26, "bold"), text_color=("#1f2937", "#93c5fd")).grid(row=1, column=0)
        ctk.CTkLabel(self.header_frame, text="Extração de dados de NF-e e NFS-e (PDFs)", font=("Segoe UI", 14), text_color="gray").grid(row=2, column=0)

        # 2. Main Content
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=30, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)
        # self.main_frame.grid_rowconfigure(3, weight=1) # REMOVED expansion to respect fixed height

        # Upload Area
        self.upload_btn = ctk.CTkButton(self.main_frame, text="+ Adicionar Arquivos PDF/ZIP", 
                                        height=50, corner_radius=8, font=("Segoe UI", 14, "bold"),
                                        command=self.pick_files)
        self.upload_btn.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        # Progress Bar (Moved to Main Frame below Upload Button)
        # Initially hidden, shown only on start_processing
        self.progress_bar = ctk.CTkProgressBar(self.main_frame, height=15)
        self.progress_bar.set(0)
        
        self.lbl_progress_percent = ctk.CTkLabel(self.main_frame, text="0%", font=("Segoe UI", 12, "bold"))

        # Stats / Actions Row (Shifted to Row 2)
        # Increased pady to (20, 20) to push Arquivos/Limpar down from Upload/Progress
        self.actions_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.actions_frame.grid(row=2, column=0, sticky="ew", pady=(20, 20))
        
        # Left side container for labels
        self.left_stats_frame = ctk.CTkFrame(self.actions_frame, fg_color="transparent")
        self.left_stats_frame.pack(side="left")
        
        self.lbl_count = ctk.CTkLabel(self.left_stats_frame, text="Arquivos: 0", font=("Segoe UI", 12, "bold"))
        self.lbl_count.pack(anchor="w")
        
        # Processing status label (e.g., "Processando arquivo X de Y")
        # Same style as lbl_count
        self.lbl_processing_status = ctk.CTkLabel(self.left_stats_frame, text="", 
                                                   font=("Segoe UI", 12, "bold"))
        # Initially hidden, will be shown during processing

        self.btn_clear = ctk.CTkButton(self.actions_frame, text="Limpar", width=80, fg_color=Colors.ERROR, hover_color="#991b1b", 
                                       command=self.clear_files, font=("Segoe UI", 13, "bold"))
        self.btn_clear.pack(side="right")
        
        # Track maximum progress to prevent regression
        self.max_progress_value = 0.0

        # File List (Scrollable) (Shifted to Row 3)
        # Fixed height to limit visibility to ~5 items (approx 250px)
        # File List (Scrollable) (Shifted to Row 3)
        # Fixed height increased to 320 to limit visibility to ~5 items
        self.scroll_frame = ctk.CTkScrollableFrame(self.main_frame, label_text="Arquivos Carregados", label_font=("Segoe UI", 14, "bold"), height=320)
        self.scroll_frame.grid(row=3, column=0, sticky="ew", pady=(20, 10))

        # Footer Actions
        self.footer_frame = ctk.CTkFrame(self, corner_radius=0, height=80, fg_color=Colors.CARD_BG)
        self.footer_frame.grid(row=2, column=0, sticky="ew")
        self.footer_frame.grid_columnconfigure(1, weight=1)

        self.btn_process = ctk.CTkButton(self.footer_frame, text="PROCESSAR ARQUIVOS", height=40, width=200, 
                                         font=("Segoe UI", 13, "bold"), command=self.start_processing, state="disabled")
        self.btn_process.grid(row=0, column=0, padx=20, pady=20)

        # Summary Stats
        self.stats_label = ctk.CTkLabel(self.footer_frame, text="Total: 0 | Sucesso: 0 | Erros: 0", font=("Segoe UI", 14))
        self.stats_label.grid(row=0, column=1)

        self.btn_download = ctk.CTkButton(self.footer_frame, text="BAIXAR RELATÓRIO", height=40, width=200,
                                          fg_color=Colors.SUCCESS, hover_color="#15803d",
                                          font=("Segoe UI", 13, "bold"), # Matched Font
                                          command=self.open_report, state="disabled")
        self.btn_download.grid(row=0, column=2, padx=20, pady=20)
        
        # AI Toggle (User Request)
        self.ai_var = ctk.BooleanVar(value=self.orchestrator.extractor.llm_enabled)
        self.chk_ai = ctk.CTkCheckBox(self.footer_frame, text="Habilitar Correção com IA", 
                                      variable=self.ai_var, command=self._toggle_ai,
                                      font=("Segoe UI", 12))
        self.chk_ai.grid(row=0, column=3, padx=20)



    def pick_files(self):
        filetypes = (("PDF Files", "*.pdf"), ("ZIP Files", "*.zip"), ("All Files", "*.*"))
        paths = filedialog.askopenfilenames(title="Selecione os arquivos", filetypes=filetypes)
        
        for p in paths:
            path_obj = Path(p)
            if path_obj not in self.selected_files:
                self.selected_files.append(path_obj)
                self._add_file_item(path_obj)
        
        self._update_ui_state()

    def _add_file_item(self, path: Path):
        item = FileItemFrame(self.scroll_frame, path, self.remove_file)
        item.pack(fill="x", pady=2, padx=5)
        self.file_frames[str(path)] = item

    def remove_file(self, item_frame):
        path = item_frame.file_path
        if path in self.selected_files:
            self.selected_files.remove(path)
        
        item_frame.destroy()
        del self.file_frames[str(path)]
        self._update_ui_state()

    def clear_files(self):
        """Clear files OR cancel processing if running"""
        if self.is_processing:
            # Cancel mode
            self.orchestrator.cancel()
            self.lbl_processing_status.configure(text=" Cancelando... ")
            self.btn_clear.configure(state="disabled")  # Prevent multiple clicks
            return
        
        # Normal clear mode
        for frame in self.file_frames.values():
            frame.destroy()
        self.file_frames.clear()
        self.selected_files.clear()
        self.progress_bar.set(0) # Reset progress
        self.lbl_progress_percent.configure(text="0%")
        
        # Hide progress bar and percentage (will reappear on next processing)
        self.progress_bar.grid_remove()
        self.lbl_progress_percent.grid_remove()
        
        self.stats_label.configure(text="Total: 0 | Sucesso: 0 | Erros: 0")
        self._update_ui_state()

    def _update_ui_state(self):
        count = len(self.selected_files)
        self.lbl_count.configure(text=f"Arquivos: {count}")
        
        if count > 0:
            self.btn_process.configure(state="normal")
        else:
            self.btn_process.configure(state="disabled")

            self.btn_process.configure(state="disabled")

    def _toggle_ai(self):
        """Toggle AI/LLM usage in extractor"""
        enabled = self.ai_var.get()
        self.orchestrator.extractor.llm_enabled = enabled
        model = self.orchestrator.extractor.vision_extractor.model_name if self.orchestrator.extractor.vision_extractor else "N/A"
        logger.info(f"AI Vision enabled: {enabled} (Model: {model})")

    def _animate_progress(self, target_value: float):
        """Animate progress bar incrementally (never goes backwards)"""
        # Ensure progress never goes backwards (monotonic increase)
        if target_value < self.max_progress_value:
            target_value = self.max_progress_value
        else:
            self.max_progress_value = target_value
        
        current_value = self.progress_bar.get()
        
        # If target reached, stop
        if current_value >= target_value:
            return
        
        # Calculate step (e.g., 1% of the distance or fixed 0.01)
        step = 0.01
        new_value = min(target_value, current_value + step)
        
        self.progress_bar.set(new_value)
        self.lbl_progress_percent.configure(text=f"{int(new_value * 100)}%")
        
        # Schedule next update if not reached
        if new_value < target_value:
            self.after(10, lambda: self._animate_progress(target_value))

    def start_processing(self):
        if not self.selected_files: return
        
        self.btn_process.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.btn_clear.configure(state="disabled")
        self.btn_download.configure(state="disabled")
        self.btn_download.configure(state="disabled")
        
        # Ensure progress bar and label are visible
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 20), padx=(0, 40))
        self.lbl_progress_percent.grid(row=1, column=0, sticky="e", pady=(0, 20))
        self.progress_bar.set(0)
        self.lbl_progress_percent.configure(text="0%")
        self.max_progress_value = 0.0  # Reset max progress tracker
        
        # Show processing status label
        self.lbl_processing_status.pack(anchor="w", pady=(2, 0))
        self.lbl_processing_status.configure(text="Iniciando...")
        
        # Set processing state and transform Limpar -> Cancelar
        self.is_processing = True
        self.btn_clear.configure(text="Cancelar", state="normal")  # Enable for cancellation
        
        # Reset icons
        for frame in self.file_frames.values():
            frame.set_status(ProcessingStatus.PENDING)

        threading.Thread(target=self._process_thread, daemon=True).start()

    def _process_thread(self):
        self.update_queue.put(("status", "Iniciando processamento..."))
        
        # Synchronous callback bridge
        def sync_callback(update):
            self.update_queue.put(("progress", update))

        # Inject callback into orchestrator
        self.orchestrator.progress_callback = sync_callback
        
        try:
            result = self.orchestrator.process_files(self.selected_files)
            
            # Generate Report
            successful_docs = [r.document for r in result.results if r.status == ProcessingStatus.COMPLETED and r.document]
            
            report_path = None
            if successful_docs:
                report_path = self.excel_reporter.generate_report(successful_docs)
            
            self.update_queue.put(("done", (result, report_path)))
            
        except Exception as e:
            self.update_queue.put(("error", str(e)))

    def _start_update_loop(self):
        """Poll the queue for updates from the thread"""
        try:
            while True:
                msg_type, data = self.update_queue.get_nowait()
                
                if msg_type == "status":
                    pass # maybe show toast
                elif msg_type == "progress":
                    # Update progress bar
                    if data.total_files > 0:
                        target_progress = data.current_index / data.total_files
                        # Use animation instead of jump
                        self._animate_progress(target_progress)
                        
                        # Update "Processando arquivo X de Y" label
                        self.lbl_processing_status.configure(
                            text=f"Processando arquivo {data.current_index} de {data.total_files}"
                        )
                    
                    # Update specific item status (Corrigido para buscar pelo nome)
                    target_name = data.current_file
                    for frame_path_str, frame in self.file_frames.items():
                        # Compara apenas o nome do arquivo (ex: 'nota.pdf') com o alvo
                        if Path(frame_path_str).name == target_name:
                            frame.set_status(data.status, data.message)
                            break


                elif msg_type == "done":
                    result, report_path = data
                    self._on_processing_complete(result, report_path)
                
                elif msg_type == "error":
                    messagebox.showerror("Erro", str(data))
                    # Reset processing state on error
                    self.is_processing = False
                    self.btn_clear.configure(text="Limpar", state="normal")
                    self._reset_ui()

        except queue.Empty:
            pass
        
        self.after(100, self._start_update_loop)

    def _on_processing_complete(self, result, report_path):
        self.max_progress_value = 1.0  # Allow animation to 100%
        self._animate_progress(1.0) # Force animation to full 100%
        
        # Reset processing state and restore Cancelar -> Limpar
        self.is_processing = False
        self.btn_clear.configure(text="Limpar", state="normal")
        
        # Hide processing status label
        self.lbl_processing_status.pack_forget()
        
        # Update summary
        self.stats_label.configure(text=f"Total: {result.total_files} | Sucesso: {result.successful} | Erros: {result.failed}")
        
        # Update individual icons final state
        for res in result.results:
            # Again, res.filename is likely just the name if using original Orchestrator logic.
            # But let's check ProcessingResult.filename.
            # It comes from _process_single_file -> filename arg.
            
            target_name = res.filename
            for frame_path_str, frame in self.file_frames.items():
                # We match by name because Orchestrator only tracks name currently (for ZIPs essentially)
                if Path(frame_path_str).name == target_name:
                    frame.set_status(res.status)
                    break

        # Check if processing was cancelled
        if self.orchestrator.is_cancelled():
            messagebox.showwarning("Cancelado", "Processamento cancelado!")
        elif report_path:
            self.report_path = report_path
            self.btn_download.configure(state="normal")
            messagebox.showinfo("Sucesso", f"Processamento concluído!\nRelatório gerado.")
        else:
            messagebox.showwarning("Aviso", "Nenhum arquivo processado com sucesso.")

        self._reset_ui()

        # Hide progress on reset if desired, or keep it 100%?
        # User said "appear only after clicking process".
        # So we should hide it on reset?
        # reset_ui is called after done.
        
    def _reset_ui(self):
        # Hide progress?
        # self.progress_bar.grid_remove()
        # self.lbl_progress_percent.grid_remove()
        # Maybe keep it visible until "Clear" or next upload? 
        # Typically "Limit appearance" implies dynamic showing.
        pass

        self.btn_process.configure(state="normal")
        self.upload_btn.configure(state="normal")
        self.btn_clear.configure(state="normal")

    def toggle_theme(self):
        current_mode = ctk.get_appearance_mode()
        if current_mode == "Light":
            ctk.set_appearance_mode("Dark")
            self.btn_theme.configure(text="☀️") # Sun icon to go back to Light
        else:
            ctk.set_appearance_mode("Light")
            self.btn_theme.configure(text="🌙") # Moon icon to go back to Dark

    def open_report(self):
        if not self.report_path:
            return
        # Sugere o mesmo nome do arquivo gerado
        initial_file = os.path.basename(self.report_path)
        
        # Abre diálogo para Salvar Como
        dest_path = filedialog.asksaveasfilename(
            title="Salvar Relatório Como",
            initialfile=initial_file,
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx")]
        )
    
        if dest_path:
            try:
                import shutil
                shutil.copy2(self.report_path, dest_path)
                messagebox.showinfo("Sucesso", f"Relatório salvo em:\n{dest_path}")
            
                # Opcional: Perguntar se quer abrir
                if messagebox.askyesno("Abrir", "Deseja abrir o relatório agora?"):
                    os.startfile(dest_path)
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao salvar arquivo:\n{str(e)}")
        
import os
