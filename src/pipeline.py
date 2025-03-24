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
from typing import Dict, Any, List, Optional, Set, Tuple
from pathlib import Path
import traceback

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
        
        # Configura il logger
        self.logger = get_logger("pipeline", self.config_manager.get_logging_config()["components"]["pipeline"])
        
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
            # Crea analyzer con percorsi standardizzati
            analyzer = AxeAnalysis(
                urls=None,
                analysis_state_file=analysis_state_file if crawler_file_exists else None,
                domains=axe_config.get("domains"),
                max_templates_per_domain=max_templates,  # Usa il valore standardizzato
                fallback_urls=fallback_urls,
                pool_size=pool_size,  # Usa il valore standardizzato
                sleep_time=sleep_time,  # Usa il valore standardizzato
                excel_filename=excel_filename,
                visited_file=visited_file,
                headless=headless,  # Usa il valore standardizzato
                resume=resume,  # Usa il valore standardizzato
                output_folder=str(output_manager.get_path("axe")),
                output_manager=output_manager
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
    
    async def run_report_analysis(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Optional[str]:
        """
        Genera il report finale di accessibilità con gestione standardizzata dei percorsi.
        
        Args:
            base_url: URL target
            domain_config: Configurazione specifica del dominio
            output_manager: Gestore dell'output
            
        Returns:
            Percorso del report generato o None
        """
        self.logger.info(f"Generazione report finale per {base_url}")
        
        # Ottieni configurazione report
        report_config = domain_config.get("report_config", {})
        
        # Ottieni percorsi standardizzati
        input_excel = str(output_manager.get_path(
            "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
        # Percorso per il file Excel concatenato
        concat_excel = str(output_manager.get_path(
            "analysis", f"accessibility_report_{output_manager.domain_slug}_concat.xlsx"))
        output_excel = str(output_manager.get_path(
            "analysis", f"final_analysis_{output_manager.domain_slug}.xlsx"))
        crawler_state = str(output_manager.get_path(
            "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
        charts_dir = str(output_manager.get_path("charts"))
        
        # Assicura che le directory esistano
        output_manager.ensure_path_exists("analysis")
        output_manager.ensure_path_exists("charts")
        
        # Verifica dipendenze
        if not os.path.exists(input_excel):
            self.logger.error(f"Report Axe richiesto non trovato: {input_excel}")
            return None
        
        try:
            # NUOVO PASSAGGIO: Concatenare i fogli Excel dall'output di Axe
            from utils.concat import concat_excel_sheets
            self.logger.info(f"Concatenazione fogli Excel da {input_excel}")
            concat_excel_path = concat_excel_sheets(file_path=input_excel, output_path=concat_excel)
            self.logger.info(f"Fogli Excel concatenati e salvati in {concat_excel_path}")
            
            # Crea analyzer con output manager
            analyzer = AccessibilityAnalyzer(output_manager=output_manager)
            
            # Esegui pipeline di analisi con progressione chiara
            self.logger.info(f"Caricamento dati accessibilità per {base_url}")
            # Usa il file Excel concatenato invece dell'originale
            axe_df = analyzer.load_data(concat_excel_path, crawler_state)
            
            self.logger.info(f"Calcolo metriche per {base_url}")
            metrics = analyzer.calculate_metrics(axe_df)
            
            self.logger.info(f"Creazione aggregazioni dati per {base_url}")
            aggregations = analyzer.create_aggregations(axe_df)
            
            self.logger.info(f"Generazione grafici per {base_url}")
            chart_files = analyzer.create_charts(metrics, aggregations, axe_df)
            
            # Carica dati template se disponibili
            template_df = None
            if os.path.exists(crawler_state):
                try:
                    self.logger.info(f"Caricamento dati struttura template per {base_url}")
                    templates_df, state = analyzer.load_template_data(crawler_state)
                    template_df = analyzer.analyze_templates(templates_df, axe_df)
                except Exception as e:
                    self.logger.warning(f"Analisi template fallita (non critica): {e}")
            
            # Genera report Excel finale
            self.logger.info(f"Creazione report Excel finale per {base_url}")
            report_path = analyzer.generate_report(
                axe_df=axe_df,
                metrics=metrics,
                aggregations=aggregations,
                chart_files=chart_files,
                template_df=template_df,
                output_excel=output_excel
            )
            
            self.logger.info(f"Report finale generato: {report_path}")
            return report_path
            
        except Exception as e:
            self.logger.exception(f"Errore generando report finale: {e}")
            return None
    
    async def run_authentication(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> bool:
        """Perform authentication for a domain."""
        self.logger.info(f"Initializing authentication for {base_url}")
        
        if not self.config_manager.get_bool("AUTH_ENABLED", False):
            self.logger.info(f"Authentication disabled for {base_url}")
            return False
            
        try:
            self.auth_manager = AuthenticationManager(
                config_manager=self.config_manager,
                domain=base_url,
                output_manager=output_manager
            )
            
            success = self.auth_manager.login()
            
            if success:
                self.logger.info(f"Authentication successful for {base_url}")
                authenticated_urls = self.auth_manager.collect_authenticated_urls()
                self.logger.info(f"Collected {len(authenticated_urls)} authenticated URLs for analysis")
            else:
                self.logger.error(f"Authentication failed for {base_url}")
                
            return success
        except Exception as e:
            self.logger.exception(f"Error in authentication: {e}")
            return False

    async def run_funnel_analysis(self, base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Dict[str, List[Tuple[str, str, bool]]]:
        """Run funnel analysis for a domain."""
        self.logger.info(f"Running funnel analysis for {base_url}")
        
        if not self.config_manager.get_bool("FUNNEL_ANALYSIS_ENABLED", False):
            self.logger.info(f"Funnel analysis disabled for {base_url}")
            return {}
            
        results = {}
        
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
                return {}
                
            self.logger.info(f"Found {len(available_funnels)} funnels for {base_url}")
            
            for funnel_id in available_funnels:
                if self.shutdown_flag:
                    break
                    
                self.logger.info(f"Executing funnel: {funnel_id}")
                funnel_results = self.funnel_manager.execute_funnel(funnel_id)
                results[funnel_id] = funnel_results
                
                success_count = sum(1 for _, _, success in funnel_results if success)
                total_steps = len(funnel_results)
                self.logger.info(f"Funnel {funnel_id}: {success_count}/{total_steps} steps successful")
            
            return results
            
        except Exception as e:
            self.logger.exception(f"Error in funnel analysis: {e}")
            return {}
        finally:
            if self.funnel_manager:
                self.funnel_manager.close()

    async def run_axe_analysis_on_urls(
        self, 
        base_url: str, 
        domain_config: Dict[str, Any], 
        output_manager: OutputManager,
        urls: List[str],
        auth_manager = None
    ) -> bool:
        """Run Axe analysis on specific URLs."""
        self.logger.info(f"Avvio analisi Axe su URL specifici per {base_url}")
        
        # Ottieni configurazione axe
        axe_config = domain_config.get("axe_config", {})
        
        # Definisci percorsi aggiuntivi tramite output manager
        excel_filename = str(output_manager.get_path(
            "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
        visited_file = str(output_manager.get_path(
            "axe", f"visited_urls_{output_manager.domain_slug}.txt"))
        
        # Assicura che le directory esistano
        output_manager.ensure_path_exists("axe")
        
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
        
        try:
            # Crea analyzer con percorsi standardizzati
            analyzer = AxeAnalysis(
                urls=urls,
                analysis_state_file=None,
                domains=axe_config.get("domains"),
                max_templates_per_domain=max_templates,  # Usa il valore standardizzato
                fallback_urls=[],
                pool_size=pool_size,  # Usa il valore standardizzato
                sleep_time=sleep_time,  # Usa il valore standardizzato
                excel_filename=excel_filename,
                visited_file=visited_file,
                headless=headless,  # Usa il valore standardizzato
                resume=resume,  # Usa il valore standardizzato
                output_folder=str(output_manager.get_path("axe")),
                output_manager=output_manager,
                auth_manager=auth_manager
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

    async def process_url(self, base_url: str) -> Optional[str]:
        """
        Elabora un URL attraverso l'intero pipeline con progressione esplicita e gestione errori.
        
        Args:
            base_url: URL da processare
            
        Returns:
            Percorso del report finale o None
        """
        self.logger.info(f"Elaborazione {base_url} attraverso il pipeline")
        
        # Ottieni configurazione dominio
        domain_config = self.config_manager.load_domain_config(base_url)
        
        # Crea output manager per questo dominio
        output_root = self.config_manager.get_path("OUTPUT_DIR", "~/axeScraper/output", create=True)
        clean_domain = base_url.replace("http://", "").replace("https://", "").replace("www.", "")
        clean_domain = clean_domain.split('/')[0]
        
        output_manager = OutputManager(
            base_dir=output_root,
            domain=clean_domain,
            create_dirs=True
        )
        
        # Memorizza l'output manager per riferimento futuro
        self.output_managers[base_url] = output_manager 
        
        # Ottieni configurazione pipeline con chiavi standardizzate
        start_stage = self.pipeline_config.get("start_stage") or self.config_manager.get("START_STAGE", "crawler")
        repeat_axe = self.pipeline_config.get("repeat_axe") or self.config_manager.get_int("REPEAT_ANALYSIS", 1)
        
        # Log configurazione per debug
        self.logger.info(f"Pipeline config: START_STAGE={start_stage}, REPEAT_ANALYSIS={repeat_axe}")
        self.logger.info(f"Output manager: base_dir={output_manager.base_dir}, domain={output_manager.domain}")
        
        # Esegui crawler se iniziamo da quella fase
        if start_stage == "crawler":
            self.logger.info(f"Partenza da fase crawler per {base_url}")
            try:
                crawler_success = await self.run_crawler(base_url, domain_config, output_manager)
                
                if not crawler_success:
                    self.logger.warning(f"Fase crawler fallita per {base_url}, continuo con il pipeline")
                    
                if self.shutdown_flag:
                    self.logger.warning(f"Interruzione richiesta dopo fase crawler per {base_url}")
                    return None
            except Exception as e:
                self.logger.exception(f"Errore non gestito in fase crawler: {e}")
                self.logger.warning(f"Continuo nonostante errore crawler per {base_url}")
        else:
            self.logger.info(f"Salto fase crawler per {base_url} (partenza da {start_stage})")
        
        # Run authentication if needed
        auth_success = False
        authenticated_urls = []
        if start_stage in ["crawler", "auth", "axe"]:
            auth_success = await self.run_authentication(base_url, domain_config, output_manager)
            if auth_success and self.auth_manager:
                authenticated_urls = self.auth_manager.authenticated_urls
                self.logger.info(f"Authentication successful, {len(authenticated_urls)} URLs available")

        # Run funnel analysis if enabled
        funnel_results = {}
        funnel_urls = []
        if start_stage in ["crawler", "auth", "axe", "funnel"]:
            funnel_results = await self.run_funnel_analysis(base_url, domain_config, output_manager)
            if self.funnel_manager:
                funnel_urls = self.funnel_manager.get_all_visited_urls()
                self.logger.info(f"Collected {len(funnel_urls)} URLs from funnel analysis")

        # Combine special URLs
        special_urls = list(set(authenticated_urls + funnel_urls))

        # Run standard and special URL analysis
        if start_stage in ["crawler", "auth", "axe"]:
            self.logger.info(f"Esecuzione analisi Axe per {base_url} ({repeat_axe} iterazioni)")
            
            axe_success = False
            for i in range(repeat_axe):
                self.logger.info(f"Iterazione analisi Axe {i+1}/{repeat_axe} per {base_url}")
                try:
                    iteration_success = await self.run_axe_analysis(base_url, domain_config, output_manager)
                    axe_success = axe_success or iteration_success
                    
                    if not iteration_success:
                        self.logger.warning(f"Iterazione analisi Axe {i+1} fallita per {base_url}")
                        
                    if self.shutdown_flag:
                        self.logger.warning(f"Interruzione richiesta durante analisi Axe per {base_url}")
                        return None
                except Exception as e:
                    self.logger.exception(f"Errore non gestito in iterazione analisi Axe {i+1}: {e}")
                    
                # Pausa tra iterazioni
                if i < repeat_axe - 1:
                    await asyncio.sleep(1)
                    
            if not axe_success:
                self.logger.error(f"Tutte le iterazioni analisi Axe fallite per {base_url}")
                self.logger.warning(f"Continuo alla fase report finale nonostante fallimenti Axe")
            
            # Add special URL analysis
            if special_urls:
                self.logger.info(f"Running Axe analysis on {len(special_urls)} special URLs")
                try:
                    special_output_manager = OutputManager(
                        base_dir=output_root,
                        domain=f"{output_manager.domain_slug}_auth",
                        create_dirs=True
                    )
                    
                    await self.run_axe_analysis_on_urls(
                        base_url, 
                        domain_config, 
                        special_output_manager,
                        special_urls,
                        auth_manager=self.auth_manager if auth_success else None
                    )
                except Exception as e:
                    self.logger.exception(f"Error in special URLs analysis: {e}")

        # Genera report finale
        if not self.shutdown_flag:
            self.logger.info(f"Generazione report finale per {base_url}")
            try:
                report_path = await self.run_report_analysis(base_url, domain_config, output_manager)
                
                if report_path:
                    self.logger.info(f"Report finale generato per {base_url}: {report_path}")
                    return report_path
                else:
                    self.logger.error(f"Impossibile generare report finale per {base_url}")
                    return None
            except Exception as e:
                self.logger.exception(f"Errore non gestito in fase report finale: {e}")
                return None
        else:
            self.logger.warning(f"Interruzione richiesta prima della fase report finale per {base_url}")
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