"""
Main Flet UI application with Dashboard Layout.
"""
import flet as ft
from pathlib import Path
from typing import List, Optional, Dict
from loguru import logger
import threading
import os

from models import ProgressUpdate, ProcessingStatus, BatchProcessingResult
from core import ProcessingOrchestrator
from utils import ExcelReporter

class Colors:
    PRIMARY = "blue600"
    SECONDARY = "blue400"
    SUCCESS = "green"
    ERROR = "red"
    SURFACE = "grey900" 
    BACKGROUND = "#0f172a" 
    CARD_BG = "#1e293b"

class FileItemControl(ft.Container):
    """Custom control to display a file item in the list"""
    def __init__(self, file_path: Path, remove_callback):
        super().__init__()
        self.file_path = file_path
        self.remove_callback = remove_callback
        
        self.icon_status = ft.Icon(name="access_time", color="grey", tooltip="Pendente")
        self.text_name = ft.Text(file_path.name, weight=ft.FontWeight.BOLD)
        self.text_size = ft.Text(self._get_file_size_str(), size=12, color="grey")
        
        self.content = ft.Row(
            [
                ft.Icon(name="picture_as_pdf" if file_path.suffix.lower() == '.pdf' else "folder_zip", 
                       color=Colors.SECONDARY),
                ft.Column(
                    [
                        self.text_name,
                        self.text_size,
                    ],
                    spacing=2,
                    expand=True,
                ),
                self.icon_status,
                ft.IconButton(
                    icon="delete_outline",
                    icon_color="red400",
                    on_click=lambda e: remove_callback(self),
                    tooltip="Remover"
                )
            ],
            alignment=ft.MainAxisAlignment.START,
        )
        self.padding = 10
        self.bgcolor = Colors.CARD_BG
        self.border_radius = 8
        self.margin = ft.margin.only(bottom=5)

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
            return "Unknown size"

    def set_status(self, status: ProcessingStatus, message: str = ""):
        if status == ProcessingStatus.PENDING:
            self.icon_status.name = "access_time"
            self.icon_status.color = "grey"
        elif status == ProcessingStatus.PROCESSING:
            self.icon_status.name = "loop"
            self.icon_status.color = Colors.PRIMARY
        elif status == ProcessingStatus.COMPLETED:
            self.icon_status.name = "check_circle"
            self.icon_status.color = Colors.SUCCESS
        elif status == ProcessingStatus.ERROR or status == ProcessingStatus.CANCELLED:
            self.icon_status.name = "error_outline"
            self.icon_status.color = Colors.ERROR
        
        self.icon_status.tooltip = f"{status.value}: {message}" if message else status.value
        self.update()

