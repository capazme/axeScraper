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
        crawler_pickle_path: str,
        output_report_path: Optional[str] = None,
        charts_folder: Optional[str] = None
    ) -> Dict:
        """
        Esegue la pipeline di analisi completa.
        
        Args:
            axe_excel_path: Percorso del file Excel generato da AxeAnalysis
            crawler_pickle_path: Percorso del file pickle generato da WebCrawler
            output_report_path: Percorso dove salvare il report finale (sovrascrive self.report_path)
            charts_folder: Cartella dove salvare i grafici (sovrascrive self.charts_dir)
            
        Returns:
            Dizionario con i risultati della pipeline e i percorsi dei file generati
        """
        self.logger.info(f"Avvio pipeline con Excel: {axe_excel_path}, Pickle: {crawler_pickle_path}")
        
        # Validazione input
        if not os.path.exists(axe_excel_path):
            raise FileNotFoundError(f"File Excel non trovato: {axe_excel_path}")
        
        if not os.path.exists(crawler_pickle_path):
            raise FileNotFoundError(f"File pickle non trovato: {crawler_pickle_path}")
        
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
        
        # Step 2: Carica i dati di template dal file pickle
        self.logger.info("Caricamento dati di template dal file pickle...")
        templates_df, state = self.analyzer.load_template_data(crawler_pickle_path)
        self.logger.info(f"Caricati {len(templates_df)} template dal pickle")
        
        # Step 3: Analyzes the templates with the accessibility data
        self.logger.info("Analisi dei template con i dati di accessibilità...")
        template_analysis = self.analyzer.analyze_templates(templates_df, axe_df_concat)
        self.logger.info(f"Completata analisi di template su {len(template_analysis)} template")
        
        # Step 4: Calculate metrics
        self.logger.info("Calcolo metriche di accessibilità...")
        metrics = self.analyzer.calculate_metrics(axe_df_concat)
        
        # Step 5: Create aggregations
        self.logger.info("Creazione aggregazioni...")
        aggregations = self.analyzer.create_aggregations(axe_df_concat)
        
        # Step 6: Create charts
        self.logger.info("Generazione grafici...")
        chart_files = self.analyzer.create_charts(metrics, aggregations, charts_folder)
        
        # Step 7: Generate comprehensive report
        self.logger.info(f"Generazione report completo in {output_report_path}...")
        self.analyzer.generate_report(
            axe_df=axe_df_concat,
            metrics=metrics,
            aggregations=aggregations,
            chart_files=chart_files,
            template_df=template_analysis,
            output_excel=output_report_path
        )
        
        self.logger.info("Pipeline completata con successo!")
        
        # Ritorna i risultati e i percorsi dei file generati
        return {
            "metrics": metrics,
            "aggregations": aggregations,
            "template_analysis": template_analysis,
            "output_report": str(output_report_path),
            "charts": chart_files
        }
    
    def analyze_from_crawl_and_scan(
        self,
        crawler_instance,  # WebCrawler instance
        axe_instance,      # AxeAnalysis instance
        output_report_path: Optional[str] = None,
        charts_folder: Optional[str] = None,
        perform_crawl: bool = False,
        perform_scan: bool = False,
        custom_crawler_state_path: Optional[str] = None,
        custom_axe_excel_path: Optional[str] = None
    ) -> Dict:
        """
        Esegue l'intera pipeline partendo dalle istanze di WebCrawler e AxeAnalysis.
        Opzionalmente esegue anche il crawling e la scansione prima dell'analisi.
        
        Args:
            crawler_instance: Istanza configurata di WebCrawler
            axe_instance: Istanza configurata di AxeAnalysis
            output_report_path: Percorso dove salvare il report finale (sovrascrive self.report_path)
            charts_folder: Cartella dove salvare i grafici (sovrascrive self.charts_dir)
            perform_crawl: Se True, esegue il crawling prima dell'analisi
            perform_scan: Se True, esegue la scansione prima dell'analisi
            custom_crawler_state_path: Percorso personalizzato per il file di stato del crawler
            custom_axe_excel_path: Percorso personalizzato per il file Excel di Axe
            
        Returns:
            Dizionario con i risultati della pipeline e i percorsi dei file generati
        """
        # Directory temporanea per i file intermedi
        temp_dir = self.temp_dir
        
        # Configura percorsi di output
        pickle_path = custom_crawler_state_path or crawler_instance.state_file
        excel_path = custom_axe_excel_path or axe_instance.excel_filename
        
        # Se sono forniti percorsi personalizzati, aggiorna le istanze
        if custom_crawler_state_path:
            crawler_instance.state_file = custom_crawler_state_path
            
        if custom_axe_excel_path:
            axe_instance.excel_filename = custom_axe_excel_path
        
        # Step 1: Esegui il crawling (opzionale)
        if perform_crawl:
            self.logger.info("Esecuzione del crawling web...")
            # Usa asyncio.run per eseguire il metodo asincrono
            import asyncio
            asyncio.run(crawler_instance.run())
            self.logger.info(f"Crawling completato. Stato salvato in {pickle_path}")
        
        # Step 2: Esegui la scansione di accessibilità (opzionale)
        if perform_scan:
            self.logger.info("Esecuzione della scansione di accessibilità...")
            axe_instance.start()
            self.logger.info(f"Scansione completata. Report salvato in {excel_path}")
        
        # Step 3: Esegui l'analisi completa
        return self.run(
            axe_excel_path=excel_path,
            crawler_pickle_path=pickle_path,
            output_report_path=output_report_path,
            charts_folder=charts_folder
        )
        
    def get_template_coverage_report(self, template_analysis_df: pd.DataFrame) -> pd.DataFrame:
        """
        Genera un report sulla copertura dei template analizzati.
        
        Args:
            template_analysis_df: DataFrame risultante dall'analisi dei template
            
        Returns:
            DataFrame con statistiche di copertura
        """
        if template_analysis_df.empty:
            self.logger.warning("Nessun dato di template disponibile per il report di copertura")
            return pd.DataFrame()
        
        # Calcola statistiche di copertura
        total_pages = template_analysis_df['Page Count'].sum()
        total_templates = len(template_analysis_df)
        
        # Calcola violazioni totali stimate
        total_violations = template_analysis_df['Est. Total Violations'].sum()
        critical_violations = template_analysis_df['Est. Critical'].sum()
        serious_violations = template_analysis_df['Est. Serious'].sum()
        
        # Calcola la percentuale di pagine coperte dai template principali
        top_templates = template_analysis_df.head(10)
        top_coverage = top_templates['Page Count'].sum() / total_pages * 100 if total_pages > 0 else 0
        
        # Crea il DataFrame di report
        coverage_data = {
            'Metrica': [
                'Numero totale template', 
                'Numero totale pagine', 
                'Violazioni totali stimate',
                'Violazioni critiche stimate',
                'Violazioni gravi stimate',
                'Copertura top 10 template (%)'
            ],
            'Valore': [
                total_templates,
                total_pages,
                total_violations,
                critical_violations,
                serious_violations,
                round(top_coverage, 2)
            ]
        }
        
        return pd.DataFrame(coverage_data)


# Esempio di utilizzo
if __name__ == "__main__":
    # Esempio 1: Pipeline con percorsi personalizzati all'inizializzazione
    pipeline = AccessibilityPipeline(
        output_dir="/home/ec2-user/axeScraper/output/locautorent_com/analysis_output",
        report_path="/home/ec2-user/axeScraper/output/locautorent_com/analysis_output/final_analysis_report_restricted_page.xlsx",
        charts_dir="./home/ec2-user/axeScraper/output/locautorent_com/analysis_output/charts",
        temp_dir="./temp_files",
        logs_dir="/home/ec2-user/axeScraper/output/locautorent_com/analysis_output/logs"
    )
    
    # Opzione 1: Eseguire la pipeline su file già generati
    results = pipeline.run(
        axe_excel_path="/home/ec2-user/axeScraper/output/locautorent_com_auth/analysis_output/accessibility_report_locautorent_com_auth_concat.xlsx"
    )
    
    print(f"Report generato in: {results['output_report']}")
    
    