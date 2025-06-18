import os
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Optional, Tuple

# Importazione delle classi (assicurati che siano disponibili nel percorso Python)
# from axe_analysis import AxeAnalysis
# from web_crawler import WebCrawler
from report_analysis import AccessibilityAnalyzer
from concat import concat_excel_sheets

class AccessibilityPipeline:
    """
    Pipeline che integra i risultati dell'analisi di AxeAnalysis con i dati strutturali
    di WebCrawler, utilizzando AccessibilityAnalyzer per generare report avanzati.
    """
    
    def __init__(
        self,
        output_dir: str = "./output",
        report_path: Optional[str] = None,
        charts_dir: Optional[str] = None,
        temp_dir: Optional[str] = None,
        logs_dir: Optional[str] = None,
        log_level: int = logging.INFO
    ) -> None:
        """
        Inizializza la pipeline di analisi accessibilità.
        
        Args:
            output_dir: Directory base dove salvare tutti gli output
            report_path: Percorso del report Excel finale (default: output_dir/comprehensive_report.xlsx)
            charts_dir: Directory dove salvare i grafici (default: output_dir/charts)
            temp_dir: Directory per file temporanei (default: output_dir/temp)
            logs_dir: Directory per i file di log (default: output_dir/logs)
            log_level: Livello di logging (default: INFO)
        """
        # Imposta directory di base
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        # Imposta percorsi specifici
        self.report_path = Path(report_path) if report_path else self.output_dir / "comprehensive_report.xlsx"
        self.charts_dir = Path(charts_dir) if charts_dir else self.output_dir / "charts"
        self.temp_dir = Path(temp_dir) if temp_dir else self.output_dir / "temp"
        self.logs_dir = Path(logs_dir) if logs_dir else self.output_dir / "logs"
        
        # Crea le directory necessarie
        self.charts_dir.mkdir(exist_ok=True, parents=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        self.logs_dir.mkdir(exist_ok=True, parents=True)
        
        # Configurazione logging
        self.logger = logging.getLogger("AccessibilityPipeline")
        self.logger.setLevel(log_level)
        
        if not self.logger.handlers:
            # Aggiungi handler solo se non ne esistono già
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            
            # Handler per console
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
            
            # Handler per file
            log_file = self.logs_dir / "accessibility_pipeline.log"
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Inizializza l'analizzatore di accessibilità
        self.analyzer = AccessibilityAnalyzer(log_level=log_level)
        
        self.logger.info(f"Pipeline inizializzata con le seguenti directory:")
        self.logger.info(f"- Output base: {self.output_dir}")
        self.logger.info(f"- Report path: {self.report_path}")
        self.logger.info(f"- Charts dir: {self.charts_dir}")
        self.logger.info(f"- Temp dir: {self.temp_dir}")
        self.logger.info(f"- Logs dir: {self.logs_dir}")
    
    def set_output_paths(
        self,
        report_path: Optional[str] = None,
        charts_dir: Optional[str] = None,
        temp_dir: Optional[str] = None,
        logs_dir: Optional[str] = None
    ) -> None:
        """
        Aggiorna i percorsi di output della pipeline.
        
        Args:
            report_path: Nuovo percorso per il report Excel
            charts_dir: Nuova directory per i grafici
            temp_dir: Nuova directory per i file temporanei
            logs_dir: Nuova directory per i log
        """
        if report_path:
            self.report_path = Path(report_path)
            self.logger.info(f"Report path aggiornato: {self.report_path}")
            
        if charts_dir:
            self.charts_dir = Path(charts_dir)
            self.charts_dir.mkdir(exist_ok=True, parents=True)
            self.logger.info(f"Charts directory aggiornata: {self.charts_dir}")
            
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            self.temp_dir.mkdir(exist_ok=True, parents=True)
            self.logger.info(f"Temp directory aggiornata: {self.temp_dir}")
            
        if logs_dir:
            self.logs_dir = Path(logs_dir)
            self.logs_dir.mkdir(exist_ok=True, parents=True)
            self.logger.info(f"Logs directory aggiornata: {self.logs_dir}")
    
    def run(
        self,
        axe_excel_path: str,
        crawler_pickle_path: Optional[str] = None,  # Made optional
        output_report_path: Optional[str] = None,
        charts_folder: Optional[str] = None
    ) -> Dict:
        """
        Esegue la pipeline di analisi completa.
        
        Args:
            axe_excel_path: Percorso del file Excel generato da AxeAnalysis
            crawler_pickle_path: Percorso opzionale del file pickle generato da WebCrawler
            output_report_path: Percorso dove salvare il report finale (sovrascrive self.report_path)
            charts_folder: Cartella dove salvare i grafici (sovrascrive self.charts_dir)
            
        Returns:
            Dizionario con i risultati della pipeline e i percorsi dei file generati
        """
        self.logger.info(f"Avvio pipeline con Excel: {axe_excel_path}, Pickle: {crawler_pickle_path if crawler_pickle_path else 'Non fornito'}")
        
        # Validazione input
        if not os.path.exists(axe_excel_path):
            raise FileNotFoundError(f"File Excel non trovato: {axe_excel_path}")
        
        if crawler_pickle_path and not os.path.exists(crawler_pickle_path):
            self.logger.warning(f"File pickle non trovato: {crawler_pickle_path}. L'analisi dei template sarà saltata.")
            crawler_pickle_path = None
        
        # Configura percorsi di output per questa esecuzione
        if output_report_path is None:
            output_report_path = self.report_path
        
        if charts_folder is None:
            charts_folder = self.charts_dir
        else:
            charts_folder = Path(charts_folder)
            charts_folder.mkdir(exist_ok=True, parents=True)
        
        # Step 1: Carica i dati di accessibilità dall'Excel
        self.logger.info("Caricamento dati di accessibilità da Excel...")
        axe_excel_path_concat = concat_excel_sheets(file_path=axe_excel_path, output_path=output_report_path.parent / "accessibility_report_concat.xlsx")
        axe_df_concat = self.analyzer.load_data(axe_excel_path_concat)
        self.logger.info(f"Caricati {len(axe_df_concat)} record di violazioni dall'Excel")
        
        # Step 2: Carica i dati di template dal file pickle (se fornito)
        templates_df = None
        if crawler_pickle_path:
            self.logger.info("Caricamento dati di template dal file pickle...")
            templates_df, state = self.analyzer.load_template_data(crawler_pickle_path)
            self.logger.info(f"Caricati {len(templates_df)} template dal pickle")
        else:
            self.logger.info("Nessun file pickle fornito, l'analisi dei template verrà saltata.")
        