class SummaryPanel(ft.Container):
    def __init__(self):
        super().__init__()
        self.total_count = ft.Text("0", size=20, weight="bold")
        self.success_count = ft.Text("0", size=20, weight="bold", color=Colors.SUCCESS)
        self.error_count = ft.Text("0", size=20, weight="bold", color=Colors.ERROR)
        
        self.content = ft.Column([
            ft.Text("Resumo do Processamento", weight="bold"),
            ft.Row([
                self._build_metric("Total", self.total_count),
                self._build_metric("Concluídos", self.success_count),
                self._build_metric("Erros", self.error_count),
            ], spacing=20)
        ])
        self.padding = 15
        self.bgcolor = Colors.CARD_BG
        self.border_radius = 8

    def _build_metric(self, label, control):
        return ft.Column([
            ft.Text(label, size=12, color="grey"),
            control
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def update_stats(self, total, success, error):
        self.total_count.value = str(total)
        self.success_count.value = str(success)
        self.error_count.value = str(error)
        self.update()

class FiscalExtractorApp:
    def __init__(self, orchestrator: ProcessingOrchestrator, excel_reporter: ExcelReporter, output_dir: Path):
        self.orchestrator = orchestrator
        self.excel_reporter = excel_reporter
        self.output_dir = output_dir
        
        self.selected_files: List[Path] = []
        self.file_controls: Dict[str, FileItemControl] = {}
        self.is_processing = False
        
        self.report_path: Optional[Path] = None

    def build(self, page: ft.Page):
        self.page = page
        page.title = "Extrator de Documentos Fiscais"
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = Colors.BACKGROUND
        page.padding = 0 
        page.window_width = 1000
        page.window_height = 800

        # --- Header ---
        self.btn_theme = ft.IconButton(
            icon="light_mode",
            on_click=self.toggle_theme,
            tooltip="Alternar Tema"
        )

        header = ft.Container(
            content=ft.Column([
                ft.Row([ft.Container(expand=True), self.btn_theme], alignment=ft.MainAxisAlignment.END),
                ft.Text("Extrator de Dados de Notas Fiscais", size=32, weight=ft.FontWeight.BOLD, color="blue200", text_align="center"),
                ft.Text("Extraia dados de NF-e e NFS-e (PDFs) com o poder da Inteligência Artificial.", color="grey", text_align="center"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(vertical=20),
            alignment=ft.alignment.center
        )

        # --- Upload Area ---
        self.upload_area = ft.Container(
            content=ft.Column([
                ft.Icon(name="cloud_upload_outlined", size=48, color=Colors.SECONDARY),
                ft.Text("Arraste e solte arquivos PDF ou ZIP aqui", size=16),
                ft.Text("ou clique para selecionar", size=12, color="grey"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
            border=ft.border.all(1, Colors.SECONDARY),
            border_radius=8,
            padding=40,
            alignment=ft.alignment.center,
            on_click=self.pick_files,
            ink=True,
            bgcolor=Colors.CARD_BG
        )

        # --- File List ---
        self.file_list_view = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        self.file_list_container = ft.Container(
            content=self.file_list_view,
            border=ft.border.all(1, "grey800"),
            border_radius=8,
            padding=10,
            expand=True,
            visible=False
        )

        # --- Action Buttons ---
        self.btn_process = ft.ElevatedButton(
            "Processar Arquivos", 
            icon="play_arrow",
            style=ft.ButtonStyle(bgcolor=Colors.PRIMARY, color="white", padding=20),
            on_click=self.start_processing,
            disabled=True
        )
        
        self.btn_download = ft.ElevatedButton(
            "Baixar Relatório (.xlsx)", 
            icon="download",
            style=ft.ButtonStyle(bgcolor=Colors.SUCCESS, color="white", padding=20),
            on_click=self.open_report,
            visible=False # Initially hidden
        )
        
        self.btn_clear = ft.ElevatedButton(
            "Limpar Todos",
            icon="delete_sweep",
            style=ft.ButtonStyle(bgcolor="red400", color="white"),
            on_click=self.clear_files
        )

        actions_row = ft.Row([self.btn_process, self.btn_download], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        
        # --- Summary Panel ---
        self.summary_panel = SummaryPanel()
        self.summary_panel.visible = False

        # --- Footer Status ---
        self.status_text = ft.Text("", size=12, color="grey")

        # Layout
        main_col = ft.Column([
            header,
            ft.Container(
                content=ft.Column([
                    self.upload_area,
                    ft.Row([ft.Text("Arquivos Carregados", size=16, weight="bold"), ft.Container(expand=True), self.btn_clear]),
                    self.file_list_container,
                    ft.Divider(color="grey800"),
                    actions_row,
                    ft.Divider(color="grey800"),
                    self.summary_panel,
                    self.status_text
                ], spacing=15, expand=True),
                padding=20,
                expand=True,
                # max_width=900 removed due to flet version compatibility
            )
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)
        
        page.add(ft.Container(main_col, alignment=ft.alignment.center, expand=True))

        # File Picker
        self.file_picker = ft.FilePicker(on_result=self.on_files_selected)
        page.overlay.append(self.file_picker)
        page.update()

    def toggle_theme(self, e):
        if self.page.theme_mode == ft.ThemeMode.DARK:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.btn_theme.icon = "dark_mode"
            self.page.bgcolor = "#f0f2f5" # Light BG
        else:
            self.page.theme_mode = ft.ThemeMode.DARK
            self.btn_theme.icon = "light_mode"
            self.page.bgcolor = Colors.BACKGROUND
        self.page.update()

    def pick_files(self, e):
        if self.is_processing: return
        self.file_picker.pick_files(allowed_extensions=["pdf", "zip"], allow_multiple=True)

    def on_files_selected(self, e: ft.FilePickerResultEvent):
        if not e.files: return
        for f in e.files:
            path = Path(f.path)
            if path not in self.selected_files:
                self.selected_files.append(path)
                item = FileItemControl(path, self.remove_file)
                self.file_controls[path.name] = item
                self.file_list_view.controls.append(item)
        self.update_ui()

    def remove_file(self, item):
        if self.is_processing: return
        try:
            self.selected_files.remove(item.file_path)
            del self.file_controls[item.file_path.name]
            self.file_list_view.controls.remove(item)
            self.update_ui()
        except ValueError:
            pass

    def clear_files(self, e):
        if self.is_processing: return
        self.selected_files.clear()
        self.file_controls.clear()
        self.file_list_view.controls.clear()
        self.btn_download.visible = False
        self.summary_panel.visible = False
        self.status_text.value = ""
        self.update_ui()

    def update_ui(self):
        has_files = len(self.selected_files) > 0
        self.file_list_container.visible = has_files
        self.btn_process.disabled = not has_files or self.is_processing
        self.upload_area.visible = not self.is_processing
        self.btn_clear.visible = has_files and not self.is_processing
        self.btn_process.text = "Processando..." if self.is_processing else "Processar Arquivos"
        self.page.update()

    def start_processing(self, e):
        if not self.selected_files: return
        self.is_processing = True
        self.report_path = None
        self.btn_download.visible = False
        self.summary_panel.visible = True
        self.summary_panel.update_stats(len(self.selected_files), 0, 0)
        self.status_text.value = "Iniciando processamento..."
        self.status_text.color = "grey"
        self.update_ui()
        
        # Reset icons
        for ctrl in self.file_controls.values():
            ctrl.set_status(ProcessingStatus.PENDING)

        import threading
        threading.Thread(target=self._process_thread, daemon=True).start()

    def _process_thread(self):
        try:
            self.orchestrator.progress_callback = self.on_progress
            result = self.orchestrator.process_files(self.selected_files)
            
            # Generate Report
            successful_docs = [res.document for res in result.results if res.status == ProcessingStatus.COMPLETED and res.document]
            
            if successful_docs:
                self.page.run_task(self._update_status_generating)
                self.report_path = self.excel_reporter.generate_report(successful_docs)
                logger.info(f"Report: {self.report_path}")

            self.page.run_task(self._on_complete, result)

        except Exception as e:
            logger.error(f"Error: {e}")
            self.page.run_task(self._on_error, str(e))

    async def _update_status_generating(self):
        self.status_text.value = "Gerando Excel..."
        self.page.update()

    def on_progress(self, update: ProgressUpdate):
        # Update specific item
        file_name = Path(update.current_file).name 
        
        async def update_async():
            if file_name in self.file_controls:
                self.file_controls[file_name].set_status(update.status, update.message)
            
        self.page.run_task(update_async)

    async def _on_complete(self, result: BatchProcessingResult):
        self.is_processing = False
        self.update_ui()
        self.status_text.value = f"Processamento finalizado em {result.total_time_seconds:.2f}s"
        
        self.summary_panel.update_stats(result.total_files, result.successful, result.failed)
        
        # Consistency check for icons
        for res in result.results:
             if res.filename in self.file_controls:
                 self.file_controls[res.filename].set_status(res.status, str(res.error.error_message) if res.error else "")

        if self.report_path:
             self.btn_download.visible = True
             self.btn_download.text = "Baixar Relatório (.xlsx)"
             self.status_text.color = "green"
        else:
             if result.failed > 0:
                self.status_text.value += " - NENHUM RELATÓRIO GERADO. Verifique erros (falta de Tesseract?)."
                self.status_text.color = "red"
        
        self.page.update()

    async def _on_error(self, err):
        self.is_processing = False
        self.status_text.value = f"Erro fatal na aplicação: {err}"
        self.status_text.color = "red"
        self.update_ui()
        self.page.update()

    def open_report(self, e):
        if self.report_path:
            os.startfile(str(self.report_path))
