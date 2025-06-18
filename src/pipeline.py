#!/usr/bin/env python3
"""
Pipeline di accessibilità completa e robusta.

Questo script orchestra le tre fasi principali:
1. Crawling: raccolta degli URL
2. Axe Analysis: analisi di accessibilità
3. Report Analysis: generazione dei report finali

Utilizza i gestori centralizzati per:
- Configurazione: ConfigurationManager
- Logging: tramite get_logger
- Output: OutputManager
"""

import asyncio
import os
import signal
import time
import psutil
import subprocess
from typing import Dict, Any, List, Optional, Set, Tuple, Union
from pathlib import Path
import traceback
import pandas as pd
import re
import shutil
from datetime import datetime

# Import delle classi centrali di gestione
from utils.config_manager import ConfigurationManager
from utils.logging_config import get_logger
from utils.output_manager import OutputManager
from utils.auth_manager import AuthenticationManager
from utils.funnel_manager import FunnelManager
from utils.config import OUTPUT_ROOT

# Import dei componenti principali
from axcel.axcel import AxeAnalysis
from analysis.report_analysis import AccessibilityAnalyzer
from utils.send_mail import send_email_report

# Stato globale
running_processes = {}
output_managers = {}
shutdown_flag = False
start_time = time.time()

class Pipeline:
    """
    Orchestratore completo del pipeline di accessibilità che gestisce:
    - Configurazione centralizzata 
    - Logging strutturato
    - Gestione dell'output
    - Gestione delle risorse
    - Gestione dei segnali di interruzione
    """
    
    def __init__(self, config_file: Optional[str] = None, cli_args: Optional[Dict[str, Any]] = None):
        """
        Inizializza il pipeline con la configurazione globale.
        
        Args:
            config_file: Percorso del file di configurazione (opzionale)
            cli_args: Argomenti da linea di comando (opzionale)
        """
        # Inizializza il gestore di configurazione con il nuovo schema
        self.config_manager = ConfigurationManager(
            project_name="axeScraper",
            config_file=config_file,
            cli_args=cli_args or {}
        )
        
        # Attiva la modalità debug se richiesto
        if self.config_manager.get_bool("DEBUG", False):
            self.config_manager.set_debug_mode(True)
        
        # Configura il logger con output manager
        self.logger = get_logger(
            "pipeline", 
            self.config_manager.get_logging_config()["components"]["pipeline"]
        )
        
        # Mostra riepilogo configurazione all'avvio
        self.config_manager.log_config_summary()
        
        # Informazioni sul sistema
        self.logger.info(f"Risorse sistema: {os.cpu_count()} CPU, "
                        f"{psutil.virtual_memory().total / (1024**3):.1f}GB RAM totale")
        
        # Registra handlers per interruzioni
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        # Stato interno
        self.running_processes = {}
        self.output_managers = {}
        self.shutdown_flag = False
        self.start_time = time.time()
        
        # Carica pipeline config
        self.pipeline_config = self.config_manager.get_pipeline_config()
        
        # Log dei parametri chiave (usando le chiavi standardizzate)
        self.logger.info("Parametri chiave di configurazione:")
        self.logger.info(f"CRAWLER_MAX_URLS: {self.config_manager.get_int('CRAWLER_MAX_URLS')}")
        self.logger.info(f"CRAWLER_HYBRID_MODE: {self.config_manager.get_bool('CRAWLER_HYBRID_MODE')}")
        self.logger.info(f"CRAWLER_PENDING_THRESHOLD: {self.config_manager.get_int('CRAWLER_PENDING_THRESHOLD')}")
        self.logger.info(f"AXE_MAX_TEMPLATES: {self.config_manager.get_int('AXE_MAX_TEMPLATES')}")
        self.logger.info(f"START_STAGE: {self.config_manager.get('START_STAGE')}")
        self.logger.info(f"REPEAT_ANALYSIS: {self.config_manager.get_int('REPEAT_ANALYSIS')}")
        
        # Initialize auth and funnel managers
        self.auth_manager = None
        self.funnel_manager = None

        # Inizializza un OutputManager generico per l'analyzer
        base_dir = self.config_manager.get('OUTPUT_BASE_DIR', 'output')
        domain = self.config_manager.get('DOMAIN', 'generic')
        generic_output_manager = OutputManager(base_dir=OUTPUT_ROOT, domain=domain)
        self.analyzer = AccessibilityAnalyzer(output_manager=generic_output_manager)

        # Centralizza e ordina la gestione del logging e dell'output
        self.logger.info("=== INIZIO PIPELINE DI ACCESSIBILITÀ ===")
        self.logger.info(f"Output base: {base_dir}")
        self.logger.info(f"Dominio: {domain}")
        self.logger.info(f"OutputManager base_dir: {generic_output_manager.base_dir}")
        self.logger.info(f"OutputManager domain_slug: {generic_output_manager.domain_slug}")
        self.logger.info(f"Percorsi OutputManager: {getattr(generic_output_manager, 'paths', {})}")
        
        self.logger.info("Pipeline __init__ completato.")
            
        # Archiviazione run precedente
        self._archive_previous_run()
            
    def _archive_previous_run(self):
        """Se esiste una cartella di output corrente, la sposta in output/runs/<timestamp>/"""
        try:
            # Determina la cartella base di output e la slug del dominio
            base_dir = OUTPUT_ROOT
            domain = self.config_manager.get('DOMAIN_SLUG', 'generic')
            domain_slug = re.sub(r'[^\w\-]+', '_', domain.lower())
            current_output_dir = Path(base_dir) / domain_slug
            runs_dir = Path(base_dir) / 'runs'
            runs_dir.mkdir(parents=True, exist_ok=True)
            if current_output_dir.exists() and any(current_output_dir.iterdir()):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                archive_dir = runs_dir / f'{domain_slug}_{timestamp}'
                shutil.move(str(current_output_dir), str(archive_dir))
                self.logger.info(f"Output precedente archiviato in: {archive_dir}")
            else:
                self.logger.info(f"Nessun output precedente da archiviare in {current_output_dir}")
        except Exception as e:
            self.logger.warning(f"Errore durante l'archiviazione della run precedente: {e}")

    def _handle_shutdown(self, signum, _):
        """Gestisce i segnali di interruzione con pulizia ordinata."""
        self.shutdown_flag = True
        self.logger.warning(f"Ricevuto segnale di interruzione ({signum}). Avvio chiusura controllata...")
        
        # Termina i processi di crawling
        for url, process in self.running_processes.items():
            if process and process.poll() is None:
                self.logger.info(f"Terminazione processo crawler per {url}")
                try:
                    process.terminate()
                    # Attendi fino a 30 secondi per terminazione
                    for _ in range(30):
                        if process.poll() is not None:
                            break
                        time.sleep(1)
                    # Forza la chiusura se ancora in esecuzione
                    if process.poll() is None:
                        process.kill()
                except Exception as e:
                    self.logger.error(f"Errore terminando processo: {e}")
    
    async def monitor_resources(self):
        """
        Monitora le risorse di sistema e mette in pausa l'esecuzione
        se le soglie CPU/memoria vengono superate.
        """
        # Ottieni configurazione monitoraggio risorse
        resource_config = self.pipeline_config.get("resource_monitoring", {})
        
        threshold_cpu = resource_config.get("threshold_cpu", 90)
        threshold_memory = resource_config.get("threshold_memory", 85)
        check_interval = resource_config.get("check_interval", 3)
        cool_down_time = resource_config.get("cool_down_time", 7)
        
        if not resource_config.get("enabled", True):
            self.logger.info("Monitoraggio risorse disabilitato da configurazione")
            return
            
        try:
            while not self.shutdown_flag:
                try:
                    cpu = psutil.cpu_percent(interval=0.5)
                    mem = psutil.virtual_memory().percent
                    
                    # Log metriche periodicamente
                    if (time.time() - self.start_time) % 60 < 3:
                        elapsed = time.time() - self.start_time
                        if elapsed > 0:
                            self.logger.info(f"Performance: CPU={cpu:.1f}%, Memoria={mem:.1f}%, "
                                          f"Uptime={elapsed/60:.1f} minuti")
                    
                    # Pausa se risorse limitate
                    if cpu > threshold_cpu or mem > threshold_memory:
                        self.logger.warning(f"Utilizzo risorse elevato: CPU={cpu:.1f}%, Memoria={mem:.1f}%. "
                                         f"Pausa di {cool_down_time} secondi...")
                        
                        # Esegui garbage collection
                        if mem > threshold_memory:
                            self.logger.info("Esecuzione garbage collection...")
                            import gc
                            gc.collect()
                            
                        await asyncio.sleep(cool_down_time)
                    else:
                        await asyncio.sleep(check_interval)
                except Exception as e:
                    self.logger.error(f"Errore nel monitor risorse: {e}")
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.logger.info("Monitor risorse terminato")
            raise
    
    async def run_crawler(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> bool:
        """
        Esegue il componente di crawling con gestione standardizzata dei percorsi ed errori migliorata.
        
        Args:
            base_url: URL di partenza
            domain_config: Configurazione specifica del dominio
            output_manager: Gestore dell'output
            
        Returns:
            True se il crawling è completato con successo
        """
        self.logger.info(f"Avvio crawler per {base_url}")
        
        # Ottieni configurazione crawler
        crawler_config = domain_config.get("crawler_config", {})
        
        # Ottieni percorsi standardizzati da output_manager
        output_dir = str(output_manager.get_path("crawler"))
        state_file = str(output_manager.get_crawler_state_path())
        log_file = str(output_manager.get_timestamped_path(
            "logs", f"crawler_{output_manager.domain_slug}", "log"))
        
        # Log percorsi per debug
        self.logger.info(f"Directory output crawler: {output_dir}")
        self.logger.info(f"File stato crawler: {state_file}")
        self.logger.info(f"File log crawler: {log_file}")
        
        # Assicura che le directory esistano
        output_manager.ensure_path_exists("crawler")
        output_manager.ensure_path_exists("logs")
        
        try:
            # Prepara il dominio correttamente
            # Estrai il dominio base senza path
            clean_domain = output_manager.domain.replace("http://", "").replace("https://", "").replace("www.", "")
            clean_domain = clean_domain.split('/')[0]
            
            # Ottieni i valori configurazione dalle chiavi standardizzate
            max_urls = crawler_config.get('max_urls', self.config_manager.get_int("CRAWLER_MAX_URLS", 100))
            hybrid_mode = crawler_config.get('hybrid_mode', self.config_manager.get_bool("CRAWLER_HYBRID_MODE", True))
            request_delay = crawler_config.get('request_delay', self.config_manager.get_float("CRAWLER_REQUEST_DELAY", 0.25))
            selenium_threshold = crawler_config.get('pending_threshold', self.config_manager.get_int("CRAWLER_PENDING_THRESHOLD", 30))
            max_workers = crawler_config.get('max_workers', self.config_manager.get_int("CRAWLER_MAX_WORKERS", 16))
            
            # Log configurazione con chiavi standardizzate
            self.logger.info(f"Configurazione crawler:")
            self.logger.info(f"Domain: {clean_domain}")
            self.logger.info(f"CRAWLER_MAX_URLS: {max_urls}")
            self.logger.info(f"CRAWLER_HYBRID_MODE: {hybrid_mode}")
            self.logger.info(f"CRAWLER_REQUEST_DELAY: {request_delay}")
            self.logger.info(f"CRAWLER_PENDING_THRESHOLD: {selenium_threshold}")
            self.logger.info(f"CRAWLER_MAX_WORKERS: {max_workers}")
            
            # Verifica se il processo esiste già
            if base_url in self.running_processes and self.running_processes[base_url] and self.running_processes[base_url].poll() is None:
                self.logger.warning(f"Processo crawler per {base_url} già in esecuzione")
                return False
                
            # Trova il percorso al modulo multi_domain_crawler
            crawler_paths = [
                os.path.abspath(os.path.join(os.path.dirname(__file__), "multi_domain_crawler")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/multi_domain_crawler")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../multi_domain_crawler"))
            ]
            
            cwd = None
            for path in crawler_paths:
                if os.path.exists(path):
                    cwd = path
                    break
                    
            if not cwd:
                self.logger.error("Impossibile trovare directory multi_domain_crawler")
                return False
                
            self.logger.info(f"Directory crawler: {cwd}")
                
            # Configura il comando con i parametri standardizzati
            cmd = [
                "python", "-m", "scrapy", "crawl", "multi_domain_spider",
                "-a", f"domains={clean_domain}",
                "-a", f"max_urls_per_domain={max_urls}",  # Usa il valore standardizzato
                "-a", f"hybrid_mode={'True' if hybrid_mode else 'False'}",  # Usa il valore standardizzato
                "-a", f"request_delay={request_delay}",  # Usa il valore standardizzato
                "-a", f"selenium_threshold={selenium_threshold}",  # Usa il valore standardizzato
                "-s", f"OUTPUT_DIR={output_dir}",
                "-s", f"CONCURRENT_REQUESTS={max_workers}",  # Usa il valore standardizzato
                "-s", f"CONCURRENT_REQUESTS_PER_DOMAIN={max(8, max_workers // 2)}",
                "-s", f"LOG_LEVEL=DEBUG",
                "-s", f"PIPELINE_REPORT_FORMAT=all",
                "--logfile", f"{log_file}"
            ]
            
            # Log comando completo
            self.logger.info(f"Comando crawler: {' '.join(cmd)}")
                    
            # Esegui comando
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Verifica avvio processo
            if process.pid is None:
                self.logger.error(f"Impossibile avviare processo crawler per {base_url}")
                return False
                
            self.logger.info(f"Crawler avviato per {base_url} con PID {process.pid}")
            self.running_processes[base_url] = process
            
            # Monitora esecuzione processo
            while process.poll() is None:
                # Elabora stdout e stderr
                stdout_line = process.stdout.readline() if process.stdout else ""
                if stdout_line.strip():
                    self.logger.info(f"Crawler ({base_url}): {stdout_line.strip()}")
                
                stderr_line = process.stderr.readline() if process.stderr else ""
                if stderr_line.strip():
                    self.logger.warning(f"Crawler ({base_url}) stderr: {stderr_line.strip()}")
                
                # Verifica segnale interruzione
                if self.shutdown_flag:
                    self.logger.warning(f"Interruzione richiesta, terminazione crawler per {base_url}")
                    process.terminate()
                    return False
                
                await asyncio.sleep(0.1)
            
            # Processo completato
            return_code = process.returncode
            
            # Leggi eventuale output rimanente
            stdout, stderr = process.communicate()
            if stdout and stdout.strip():
                self.logger.info(f"Output finale crawler: {stdout.strip()}")
            if stderr and stderr.strip():
                self.logger.warning(f"Errori finali crawler: {stderr.strip()}")
            
            if return_code == 0:
                self.logger.info(f"Crawler completato con successo per {base_url}")
                return True
            else:
                self.logger.error(f"Crawler fallito con codice {return_code} per {base_url}")
                return False
                
        except Exception as e:
            self.logger.exception(f"Errore eseguendo crawler: {e}")
            return False
        finally:
            # Rimuovi processo dal tracking
            self.running_processes.pop(base_url, None)
    
    def collect_funnel_html_files(self, funnel_id: str, output_manager: OutputManager) -> List[Tuple[str, str, Path]]:
        """
        Collect HTML snapshots from funnel directories for analysis.
        
        Args:
            funnel_id: ID of the funnel
            output_manager: Output manager for path handling
            
        Returns:
            List of (step_name, step_number, file_path) tuples
        """
        funnel_directory = output_manager.get_path("funnels", funnel_id)
        self.logger.info(f"Collecting HTML files from funnel directory: {funnel_directory}")
        
        html_files = []
        
        if not funnel_directory.exists():
            self.logger.warning(f"Funnel directory not found: {funnel_directory}")
            return html_files
            
        # Find all HTML files in the directory
        for html_file in funnel_directory.glob("*.html"):
            file_name = html_file.name
            
            # Extract step information from filename
            # Expected format: step_1_stepname.html
            match = re.match(r'step_(\d+)_(.+)\.html', file_name)
            if match:
                step_number = match.group(1)
                step_name = match.group(2).replace('_', ' ')
                html_files.append((step_name, step_number, html_file))
            else:
                self.logger.warning(f"Couldn't parse step information from filename: {file_name}")
        
        # Sort by step number
        html_files.sort(key=lambda x: int(x[1]))
        
        self.logger.info(f"Found {len(html_files)} HTML files for funnel {funnel_id}")
        return html_files
    
    async def analyze_funnel_html_files(
        self, 
        funnel_id: str, 
        html_files: List[Tuple[str, str, Path]], 
        output_manager: OutputManager
    ) -> pd.DataFrame:
        """
        Analyze HTML files from a funnel for accessibility issues using AxeAnalysis.
        
        Args:
            funnel_id: ID of the funnel
            html_files: List of (step_name, step_number, file_path) tuples
            output_manager: Output manager for path handling
            
        Returns:
            DataFrame with accessibility analysis results
        """
        from axcel.axcel import AxeAnalysis
        
        self.logger.info(f"Analyzing {len(html_files)} HTML files for funnel {funnel_id} using AxeAnalysis")
        
        # Create temporary file paths for this analysis session
        funnel_output_dir = output_manager.get_path("analysis", f"funnel_{funnel_id}_temp")
        excel_output_path = funnel_output_dir / f"funnel_{funnel_id}_accessibility.xlsx"
        visited_file_path = funnel_output_dir / "visited_urls.txt"
        
        # Make sure the directories exist
        os.makedirs(funnel_output_dir, exist_ok=True)
        
        # Convert HTML files to URLs
        file_urls = []
        url_to_metadata = {}  # Mapping for storing metadata about each URL
        
        for step_name, step_number, html_file in html_files:
            # Create file:// URL
            file_url = f"file://{html_file.absolute()}"
            file_urls.append(file_url)
            
            # Store metadata for later use
            url_to_metadata[file_url] = {
                "funnel_name": funnel_id,
                "funnel_step": step_name,
                "step_number": step_number,
                "has_funnel_data": True
            }
            
            self.logger.info(f"Added file for analysis: {html_file.name} -> {file_url}")
        
        try:
            # Configure AxeAnalysis to analyze these HTML files
            analyzer = AxeAnalysis(
                urls=file_urls,  # Pass our file URLs directly
                pool_size=self.config_manager.get_int("FUNNEL_POOL_SIZE", 2),  # Smaller pool for files
                sleep_time=self.config_manager.get_float("FUNNEL_SLEEP_TIME", 1.0),
                excel_filename=str(excel_output_path),
                visited_file=str(visited_file_path),
                headless=self.config_manager.get_bool("AXE_HEADLESS", True),
                resume=False,  # Don't resume for funnel analysis
                output_folder=str(funnel_output_dir),
                output_manager=output_manager
            )
            
            # Start the analysis (runs asynchronously internally)
            self.logger.info(f"Starting AxeAnalysis for {len(file_urls)} funnel HTML files")
            analyzer.start()
            
            # Check if the Excel file was generated
            if not os.path.exists(excel_output_path):
                self.logger.error(f"AxeAnalysis did not generate expected output file: {excel_output_path}")
                return pd.DataFrame()
            
            # Read and process the results from the Excel file
            self.logger.info(f"Processing AxeAnalysis results from {excel_output_path}")
            
            # Use pandas to read all sheets from the Excel file
            all_violations = []
            
            # Read Excel with sheet_name=None to get a dict of all sheets
            excel_data = pd.read_excel(excel_output_path, sheet_name=None)
            
            for sheet_name, df in excel_data.items():
                if df.empty:
                    continue
                    
                # Process each row in the sheet
                for _, row in df.iterrows():
                    # Get original URL to retrieve metadata
                    url = row.get('page_url', '')
                    metadata = url_to_metadata.get(url, {})
                    
                    # Create extended violation record with funnel metadata
                    violation = {
                        "page_url": url,
                        "funnel_name": metadata.get('funnel_name', funnel_id),
                        "funnel_step": metadata.get('funnel_step', ''),
                        "step_number": metadata.get('step_number', ''),
                        "has_funnel_data": True,
                        "violation_id": row.get('violation_id', ''),
                        "impact": row.get('impact', ''),
                        "description": row.get('description', ''),
                        "help": row.get('help', ''),
                        "target": row.get('target', ''),
                        "html": row.get('html', ''),
                        "failure_summary": row.get('failure_summary', '')
                    }
                    all_violations.append(violation)
            
            # Create combined DataFrame
            if all_violations:
                self.logger.info(f"Found {len(all_violations)} accessibility violations across {len(file_urls)} funnel HTML files")
                result_df = pd.DataFrame(all_violations)
                
                # Add funnel metadata to result_df
                extra_cols = ["auth_required", "auth_strategy", "funnel_name", "funnel_step", "has_funnel_data"]
                for col in extra_cols:
                    if col not in result_df.columns:
                        if col == "has_funnel_data":
                            result_df[col] = True
                        elif col == "auth_required":
                            result_df[col] = False
                        else:
                            result_df[col] = "none"
                
                # Save to a properly named Excel file
                final_excel_path = output_manager.get_path("analysis", f"funnel_{funnel_id}_accessibility.xlsx")
                with pd.ExcelWriter(final_excel_path) as writer:
                    result_df.to_excel(writer, index=False)
                    
                self.logger.info(f"Saved funnel analysis to {final_excel_path}")
                return result_df
            else:
                self.logger.info(f"No violations found in funnel {funnel_id}")
                return pd.DataFrame()
        
        except Exception as e:
            self.logger.exception(f"Error analyzing funnel HTML files: {e}")
            return pd.DataFrame()
        finally:
            # Cleanup temporary files if needed
            if self.config_manager.get_bool("CLEAN_TEMP_FILES", False):
                try:
                    import shutil
                    shutil.rmtree(funnel_output_dir, ignore_errors=True)
                    self.logger.info(f"Cleaned up temporary directory: {funnel_output_dir}")
                except Exception as cleanup_err:
                    self.logger.warning(f"Error cleaning up temporary files: {cleanup_err}")            

    async def run_axe_analysis(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> bool:
        """
        Esegue l'analisi Axe con gestione standardizzata dei percorsi e gestione errori migliorata.
        
        Args:
            base_url: URL target
            domain_config: Configurazione specifica del dominio
            output_manager: Gestore dell'output
            
        Returns:
            True se analisi completata con successo
        """
        self.logger.info(f"Avvio analisi Axe per {base_url}")
        
        # Ottieni configurazione axe
        axe_config = domain_config.get("axe_config", {})
        
        # Usa l'output manager per ottenere il percorso dello stato crawler (più robusto)
        analysis_state_file = str(output_manager.get_crawler_state_path())
        
        # Definisci percorsi aggiuntivi tramite output manager
        excel_filename = str(output_manager.get_path(
            "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
        visited_file = str(output_manager.get_path(
            "axe", f"visited_urls_{output_manager.domain_slug}.txt"))
        
        # Assicura che le directory esistano
        output_manager.ensure_path_exists("axe")
        
        # Configura URL di fallback e verifica file stato
        fallback_urls = [base_url]
        crawler_file_exists = os.path.exists(analysis_state_file)
        
        # Ottieni i valori configurazione dalle chiavi standardizzate
        max_templates = axe_config.get('max_templates_per_domain', 
                                self.config_manager.get_int("AXE_MAX_TEMPLATES", 50))
        pool_size = axe_config.get('pool_size', 
                            self.config_manager.get_int("AXE_POOL_SIZE", 5))
        sleep_time = axe_config.get('sleep_time', 
                            self.config_manager.get_float("AXE_SLEEP_TIME", 1.0))
        headless = axe_config.get('headless', 
                            self.config_manager.get_bool("AXE_HEADLESS", True))
        resume = axe_config.get('resume', 
                        self.config_manager.get_bool("AXE_RESUME", True))
        
        # Log configurazione con chiavi standardizzate
        self.logger.info(f"Configurazione Axe Analysis:")
        self.logger.info(f"AXE_MAX_TEMPLATES: {max_templates}")
        self.logger.info(f"AXE_POOL_SIZE: {pool_size}")
        self.logger.info(f"AXE_SLEEP_TIME: {sleep_time}")
        self.logger.info(f"AXE_HEADLESS: {headless}")
        self.logger.info(f"AXE_RESUME: {resume}")
        
        if not crawler_file_exists:
            self.logger.warning(f"File stato crawler non trovato: {analysis_state_file}")
            self.logger.info(f"Utilizzo URL fallback: {base_url}")
        else:
            self.logger.info(f"Utilizzo file stato crawler: {analysis_state_file}")
        
        try:
            analyzer = AxeAnalysis(
                urls=None,
                analysis_state_file=analysis_state_file if crawler_file_exists else None,
                domains=axe_config.get("domains"),
                max_templates_per_domain=max_templates,
                fallback_urls=fallback_urls,
                pool_size=pool_size,
                sleep_time=sleep_time,
                excel_filename=excel_filename,
                visited_file=visited_file,
                headless=headless,
                resume=resume,
                output_folder=str(output_manager.get_path("axe")),
                output_manager=output_manager,
                auth_manager=self.auth_manager  # Pass auth_manager here
            )
            
            # Esegui analisi in un thread per evitare blocco asyncio
            await asyncio.to_thread(analyzer.start)
            
            # Verifica output creato
            if os.path.exists(excel_filename):
                self.logger.info(f"Analisi Axe completata con successo per {base_url}")
                return True
            else:
                self.logger.error(f"Analisi Axe non ha prodotto output per {base_url}")
                return False
                
        except Exception as e:
            self.logger.exception(f"Errore in analisi Axe: {e}")
            return False
    
    async def run_report_analysis(self, base_url: str, domain_config: Dict[str, Any],
                                    output_manager: OutputManager,
                                    funnel_metadata: Optional[Dict[str, Dict[str, Any]]] = None, # Non più usato direttamente dall'analyzer
                                    funnel_violations_df: Optional[pd.DataFrame] = None) -> Optional[str]:
            """
            Genera il report di accessibilità finale, combinando i risultati di Axe
            con l'analisi opzionale dei file HTML dei funnel.
            Utilizza il metodo run_analysis dell'analyzer pre-istanziato.

            Args:
                base_url: URL target (usato per logging/contesto).
                domain_config: Configurazione specifica del dominio (potrebbe non essere più necessaria qui).
                output_manager: Gestore dell'output (usato per determinare i percorsi di input/output).
                funnel_metadata: Metadati sui funnel (attualmente non usati direttamente qui).
                funnel_violations_df: DataFrame opzionale con i risultati dell'analisi dei file HTML dei funnel.

            Returns:
                Percorso del report finale generato o None in caso di errore.
            """
            self.logger.info(f"Avvio generazione report analisi per {base_url}...")

            # --- Determina Percorsi Input ---
            # L'analyzer.run_analysis troverà questi di default tramite output_manager,
            # ma li otteniamo qui per poter combinare i dati prima, se necessario.
            axe_report_path = output_manager.get_path("axe", f"accessibility_report_{output_manager.domain_slug}.xlsx")
            # Dai priorità al file _concat se esiste
            concat_report_path_default = output_manager.get_path("analysis", f"accessibility_report_{output_manager.domain_slug}_concat.xlsx")
            if concat_report_path_default.exists():
                path_to_load = concat_report_path_default
                self.logger.info(f"Trovato file concatenato pre-esistente: {path_to_load}")
            elif axe_report_path.exists():
                # Se il concat non esiste, concatena quello base
                self.logger.info(f"File concatenato non trovato, concateno fogli da: {axe_report_path}")
                try:
                    from utils.concat import concat_excel_sheets # Assicurati che sia importato
                    # Salva il file concatenato temporaneo o nell'area analysis
                    concat_output_path = output_manager.get_path("analysis", f"temp_{output_manager.domain_slug}_concat.xlsx")
                    path_to_load = Path(concat_excel_sheets(file_path=str(axe_report_path), output_path=str(concat_output_path)))
                    self.logger.info(f"Fogli concatenati in: {path_to_load}")
                except Exception as concat_err:
                    self.logger.error(f"Errore durante la concatenazione dei fogli da {axe_report_path}: {concat_err}. Tento di usare il file originale.")
                    path_to_load = axe_report_path # Fallback al file originale
            else:
                self.logger.error(f"Nessun file Excel di input Axe trovato ({concat_report_path_default} o {axe_report_path}). Impossibile generare il report.")
                return None

            # Percorso opzionale del file PKL del crawler
            crawler_state_path = output_manager.get_path("crawler", f"crawler_state_{output_manager.domain_slug}.pkl")
            crawler_state_input = str(crawler_state_path) if crawler_state_path.exists() else None
            if not crawler_state_input:
                self.logger.warning(f"File di stato Crawler non trovato ({crawler_state_path}). L'analisi dei template sarà limitata.")


            # --- Combina Dati Funnel HTML (se presenti) ---
            final_input_excel_path = str(path_to_load) # Default: usa il file (concatenato) trovato

            if funnel_violations_df is not None and not funnel_violations_df.empty:
                self.logger.info(f"Combinazione dei risultati Axe ({path_to_load}) con {len(funnel_violations_df)} violazioni da analisi funnel HTML...")
                try:
                    # Carica il DataFrame principale (dal file concatenato)
                    main_axe_df = pd.read_excel(path_to_load, sheet_name=0)

                    # Colonne extra da garantire
                    extra_cols = ["auth_required", "auth_strategy", "funnel_name", "funnel_step", "has_funnel_data"]
                    for col in extra_cols:
                        if col not in main_axe_df.columns:
                            if col == "has_funnel_data":
                                main_axe_df[col] = False
                            elif col == "auth_required":
                                main_axe_df[col] = False
                            else:
                                main_axe_df[col] = "none"
                        if col not in funnel_violations_df.columns:
                            if col == "has_funnel_data":
                                funnel_violations_df[col] = True
                            elif col == "auth_required":
                                funnel_violations_df[col] = False
                            else:
                                funnel_violations_df[col] = "none"

                    # Verifica compatibilità colonne
                    if all(col in funnel_violations_df.columns for col in extra_cols):
                        # Seleziona colonne comuni + quelle specifiche del funnel per mantenere l'informazione
                        funnel_cols_to_keep = extra_cols + ['funnel_name', 'funnel_step', 'step_number', 'has_funnel_data']
                        funnel_violations_df_filtered = funnel_violations_df[[col for col in funnel_cols_to_keep if col in funnel_violations_df.columns]].copy()
                        combined_df_list = [main_axe_df]
                        combined_df_list.append(funnel_violations_df_filtered)
                    else:
                        self.logger.warning("Il DataFrame delle violazioni funnel HTML non ha tutte le colonne richieste. Sarà ignorato.")

                    # Concatena se ci sono dati funnel validi
                    if len(combined_df_list) > 1:
                        combined_df = pd.concat(combined_df_list, ignore_index=True, sort=False)
                        self.logger.info(f"DataFrame combinato creato con {len(combined_df)} righe.")

                        # Salva il DataFrame combinato in un nuovo file Excel temporaneo
                        temp_combined_excel = output_manager.get_path("analysis", f"temp_{output_manager.domain_slug}_combined_input.xlsx")
                        with pd.ExcelWriter(temp_combined_excel) as writer:
                            combined_df.to_excel(writer, index=False, sheet_name="CombinedData")
                        self.logger.info(f"Dati combinati salvati in file temporaneo: {temp_combined_excel}")
                        final_input_excel_path = str(temp_combined_excel) # Usa questo file per l'analisi
                    else:
                        self.logger.info("Nessun dato funnel valido da combinare.")

                except Exception as merge_err:
                    self.logger.error(f"Errore durante la combinazione dei dati Axe e Funnel HTML: {merge_err}. Si procederà solo con i dati Axe principali.")
                    # Usa ancora path_to_load (il file Axe originale/concatenato)


            # --- Esegui l'Analisi Completa usando l'Analyzer ---
            self.logger.info(f"Avvio analisi completa usando l'istanza di AccessibilityAnalyzer...")
            try:
                # Carica il DataFrame principale dal file Excel concatenato
                main_axe_df = None
                if os.path.exists(final_input_excel_path):
                    main_axe_df = pd.read_excel(final_input_excel_path, sheet_name=0)
                else:
                    self.logger.error(f"File di input per l'analisi non trovato: {final_input_excel_path}")
                    return None

                # Se ci sono dati funnel, uniscili
                if funnel_violations_df is not None and not funnel_violations_df.empty:
                    self.logger.info(f"Unione di {len(funnel_violations_df)} violazioni funnel ai dati principali...")
                    # Trova colonne comuni e unisci
                    common_cols = [col for col in main_axe_df.columns if col in funnel_violations_df.columns]
                    funnel_cols_to_keep = common_cols + [c for c in extra_cols if c in funnel_violations_df.columns]
                    funnel_violations_df_filtered = funnel_violations_df[[col for col in funnel_cols_to_keep if col in funnel_violations_df.columns]].copy()
                    combined_df = pd.concat([main_axe_df, funnel_violations_df_filtered], ignore_index=True, sort=False)
                    self.logger.info(f"DataFrame combinato creato con {len(combined_df)} righe totali.")
                else:
                    combined_df = main_axe_df

                # Passa il DataFrame direttamente all'analyzer
                report_path = await asyncio.to_thread(
                    self.analyzer.run_analysis,
                    input_excel=final_input_excel_path,
                    crawler_state=crawler_state_input
                )

                if report_path:
                    self.logger.info(f"Analisi e generazione report completate con successo: {report_path}")
                    return report_path
                else:
                    self.logger.error("Il metodo run_analysis dell'analyzer non ha restituito un percorso valido.")
                    return None

            except Exception as e:
                self.logger.exception(f"Errore durante l'esecuzione di AccessibilityAnalyzer.run_analysis: {e}")
                return None

        # Rimuovi il metodo helper _add_funnel_metadata_to_axe_results se non più necessario
        # def _add_funnel_metadata_to_axe_results(self, ...):
        #    pass
      
    async def run_authentication(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Tuple[bool, List[str]]:
        """Initialize authentication and collect restricted URLs."""
        self.logger.info(f"Initializing authentication for {base_url}")
        
        if not self.config_manager.get_bool("AUTH_ENABLED", False):
            self.logger.info(f"Authentication disabled for {base_url}")
            return False, []
            
        try:
            # Calculate the domain slug exactly as used in config
            domain_slug = self.config_manager.domain_to_slug(base_url)
            self.logger.info(f"Domain slug for auth: {domain_slug} (from {base_url})")
            
            # Ensure we're passing the correct configuration for both auth methods
            auth_strategies = self.config_manager.get_list("AUTH_STRATEGIES", ["form"])
            
            # Log which strategies we're using
            self.logger.info(f"Using authentication strategies: {auth_strategies}")
            
            self.auth_manager = AuthenticationManager(
                config_manager=self.config_manager,
                domain=base_url,
                output_manager=output_manager
            )
            
            # Get restricted URLs directly from config without requiring authentication
            restricted_urls = self._get_restricted_urls(domain_slug)
            self.logger.info(f"Found {len(restricted_urls)} restricted URLs for {domain_slug}")
            
            return True, restricted_urls
        except Exception as e:
            self.logger.exception(f"Error in authentication setup: {e}")
            return False, []
      
    def _get_restricted_urls(self, domain_slug: str) -> List[str]:
        """Get restricted URLs directly from config."""
        
        auth_domains = self.config_manager.get("AUTH_DOMAINS", {})
        self.logger.info(f"Available AUTH_DOMAINS keys: {list(auth_domains.keys())}")
        
        if domain_slug in auth_domains:
            # Get explore_restricted_area boolean - properly retrieving it from the nested dictionary
            domain_config = auth_domains.get(domain_slug, {})
            explore_restricted_area = domain_config.get("explore_restricted_area", True)
            
            if explore_restricted_area:
                urls = domain_config.get("restricted_urls", [])
                self.logger.info(f"Found {len(urls)} restricted URLs in config for {domain_slug}")
                return urls
            else:
                self.logger.info(f"Restricted URL exploration is disabled for {domain_slug}")
                return []
        
        # Try alternative formats of the domain slug
        alt_slug = domain_slug.replace("_", "")
        if alt_slug in auth_domains:
            self.logger.info(f"Found match with alternative slug format: {alt_slug}")
            domain_config = auth_domains.get(alt_slug, {})
            explore_restricted_area = domain_config.get("explore_restricted_area", True)
            
            if explore_restricted_area:
                return domain_config.get("restricted_urls", [])
            else:
                self.logger.info(f"Restricted URL exploration is disabled for {alt_slug}")
                return []
                
        self.logger.warning(f"No restricted URLs found for domain slug '{domain_slug}'")
        return []
    
    async def run_funnel_analysis(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Dict[str, Any]:
        """
        Esegue l'analisi dei funnel per un dominio, gestendo l'autenticazione e raccogliendo i risultati.
        Anche se un funnel fallisce, analizza gli HTML generati se disponibili.
        
        Args:
            base_url: URL di base del dominio
            domain_config: Configurazione specifica del dominio
            output_manager: Gestore dell'output per i file
            
        Returns:
            Dictionary con i risultati dell'analisi dei funnel
        """
        self.logger.info(f"Avvio analisi funnel per {base_url}")
        
        # Controlla se l'analisi dei funnel è abilitata
        if not self.config_manager.get_bool("FUNNEL_ANALYSIS_ENABLED", False):
            self.logger.info(f"Analisi funnel disabilitata per {base_url}")
            return {'enabled': False, 'funnels': {}}
                
        # Inizializza strutture dati per i risultati
        results = {}
        funnel_metadata = {}  # Mappatura URL -> dati funnel
        all_funnel_violations = []
        domain_slug = self.config_manager.domain_to_slug(base_url)
        html_files_found = False  # Flag per tracciare se sono stati trovati file HTML

        try:
            # PRIMA: Inizializza il FunnelManager
            self.logger.info(f"Inizializzazione FunnelManager per {base_url}")
            self.funnel_manager = FunnelManager(
                config_manager=self.config_manager,
                domain=base_url,
                output_manager=output_manager,
                auth_manager=self.auth_manager
            )
            
            # POI: Ottieni i funnel disponibili
            available_funnels = self.funnel_manager.get_available_funnels(domain_slug)
            if not available_funnels:
                self.logger.info(f"Nessun funnel definito per {base_url}")
                return {'enabled': True, 'funnels': {}}
            
            self.logger.info(f"Trovati {len(available_funnels)} funnel per dominio {domain_slug}")
                
            # Verifica se possiamo riutilizzare il driver dall'autenticazione
            if self.auth_manager and hasattr(self.auth_manager, 'driver') and self.auth_manager.driver:
                self.logger.info("Riutilizzo del driver di autenticazione per i funnel")
                
                # Verifica se il driver ha un metodo quit per assicurarsi che sia valido
                if hasattr(self.auth_manager.driver, 'quit'):
                    # Passa il driver esistente al funnel manager
                    if hasattr(self.funnel_manager, 'use_existing_driver'):
                        self.funnel_manager.use_existing_driver(self.auth_manager.driver)
                    else:
                        self.logger.warning("Metodo 'use_existing_driver' non trovato, verrà creato un nuovo driver")
                    
                    # Verifica l'autenticazione prima di procedere
                    if hasattr(self.auth_manager, 'verify_authentication'):
                        is_still_auth = self.auth_manager.verify_authentication(self.auth_manager.driver)
                        self.logger.info(f"Verifica autenticazione: {'Valida' if is_still_auth else 'NON valida'}")
                        
                        # Se l'autenticazione non è più valida, prova a riautenticarsi
                        if not is_still_auth:
                            self.logger.warning("Tentativo di ri-autenticazione prima di eseguire i funnel")
                            auth_success = self.auth_manager.login()
                            if not auth_success:
                                self.logger.error("Ri-autenticazione fallita, i funnel potrebbero non funzionare correttamente")
                    else:
                        self.logger.info("La verifica dell'autenticazione non è disponibile")
                else:
                    self.logger.warning("Il driver di autenticazione non sembra valido, ne verrà creato uno nuovo")
                    
            # Elabora ogni funnel disponibile
            for funnel_id in available_funnels:
                if self.shutdown_flag:
                    self.logger.warning("Shutdown richiesto, interruzione analisi funnel")
                    break
                    
                self.logger.info(f"Esecuzione funnel: {funnel_id}")
                
                try:
                    # Esegui il funnel
                    funnel_results = self.funnel_manager.execute_funnel(funnel_id)
                    results[funnel_id] = funnel_results
                    
                    # Memorizza i metadati dei funnel per ogni URL (anche se il funnel non ha completato tutte le fasi)
                    for step_name, url, success in funnel_results:
                        if url and isinstance(url, str):
                            funnel_metadata[url] = {
                                'funnel_name': funnel_id,
                                'funnel_step': step_name,
                                'success': success
                            }
                    
                except Exception as funnel_err:
                    self.logger.exception(f"Errore durante l'esecuzione del funnel {funnel_id}: {funnel_err}")
                    results[funnel_id] = []  # Segna come funnel fallito, ma continua con l'analisi degli HTML
                
                # IMPORTANTE: Analizza i file HTML generati indipendentemente dal successo del funnel
                # Raccolta file HTML generati (funziona anche se il funnel è fallito ma ha generato HTML)
                html_files = self.collect_funnel_html_files(funnel_id, output_manager)
                
                if html_files:
                    html_files_found = True  # Imposta il flag perché abbiamo trovato file HTML
                    self.logger.info(f"Analisi di {len(html_files)} file HTML del funnel {funnel_id} (funnel {'completato con successo' if results[funnel_id] else 'fallito'})")
                    funnel_violations_df = await self.analyze_funnel_html_files(funnel_id, html_files, output_manager)
                    
                    # Aggiungi alla lista complessiva di violazioni
                    if hasattr(funnel_violations_df, 'empty') and not funnel_violations_df.empty:
                        all_funnel_violations.append(funnel_violations_df)
                        self.logger.info(f"Aggiunte {len(funnel_violations_df)} violazioni all'analisi complessiva")
                else:
                    self.logger.warning(f"Nessun file HTML trovato per il funnel {funnel_id}")
                
                # Statistiche sul successo del funnel (se ci sono risultati)
                funnel_results = results.get(funnel_id, [])
                if funnel_results:
                    success_count = sum(1 for _, _, success in funnel_results if success)
                    total_steps = len(funnel_results)
                    success_rate = (success_count / total_steps * 100) if total_steps > 0 else 0
                    self.logger.info(f"Funnel {funnel_id}: {success_count}/{total_steps} step completati ({success_rate:.1f}%)")
            
            # Combina tutte le violazioni dei funnel in un unico DataFrame
            combined_violations = pd.DataFrame()
            if all_funnel_violations:
                try:
                    combined_violations = pd.concat(all_funnel_violations, ignore_index=True)
                    
                    # Salva analisi combinata
                    combined_path = output_manager.get_path(
                        "analysis", f"all_funnels_accessibility.xlsx")
                    with pd.ExcelWriter(combined_path) as writer:
                        combined_violations.to_excel(writer, index=False)
                    
                    self.logger.info(f"Analisi combinata dei funnel salvata in: {combined_path}")
                except Exception as combine_err:
                    self.logger.error(f"Errore durante la combinazione dei risultati dei funnel: {combine_err}")
            
            return {
                'enabled': True,
                'funnels': results,
                'metadata': funnel_metadata,
                'violations_df': combined_violations,
                'html_files_found': html_files_found  # Aggiungiamo questo flag per indicare se sono stati trovati file HTML
            }
                    
        except Exception as e:
            self.logger.exception(f"Errore durante l'analisi dei funnel: {e}")
            return {'enabled': True, 'funnels': {}, 'metadata': {}, 'html_files_found': html_files_found}
        finally:
            # Chiudi il funnel manager solo se il driver non è condiviso con auth_manager
            if self.funnel_manager:
                shared_driver = (self.auth_manager and hasattr(self.auth_manager, 'driver') and 
                                self.funnel_manager.driver is self.auth_manager.driver)
                
                if not shared_driver:
                    self.logger.info("Chiusura FunnelManager (driver dedicato)")
                    self.funnel_manager.close()
                else:
                    self.logger.info("FunnelManager utilizza driver condiviso, non viene chiuso qui")
                    
    def _add_funnel_metadata_to_axe_results(self, excel_path: Union[str, Path], funnel_metadata: Dict[str, Dict[str, Any]]) -> bool:
        """Add funnel metadata to Axe Excel results."""
        if not excel_path or not funnel_metadata:
            return False
            
        try:
            excel_path = Path(excel_path) if isinstance(excel_path, str) else excel_path
            
            if not excel_path.exists():
                self.logger.warning(f"Excel file not found: {excel_path}")
                return False
                
            self.logger.info(f"Adding funnel metadata to {excel_path}")
            
            xls = pd.ExcelFile(excel_path)
            dfs = {}
            
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                
                if df.empty or 'page_url' not in df.columns:
                    dfs[sheet_name] = df
                    continue
                    
                # Add funnel columns
                if 'funnel_name' not in df.columns:
                    df['funnel_name'] = 'none'
                if 'funnel_step' not in df.columns:
                    df['funnel_step'] = 'none'
                if 'has_funnel_data' not in df.columns:
                    df['has_funnel_data'] = False
                    
                # Update rows with funnel information
                for url, metadata in funnel_metadata.items():
                    # Match both exact URLs and URLs containing the funnel URL (more robust matching)
                    mask = df['page_url'].apply(lambda x: str(x) == url or url in str(x))
                    if mask.any():
                        df.loc[mask, 'funnel_name'] = metadata.get('funnel_name', 'unknown')
                        df.loc[mask, 'funnel_step'] = metadata.get('funnel_step', 'unknown')
                        df.loc[mask, 'has_funnel_data'] = True
                        
                dfs[sheet_name] = df
            
            # Write back to the Excel file
            with pd.ExcelWriter(excel_path) as writer:
                for sheet_name, df in dfs.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    
            self.logger.info(f"Successfully added funnel metadata to {excel_path}")
            return True
            
        except Exception as e:
            self.logger.exception(f"Error adding funnel metadata to Excel file: {e}")
            return False
        
    async def run_axe_analysis_on_urls(
        self, 
        base_url: str, 
        domain_config: Dict[str, Any], 
        output_manager: OutputManager,
        urls: List[str],
        auth_manager = None
    ) -> bool:
        """Run Axe analysis on specific URLs."""
        if not urls:
            self.logger.warning(f"No URLs provided for analysis")
            return False
        
        self.logger.info(f"Running Axe analysis on {len(urls)} special URLs")
        self.logger.info(f"First 5 URLs: {urls[:5]}")
        
        try:
            # Get configuration for Axe
            axe_config = domain_config.get("axe_config", {})
            
            # Define paths through output manager
            excel_filename = str(output_manager.get_path(
                "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
            visited_file = str(output_manager.get_path(
                "axe", f"visited_urls_{output_manager.domain_slug}.txt"))
            
            # Ensure directories exist
            output_manager.ensure_path_exists("axe")
            
            # Create AxeAnalysis configured specifically for these URLs
            analyzer = AxeAnalysis(
                urls=urls,  # Pass the URLs directly
                analysis_state_file=None,  # No state file needed for direct URL analysis
                domains=axe_config.get("domains"),
                max_templates_per_domain=axe_config.get('max_templates_per_domain', 
                                    self.config_manager.get_int("AXE_MAX_TEMPLATES", 50)),
                fallback_urls=[],  # No fallback needed
                pool_size=axe_config.get('pool_size', 
                                self.config_manager.get_int("AXE_POOL_SIZE", 5)),
                sleep_time=axe_config.get('sleep_time', 
                                self.config_manager.get_float("AXE_SLEEP_TIME", 1.0)),
                excel_filename=excel_filename,
                visited_file=visited_file,
                headless=axe_config.get('headless', 
                                self.config_manager.get_bool("AXE_HEADLESS", True)),
                resume=axe_config.get('resume', 
                            self.config_manager.get_bool("AXE_RESUME", True)),
                output_folder=str(output_manager.get_path("axe")),
                output_manager=output_manager,
                auth_manager=auth_manager
            )
            
            # Run the analysis
            await asyncio.to_thread(analyzer.start)
            
            # Verify output was created
            if os.path.exists(excel_filename):
                self.logger.info(f"Special URL analysis completed successfully: {excel_filename}")
                return True
            else:
                self.logger.error(f"Special URL analysis produced no output")
                return False
                
        except Exception as e:
            self.logger.exception(f"Error in special URL analysis: {e}")
            return False

    async def process_url(self, base_url: str) -> Optional[str]:
        """
        Elabora un URL attraverso l'intero pipeline con progressione esplicita e gestione errori.
        Assicura che i file HTML dei funnel vengano analizzati anche se il funnel fallisce.
        
        Args:
            base_url: URL da processare
            
        Returns:
            Percorso del report finale o None
        """
        self.logger.info(f"Processing {base_url} through pipeline")
        
        # Get domain configuration
        domain_config = self.config_manager.load_domain_config(base_url)
        
        # Create output manager
        output_manager = OutputManager(
            base_dir=self.config_manager.get_path("OUTPUT_DIR", "~/axeScraper/output", create=True),
            domain=base_url,
            create_dirs=True
        )
        
        # Initialize authentication (don't login yet) and get restricted URLs 
        auth_setup_success, restricted_urls = await self.run_authentication(base_url, domain_config, output_manager)
        
        # Log the results for debugging
        if auth_setup_success:
            self.logger.info(f"Authentication setup successful, found {len(restricted_urls)} restricted URLs")
            if restricted_urls:
                self.logger.info(f"First few restricted URLs: {restricted_urls[:3]}")
        
        # Get pipeline configuration with standardized keys
        start_stage = self.pipeline_config.get("start_stage") or self.config_manager.get("START_STAGE", "crawler")
        repeat_axe = self.pipeline_config.get("repeat_axe") or self.config_manager.get_int("REPEAT_ANALYSIS", 1)
        
        # Run crawler if starting from that phase
        if start_stage == "crawler":
            self.logger.info(f"Starting from crawler phase for {base_url}")
            try:
                crawler_success = await self.run_crawler(base_url, domain_config, output_manager)
                
                if not crawler_success:
                    self.logger.warning(f"Crawler phase failed for {base_url}, continuing pipeline")
                    
                if self.shutdown_flag:
                    self.logger.warning(f"Shutdown requested after crawler phase for {base_url}")
                    return None
            except Exception as e:
                self.logger.exception(f"Unhandled error in crawler phase: {e}")
                self.logger.warning(f"Continuing despite crawler error for {base_url}")
        else:
            self.logger.info(f"Skipping crawler phase for {base_url} (starting from {start_stage})")

        # Run standard accessibility analysis
        if start_stage in ["crawler", "auth", "axe"]:
            # Standard analysis without authentication
            await self.run_axe_analysis(base_url, domain_config, output_manager)
            
            # Special handling for restricted URLs
            if restricted_urls:
                self.logger.info(f"Running dedicated analysis on {len(restricted_urls)} restricted URLs")
                
                # Create separate output manager for authenticated content
                auth_output_manager = OutputManager(
                    base_dir=output_manager.base_dir,
                    domain=f"{output_manager.domain_slug}_auth",
                    create_dirs=True
                )
                
                # Only attempt authentication now if we have restricted URLs to analyze
                auth_success = False
                if auth_setup_success and self.auth_manager:
                    self.logger.info("Performing authentication for restricted URL analysis")
                    auth_success = self.auth_manager.login()
                    
                    if not auth_success:
                        self.logger.warning("Authentication failed, restricted URLs may not be accessible")
                
                # Run specific analysis for restricted URLs with auth_manager
                await self.run_axe_analysis_on_urls(
                    base_url, 
                    domain_config, 
                    auth_output_manager,
                    restricted_urls,
                    auth_manager=self.auth_manager
                )
                
                # Generate report for authenticated content
                auth_report_path = await self.run_report_analysis(
                    base_url, 
                    domain_config, 
                    auth_output_manager
                )
                
                if auth_report_path:
                    self.logger.info(f"Generated authenticated area report: {auth_report_path}")

        # Run funnel analysis
        funnel_metadata = {}
        funnel_violations_df = None
        html_files_found = False
        
        if start_stage in ["crawler", "auth", "axe", "funnel"]:
            funnel_analysis_result = await self.run_funnel_analysis(base_url, domain_config, output_manager)
            
            # Check if analysis is enabled
            if funnel_analysis_result.get('enabled', False):
                funnel_metadata = funnel_analysis_result.get('metadata', {})
                funnel_violations_df = funnel_analysis_result.get('violations_df', None)
                html_files_found = funnel_analysis_result.get('html_files_found', False)
                
                # Log whether HTML files were found
                if html_files_found:
                    self.logger.info("HTML files were generated during funnel execution and will be analyzed")
                else:
                    self.logger.warning("No HTML files were found from funnel execution")

        # Generate final report with all data
        if not self.shutdown_flag:
            try:
                # Add funnel metadata to main results if any found
                if funnel_metadata:
                    self._add_funnel_metadata_to_axe_results(
                        output_manager.get_path("axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"),
                        funnel_metadata
                    )
                    self.logger.info("Added funnel metadata to accessibility report")
                
                # Generate final report - IMPORTANT: We do this even if the funnel failed but produced HTML
                have_funnel_data = funnel_violations_df is not None and not funnel_violations_df.empty
                
                # Log status before report generation
                if have_funnel_data:
                    self.logger.info(f"Will include {len(funnel_violations_df)} funnel violations in final report")
                
                report_path = await self.run_report_analysis(
                    base_url,
                    domain_config,
                    output_manager,
                    funnel_metadata=funnel_metadata,
                    funnel_violations_df=funnel_violations_df
                )
                
                if report_path:
                    self.logger.info(f"Final report generated for {base_url}: {report_path}")
                    if have_funnel_data:
                        self.logger.info("Report includes funnel analysis data")
                    return report_path
                else:
                    self.logger.error("Failed to generate final report")
                    
            except Exception as e:
                self.logger.exception(f"Error in final report generation: {e}")
                return None

        # Alla fine della pipeline:
        self.logger.info("=== FINE PIPELINE DI ACCESSIBILITÀ ===")

        return None
    
    async def process_all_urls(self) -> List[str]:
        """
        Processa tutti gli URL configurati attraverso il pipeline completo.
        
        Returns:
            Lista dei percorsi dei report generati
        """
        base_urls = self.config_manager.get_all_domains()
        self.logger.info(f"Elaborazione di {len(base_urls)} domini:")
        for url in base_urls:
            self.logger.info(f"  - {url}")
        
        # Avvia task di monitoraggio risorse
        monitor_task = asyncio.create_task(self.monitor_resources())
        
        # Processa tutti gli URL
        results = []
        for url in base_urls:
            if self.shutdown_flag:
                self.logger.warning("Interruzione richiesta, arresto elaborazione")
                break
                
            try:
                report_path = await self.process_url(url)
                if report_path:
                    results.append(report_path)
            except Exception as e:
                self.logger.error(f"Errore elaborando {url}: {e}")
                self.logger.error(traceback.format_exc())
        
        # Ferma monitoraggio risorse
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
            
        return results
    
    async def run(self) -> int:
        """
        Esegue il pipeline completo e invia i report via email se configurato.
        
        Returns:
            Codice di uscita (0 = successo, altro = errore)
        """
        self.logger.info("Avvio pipeline di accessibilità")
        start_time = time.time()
        
        try:
            # Processa tutti gli URL
            report_paths = await self.process_all_urls()
            
            # Cleanup
            if self.auth_manager:
                self.auth_manager.close()
            if self.funnel_manager:
                self.funnel_manager.close()
            
            # Invia report via email se configurato
            if report_paths and self.config_manager.get_bool("SEND_EMAIL", False):
                email_config = self.config_manager.get_email_config()
                recipient = email_config.get("recipient_email")
                
                if recipient and "@" in recipient:
                    self.logger.info(f"Invio report via email a {recipient}")
                    try:
                        await asyncio.to_thread(send_email_report, report_paths, recipient)
                        self.logger.info("Email inviata con successo")
                    except Exception as e:
                        self.logger.error(f"Errore invio email: {e}")
            
            # Calcola tempo totale
            elapsed = time.time() - start_time
            self.logger.info(f"Pipeline completato in {elapsed:.1f} secondi "
                           f"({elapsed/60:.1f} minuti)")
            
            # Verifica successo
            if report_paths:
                self.logger.info(f"Generati {len(report_paths)} report")
                for path in report_paths:
                    self.logger.info(f"  - {path}")
                return 0
            else:
                self.logger.warning("Nessun report generato")
                return 1
                
        except Exception as e:
            self.logger.exception(f"Errore fatale durante l'esecuzione del pipeline: {e}")
            return 2

async def main():
    """Entry point del programma con supporto per parametri CLI."""
    import argparse
    
    # Crea parser per argomenti da linea di comando
    parser = argparse.ArgumentParser(description='Pipeline di analisi accessibilità axeScraper')
    parser.add_argument('--config', '-c', help='File di configurazione')
    parser.add_argument('--domains', '-d', help='Domini da analizzare (separati da virgola)')
    parser.add_argument('--start', '-s', choices=['crawler', 'axe', 'analysis'], 
                        help='Stadio iniziale del pipeline')
    parser.add_argument('--max-urls', '-m', type=int, help='Numero massimo di URL per dominio')
    parser.add_argument('--debug', action='store_true', help='Attiva modalità debug')
    
    # Elabora gli argomenti
    args = parser.parse_args()
    
    # Converti argomenti in un dizionario per ConfigurationManager
    cli_args = {}
    if args.domains:
        cli_args['BASE_URLS'] = args.domains
    if args.start:
        cli_args['START_STAGE'] = args.start
    if args.max_urls:
        cli_args['CRAWLER_MAX_URLS'] = args.max_urls
    if args.debug:
        cli_args['DEBUG'] = True
    
    # Inizializza e avvia pipeline
    pipeline = Pipeline(config_file=args.config, cli_args=cli_args)
    exit_code = await pipeline.run()
    return exit_code

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        exit(exit_code)
    except KeyboardInterrupt:
        print("Pipeline interrotto dall'utente")
        exit(130)
    except Exception as e:
        print(f"Errore non gestito nel pipeline: {e}")
        print(traceback.format_exc())
        exit(1)