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
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import traceback

# Import delle classi centrali di gestione
from utils.config_manager import ConfigurationManager
from utils.logging_config import get_logger
from utils.output_manager import OutputManager

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
    
    def __init__(self):
        """Inizializza il pipeline con la configurazione globale."""
        # Inizializza il gestore di configurazione
        self.config_manager = ConfigurationManager(project_name="axeScraper")
        
        # Configura il logger
        self.logger = get_logger("pipeline", self.config_manager.get_logging_config()["components"]["pipeline"])
        
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
                
            # Configura il comando
            cmd = [
                "python", "-m", "scrapy", "crawl", "multi_domain_spider",
                "-a", f"domains={clean_domain}",
                "-a", f"max_urls_per_domain={crawler_config.get('max_urls', 1000)}",
                "-a", f"hybrid_mode={'True' if crawler_config.get('hybrid_mode', True) else 'False'}",
                "-a", f"request_delay={crawler_config.get('request_delay', 0.25)}",
                "-a", f"selenium_threshold={crawler_config.get('pending_threshold', 30)}",
                "-s", f"OUTPUT_DIR={output_dir}",
                "-s", f"CONCURRENT_REQUESTS={crawler_config.get('max_workers', 16)}",
                "-s", f"CONCURRENT_REQUESTS_PER_DOMAIN={max(8, crawler_config.get('max_workers', 16) // 2)}",
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
                max_templates_per_domain=axe_config.get("max_templates_per_domain"),
                fallback_urls=fallback_urls,
                pool_size=axe_config.get("pool_size", 5),
                sleep_time=axe_config.get("sleep_time", 1),
                excel_filename=excel_filename,
                visited_file=visited_file,
                headless=axe_config.get("headless", True),
                resume=axe_config.get("resume", True),
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
            from src.utils.concat import concat_excel_sheets
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
        
        # Ottieni configurazione pipeline
        start_stage = self.pipeline_config.get("start_stage", "crawler")
        repeat_axe = self.pipeline_config.get("repeat_axe", 1)
        
        # Log configurazione per debug
        self.logger.info(f"Pipeline config: start_stage={start_stage}, repeat_axe={repeat_axe}")
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
        
        # Esegui analisi Axe se iniziamo da crawler o axe
        if start_stage in ["crawler", "axe"]:
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
        else:
            self.logger.info(f"Salto fase analisi Axe per {base_url} (partenza da {start_stage})")
        
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
    """Entry point del programma."""
    pipeline = Pipeline()
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