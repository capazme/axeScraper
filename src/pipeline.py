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

# Import delle classi centrali di gestione
from utils.config_manager import ConfigurationManager
from utils.logging_config import get_logger
from utils.output_manager import OutputManager
from utils.auth_manager import AuthenticationManager
from utils.funnel_manager import FunnelManager

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
                "-s", f"LOG_LEVEL=INFO",
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
        Analyze HTML files from a funnel for accessibility issues.
        
        Args:
            funnel_id: ID of the funnel
            html_files: List of (step_name, step_number, file_path) tuples
            output_manager: Output manager for path handling
            
        Returns:
            DataFrame with accessibility analysis results
        """
        from selenium import webdriver
        from axe_selenium_python import Axe
        
        self.logger.info(f"Analyzing {len(html_files)} HTML files for funnel {funnel_id}")
        
        # Initialize webdriver
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
        
        all_violations = []
        
        try:
            for step_name, step_number, html_file in html_files:
                self.logger.info(f"Analyzing funnel step: {step_name} (file: {html_file.name})")
                
                # Load HTML file directly
                file_url = f"file://{html_file.absolute()}"
                driver.get(file_url)
                
                # Wait for page to load
                await asyncio.sleep(1)
                
                # Run axe analysis
                axe = Axe(driver)
                axe.inject()
                results = axe.run()
                
                # Process violations
                for violation in results.get("violations", []):
                    for node in violation.get("nodes", []):
                        issue = {
                            "page_url": file_url,  # Use file URL as identifier
                            "funnel_name": funnel_id,
                            "funnel_step": step_name,
                            "step_number": step_number,
                            "has_funnel_data": True,
                            "violation_id": violation.get("id", ""),
                            "impact": violation.get("impact", ""),
                            "description": violation.get("description", ""),
                            "help": violation.get("help", ""),
                            "target": ", ".join([", ".join(x) if isinstance(x, list) else x 
                                            for x in node.get("target", [])]),
                            "html": node.get("html", ""),
                            "failure_summary": node.get("failureSummary", "")
                        }
                        all_violations.append(issue)
                
                self.logger.info(f"Found {len(all_violations)} violations in step {step_name}")
                
            # Create DataFrame from all violations
            if all_violations:
                df = pd.DataFrame(all_violations)
                
                # Save to Excel file
                excel_path = output_manager.get_path(
                    "analysis", f"funnel_{funnel_id}_accessibility.xlsx")
                with pd.ExcelWriter(excel_path) as writer:
                    df.to_excel(writer, index=False)
                    
                self.logger.info(f"Saved funnel analysis to {excel_path}")
                return df
            else:
                self.logger.info(f"No violations found in funnel {funnel_id}")
                return pd.DataFrame()
                
        except Exception as e:
            self.logger.exception(f"Error analyzing funnel HTML files: {e}")
            return pd.DataFrame()
        finally:
            driver.quit()
    
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
                          funnel_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
                          funnel_violations_df: Optional[pd.DataFrame] = None) -> Optional[str]:
        """
        Generates the final report of accessibility with standardized path management.
        
        Args:
            base_url: Target URL
            domain_config: Domain-specific configuration
            output_manager: Output manager instance
            funnel_metadata: Optional metadata about funnels
            funnel_violations_df: Optional DataFrame with funnel HTML analysis results
            
        Returns:
            Path to the generated report or None
        """
        self.logger.info(f"Generating final report for {base_url}")
        
        # Ensure funnel_metadata is a dictionary, not None
        funnel_metadata = funnel_metadata or {}
        
        # Get standardized paths
        input_excel = str(output_manager.get_path(
            "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
        concat_excel = str(output_manager.get_path(
            "analysis", f"accessibility_report_{output_manager.domain_slug}_concat.xlsx"))
        output_excel = str(output_manager.get_path(
            "analysis", f"final_analysis_{output_manager.domain_slug}.xlsx"))
        crawler_state = str(output_manager.get_path(
            "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
        charts_dir = str(output_manager.get_path("charts"))
        
        # Add funnel metadata to Excel file
        if funnel_metadata:
            self.logger.info(f"Adding funnel metadata to Excel for {len(funnel_metadata)} URLs")
            self._add_funnel_metadata_to_axe_results(input_excel, funnel_metadata)
        
        try:
            # STEP 1: Concatenate sheets from main Excel file
            from utils.concat import concat_excel_sheets
            self.logger.info(f"Concatenating sheets from {input_excel}")
            concat_excel_path = concat_excel_sheets(file_path=input_excel, output_path=concat_excel)
            self.logger.info(f"Sheets concatenated and saved to {concat_excel_path}")
            
            # STEP 2: Load main analysis data
            analyzer = AccessibilityAnalyzer(output_manager=output_manager)
            
            # Set funnel metadata if provided
            if funnel_metadata:
                analyzer.funnel_metadata = funnel_metadata
                self.logger.info(f"Added funnel metadata for {len(funnel_metadata)} URLs")
            
            # Load and process the data
            self.logger.info(f"Loading accessibility data for {base_url}")
            axe_df = analyzer.load_data(concat_excel_path, crawler_state)
            
            # STEP 3: Merge funnel HTML analysis results if available
            if funnel_violations_df is not None and not funnel_violations_df.empty:
                self.logger.info(f"Integrating {len(funnel_violations_df)} funnel violations into analysis")
                
                # Ensure common columns exist in both DataFrames
                required_columns = ['violation_id', 'impact', 'page_url', 'description', 'help', 'target', 'html', 'failure_summary']
                
                # Verify all required columns exist in both DataFrames
                missing_in_axe = [col for col in required_columns if col not in axe_df.columns]
                missing_in_funnel = [col for col in required_columns if col not in funnel_violations_df.columns]
                
                if missing_in_axe or missing_in_funnel:
                    self.logger.warning(f"Missing columns in DataFrames: axe_df: {missing_in_axe}, funnel_df: {missing_in_funnel}")
                    self.logger.warning("Will only concatenate compatible columns")
                    
                    # Find common columns
                    common_columns = [col for col in axe_df.columns if col in funnel_violations_df.columns]
                    
                    # Add missing columns to funnel_violations_df with None values
                    for col in axe_df.columns:
                        if col not in funnel_violations_df.columns:
                            funnel_violations_df[col] = None
                
                # Concatenate DataFrames
                axe_df = pd.concat([axe_df, funnel_violations_df], ignore_index=True)
                self.logger.info(f"Combined DataFrame now has {len(axe_df)} rows")
            
            # Continue with analysis as before
            self.logger.info(f"Calculating metrics for {base_url}")
            metrics = analyzer.calculate_metrics(axe_df)
            
            self.logger.info(f"Creating data aggregations for {base_url}")
            aggregations = analyzer.create_aggregations(axe_df)
            
            self.logger.info(f"Generating charts for {base_url}")
            chart_files = analyzer.create_charts(metrics, aggregations, axe_df)
            
            # Load template data if available
            template_df = None
            if os.path.exists(crawler_state):
                try:
                    self.logger.info(f"Loading template structure data for {base_url}")
                    templates_df, state = analyzer.load_template_data(crawler_state)
                    template_df = analyzer.analyze_templates(templates_df, axe_df)
                except Exception as e:
                    self.logger.warning(f"Template analysis failed (non-critical): {e}")
            
            # Generate final report
            self.logger.info(f"Creating final Excel report for {base_url}")
            report_path = analyzer.generate_report(
                axe_df=axe_df,
                metrics=metrics,
                aggregations=aggregations,
                chart_files=chart_files,
                template_df=template_df,
                output_excel=output_excel
            )
            
            self.logger.info(f"Final report generated: {report_path}")
            return report_path
            
        except Exception as e:
            self.logger.exception(f"Error generating final report: {e}")
            return None   
        
    async def run_authentication(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Tuple[bool, List[str]]:
        """Initialize authentication and collect restricted URLs without forcing login."""
        self.logger.info(f"Initializing authentication for {base_url}")
        
        if not self.config_manager.get_bool("AUTH_ENABLED", False):
            self.logger.info(f"Authentication disabled for {base_url}")
            return False, []
            
        try:
            # Calculate the domain slug exactly as used in config
            domain_slug = self.config_manager.domain_to_slug(base_url)
            self.logger.info(f"Domain slug for auth: {domain_slug} (from {base_url})")
            
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
            urls = auth_domains[domain_slug].get("restricted_urls", [])
            self.logger.info(f"Found restricted URLs in config: {urls}")
            return urls
        
        # Try alternative formats of the domain slug
        alt_slug = domain_slug.replace("_", "")
        if alt_slug in auth_domains:
            self.logger.info(f"Found match with alternative slug format: {alt_slug}")
            return auth_domains[alt_slug].get("restricted_urls", [])
            
        self.logger.warning(f"No restricted URLs found for domain slug '{domain_slug}'")
        return []  
     
    async def run_funnel_analysis(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Dict[str, Any]:
        """Run funnel analysis for a domain."""
        self.logger.info(f"Running funnel analysis for {base_url}")
        
        if not self.config_manager.get_bool("FUNNEL_ANALYSIS_ENABLED", False):
            self.logger.info(f"Funnel analysis disabled for {base_url}")
            return {'enabled': False, 'funnels': {}}
            
        results = {}
        funnel_metadata = {}  # Store URL -> funnel mappings
        all_funnel_violations = []
        
        try:
            self.funnel_manager = FunnelManager(
                config_manager=self.config_manager,
                domain=base_url,
                output_manager=output_manager,
                auth_manager=self.auth_manager
            )
            
            domain_slug = self.config_manager.domain_to_slug(base_url)
            available_funnels = self.funnel_manager.get_available_funnels(domain_slug)
            
            if not available_funnels:
                self.logger.info(f"No funnels defined for {base_url}")
                return {'enabled': True, 'funnels': {}}
                    
            self.logger.info(f"Found {len(available_funnels)} funnels for {base_url}")
            
            for funnel_id in available_funnels:
                if self.shutdown_flag:
                    break
                    
                self.logger.info(f"Executing funnel: {funnel_id}")
                
                # Execute the funnel
                funnel_results = self.funnel_manager.execute_funnel(funnel_id)
                results[funnel_id] = funnel_results
                
                # Store metadata mapping for each URL in this funnel
                for step_name, url, success in funnel_results:
                    if url:
                        funnel_metadata[url] = {
                            'funnel_name': funnel_id,
                            'funnel_step': step_name,
                            'success': success
                        }
                
                # Now analyze the HTML files from this funnel
                html_files = self.collect_funnel_html_files(funnel_id, output_manager)
                
                if html_files:
                    self.logger.info(f"Analyzing {len(html_files)} HTML files from funnel {funnel_id}")
                    funnel_violations_df = await self.analyze_funnel_html_files(funnel_id, html_files, output_manager)
                    
                    # Add to the overall list of violations
                    if not funnel_violations_df.empty:
                        all_funnel_violations.append(funnel_violations_df)
                
                success_count = sum(1 for _, _, success in funnel_results if success)
                total_steps = len(funnel_results)
                self.logger.info(f"Funnel {funnel_id}: {success_count}/{total_steps} steps successful")
            
            # Combine all funnel violations into a single DataFrame
            combined_violations = pd.DataFrame()
            if all_funnel_violations:
                combined_violations = pd.concat(all_funnel_violations, ignore_index=True)
                
                # Save combined analysis
                combined_path = output_manager.get_path(
                    "analysis", f"all_funnels_accessibility.xlsx")
                with pd.ExcelWriter(combined_path) as writer:
                    combined_violations.to_excel(writer, index=False)
                
                self.logger.info(f"Saved combined funnel analysis to {combined_path}")
            
            return {
                'enabled': True,
                'funnels': results,
                'metadata': funnel_metadata,
                'violations_df': combined_violations
            }
                
        except Exception as e:
            self.logger.exception(f"Error in funnel analysis: {e}")
            return {'enabled': True, 'funnels': {}, 'metadata': {}}
        finally:
            if self.funnel_manager:
                self.funnel_manager.close()
                
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
        if start_stage in ["crawler", "auth", "axe", "funnel"]:
            funnel_analysis_result = await self.run_funnel_analysis(base_url, domain_config, output_manager)
            if funnel_analysis_result.get('enabled', False):
                funnel_metadata = funnel_analysis_result.get('metadata', {})
                funnel_violations_df = funnel_analysis_result.get('violations_df', None)

        # Generate final report with all data
        if not self.shutdown_flag:
            try:
                # Add funnel metadata to main results
                if funnel_metadata:
                    self._add_funnel_metadata_to_axe_results(
                        output_manager.get_path("axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"),
                        funnel_metadata
                    )
                
                # Generate final report
                report_path = await self.run_report_analysis(
                    base_url,
                    domain_config,
                    output_manager,
                    funnel_metadata=funnel_metadata,
                    funnel_violations_df=funnel_violations_df
                )
                
                if report_path:
                    self.logger.info(f"Final report generated for {base_url}: {report_path}")
                    return report_path
                    
            except Exception as e:
                self.logger.exception(f"Error in final report generation: {e}")
                return None

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