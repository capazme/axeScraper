#!/usr/bin/env python3
"""
AxeAnalysis

Analizza un insieme di URL utilizzando axe-core (tramite Selenium) e genera un report Excel,
con uno sheet per ogni URL analizzato. I progressi vengono salvati periodicamente su file
in modo da poter riprendere l'analisi in caso di interruzione.

Compatibile con output di multi_domain_crawler.
"""

import asyncio
import re
import logging
import tempfile
import pickle
import os
import json
import glob
from pathlib import Path
from urllib.parse import urlparse

import nest_asyncio
nest_asyncio.apply()

import pandas as pd
from axe_selenium_python import Axe
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .excel_report import rename_headers
from ..utils.config import LOGGING_CONFIG
from ..utils.output_manager import OutputManager
from ..utils.logging_config import get_logger

AUTO_SAVE_INTERVAL = 5  # Salva lo stato ogni 5 URL processati

def load_urls_from_crawler_state(state_file: str, fallback_urls=None) -> list[str]:
    """
    Carica gli URL dal file di stato del crawler (pickle).
    Supporta sia il vecchio formato che il nuovo formato del multi_domain_crawler.
    """
    path = Path(state_file)
    if path.exists():
        try:
            with path.open("rb") as f:
                state = pickle.load(f)
            
            urls = []
            
            # Prova il nuovo formato di multi_domain_crawler
            if "domain_data" in state:
                # Il nuovo formato memorizza i dati per dominio in domain_data
                for domain, data in state["domain_data"].items():
                    if "structures" in data and data["structures"]:
                        urls.extend([data["structures"][t]["url"] for t in data["structures"]])
                        logging.info(f"Caricati {len(urls)} URL da templates in domain_data[{domain}]")
                        
            # Fallback al vecchio formato
            elif "structures" in state and state["structures"]:
                urls = [data["url"] for data in state["structures"].values()]
                logging.info(f"Caricati {len(urls)} URL univoci dal file usando il vecchio formato")
            elif "unique_pages" in state and state["unique_pages"]:
                urls = list(state["unique_pages"])
                logging.info(f"Caricati {len(urls)} URL univoci dal file usando unique_pages")
            else:
                urls = list(state.get("visited", []))
                logging.info(f"Caricati {len(urls)} URL (tutti) dal file")
            
            # Se non troviamo URL, usa fallback
            if not urls and fallback_urls is not None:
                logging.info("Nessun URL trovato, uso fallback.")
                urls = fallback_urls
            return urls
        except Exception as e:
            logging.exception(f"Errore nel caricamento del file di stato {state_file}: {e}")
            try:
                path.unlink()
                logging.info(f"File {state_file} eliminato per corruzione.")
            except Exception as unlink_e:
                logging.exception(f"Errore nell'eliminazione del file {state_file}: {unlink_e}")
            return fallback_urls if fallback_urls is not None else []
    else:
        logging.warning(f"File di stato {state_file} non trovato.")
        return fallback_urls if fallback_urls is not None else []

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((TimeoutException, WebDriverException))
)

def robust_driver_get(driver, url):
    """Carica la pagina con driver.get(url) con retry in caso di errori."""
    driver.get(url)

def safe_pickle_dump(data, filename):
    """Salva i dati in modo sicuro su file."""
    tmpfile = filename + ".tmp"
    with open(tmpfile, "wb") as f:
        pickle.dump(data, f)
    os.replace(tmpfile, filename)
    logging.debug(f"Stato salvato su '{tmpfile}' e sostituito in '{filename}'.")

def load_urls_from_multi_domain_output(output_dir: str, domains=None, max_templates_per_domain=None, fallback_urls=None) -> list[str]:
    """
    Carica UN URL rappresentativo per ogni template dal crawler multi-dominio.
    
    Supporta il nuovo formato del multi_domain_crawler che utilizza una struttura diversa
    per memorizzare i template e le relative informazioni.
    """
    representative_urls = []
    output_path = Path(output_dir)
    
    # Se è specificata una lista di domini, usa solo quelli
    if domains:
        domain_list = [d.strip() for d in domains.split(',')] if isinstance(domains, str) else domains
    else:
        # Altrimenti cerca tutte le cartelle di dominio nell'output_dir
        domain_list = [d.name for d in output_path.glob("*") if d.is_dir() and not d.name.startswith('.')]
    
    logging.info(f"Cercando URL rappresentativi per i domini: {domain_list}")
    
    for domain in domain_list:
        domain_templates = []
        domain_dir = output_path / domain
        
        # Priorità 1: Cerca file di stato del crawler (per il nuovo formato multi_domain_crawler)
        state_files = list(domain_dir.glob("crawler_state_*.pkl"))
        if state_files:
            latest_state = sorted(state_files)[-1]  # Prendi il più recente
            logging.info(f"Usando il file di stato del crawler: {latest_state}")
            
            try:
                with open(latest_state, 'rb') as f:
                    state = pickle.load(f)
                
                # Gestisce il nuovo formato di multi_domain_crawler
                if "domain_data" in state:
                    for domain_name, data in state["domain_data"].items():
                        if domain_name == domain or domain_name == f"{domain}:":  # Alcuni domini finiscono con ':'
                            if "structures" in data:
                                for template_key, template_data in data["structures"].items():
                                    if isinstance(template_data, dict) and "url" in template_data:
                                        domain_templates.append({
                                            'template': template_key,
                                            'url': template_data['url'],
                                            'count': template_data.get('count', 1)
                                        })
                # Fallback al vecchio formato
                elif "structures" in state:
                    for template_key, template_data in state["structures"].items():
                        if isinstance(template_data, dict) and "url" in template_data:
                            domain_templates.append({
                                'template': template_key,
                                'url': template_data['url'],
                                'count': template_data.get('count', 1)
                            })
            except Exception as e:
                logging.exception(f"Errore nel caricamento del file di stato {latest_state}: {e}")

        # Continua con le priorità esistenti se il formato di stato non è riconosciuto
        if not domain_templates:
            # Priorità 2: Cerca file JSON di template
            json_files = list(domain_dir.glob("templates_*.json"))
            if json_files:
                latest_json = sorted(json_files)[-1]  # Prendi il più recente
                logging.info(f"Usando il file template JSON: {latest_json}")
                
                try:
                    with open(latest_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if 'templates' in data:
                            # Estrai template dal formato standard
                            for template_key, template_data in data['templates'].items():
                                if isinstance(template_data, dict) and 'url' in template_data and 'count' in template_data:
                                    domain_templates.append({
                                        'template': template_key,
                                        'url': template_data['url'],
                                        'count': template_data['count']
                                    })
                        elif 'domains' in data and domain in data['domains']:
                            # Formato alternativo (consolidated report)
                            for template_key, template_data in data['domains'][domain]['top_templates'].items():
                                if isinstance(template_data, dict) and 'url' in template_data:
                                    domain_templates.append({
                                        'template': template_key,
                                        'url': template_data['url'],
                                        'count': template_data.get('count', 1)
                                    })
                except Exception as e:
                    logging.exception(f"Errore nel caricamento del file JSON {latest_json}: {e}")
        
        # Priorità 3: Cercare template nei file CSV
        if not domain_templates:
            csv_files = list(domain_dir.glob("templates_*.csv"))
            if csv_files:
                latest_csv = sorted(csv_files)[-1]  # Prendi il più recente
                logging.info(f"Usando il file CSV: {latest_csv}")
                
                try:
                    df = pd.read_csv(latest_csv)
                    if all(col in df.columns for col in ['template', 'example_url']):
                        for _, row in df.iterrows():
                            domain_templates.append({
                                'template': row['template'],
                                'url': row['example_url'],
                                'count': row.get('count', 1)
                            })
                except Exception as e:
                    logging.exception(f"Errore nel caricamento del file CSV {latest_csv}: {e}")
        
        # Ordina per conteggio (i template più comuni prima)
        domain_templates.sort(key=lambda x: x['count'], reverse=True)
        
        # Limita il numero di template se specificato
        if max_templates_per_domain and len(domain_templates) > max_templates_per_domain:
            logging.info(f"Limitando il dominio {domain} a {max_templates_per_domain} template " +
                        f"(da {len(domain_templates)})")
            domain_templates = domain_templates[:max_templates_per_domain]
        
        # Estrai solo gli URL rappresentativi
        domain_urls = [template['url'] for template in domain_templates]
        logging.info(f"Trovati {len(domain_urls)} URL rappresentativi per il dominio {domain} " +
                    f"(uno per ciascuno dei {len(domain_templates)} template)")
        
        # Aggiungi metadati per debug
        for i, (template, url) in enumerate(zip([t['template'] for t in domain_templates], domain_urls)):
            logging.debug(f"  {i+1}. Template: {template} -> URL: {url}")
        
        representative_urls.extend(domain_urls)
    
    # Rimuovi duplicati (in caso uno stesso URL rappresenti più template)
    unique_urls = list(dict.fromkeys(representative_urls))
    
    # Usa fallback se necessario
    if not unique_urls and fallback_urls:
        logging.info("Nessun URL rappresentativo trovato, uso fallback.")
        unique_urls = fallback_urls
    
    logging.info(f"Totale: {len(unique_urls)} URL unici da analizzare (uno per template)")
    return unique_urls


class AxeAnalysis:
    def __init__(
        self,
        urls: list[str] = None,
        analysis_state_file: str = None,
        crawler_output_dir: str = None,
        domains: str = None,
        max_templates_per_domain: int = None,
        fallback_urls: list[str] = None,
        pool_size: int = 10,
        sleep_time: float = 1.0,
        excel_filename: str = None,
        visited_file: str = None,
        headless: bool = True,
        resume: bool = True,
        output_folder: str = None,
        output_manager = None
    ) -> None:
        """
        Initialize the accessibility analysis on representative URLs for templates.
        """
        # Set up logger with component-specific config
        self.logger = get_logger("axe_analysis", 
                             LOGGING_CONFIG.get("components", {}).get("axe_analysis", {}))
        
        # Use output manager if provided
        self.output_manager = output_manager
        
        # First look for URLs from the multi-domain crawler (one URL per template)
        if urls is None and crawler_output_dir:
            urls = load_urls_from_multi_domain_output(
                crawler_output_dir, 
                domains=domains,
                max_templates_per_domain=max_templates_per_domain,
                fallback_urls=fallback_urls
            )
        # Fallback to the old system
        elif urls is None and analysis_state_file is not None:
            urls = load_urls_from_crawler_state(analysis_state_file, fallback_urls=fallback_urls)
        elif urls is None:
            urls = fallback_urls or []
            
        self.all_urls = set(urls)
        self.logger.info(f"{len(self.all_urls)} representative URLs will be analyzed.")

        # Determine paths from output manager if available
        if self.output_manager:
            self.visited_file = self.output_manager.get_path("axe", "visited_urls.txt")
            self.excel_filename = self.output_manager.get_path(
                "axe", f"accessibility_report_{self.output_manager.domain_slug}.xlsx")
            self.output_folder = str(self.output_manager.get_path("axe"))
        else:
            # Use provided paths
            self.visited_file = Path(visited_file or "visited_urls.txt")
            self.excel_filename = excel_filename or "accessibility_report.xlsx"
            self.output_folder = output_folder or "output_axe"
            
            # Create output directory if needed
            Path(self.output_folder).mkdir(parents=True, exist_ok=True)

        self.visited: set[str] = set()
        if resume:
            self._load_visited()
        else:
            self.logger.info("Resume mode disabled: ignoring visited state.")

        self.pending_urls = list(self.all_urls - self.visited)
        self.logger.info(f"{len(self.pending_urls)} pending URLs to process.")

        self.pool_size = pool_size
        self.sleep_time = sleep_time
        self.headless = headless

        self.results: dict[str, list[dict]] = {}
        self.processed_count = 0

    def _load_visited(self) -> None:
        """Carica gli URL già processati dal file visited."""
        if self.visited_file.exists():
            try:
                with self.visited_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        url = line.strip()
                        if url:
                            self.visited.add(url)
                self.logger.info(f"Caricati {len(self.visited)} URL dal file '{self.visited_file}'.")
            except Exception as e:
                self.logger.exception(f"Errore nel caricamento del file visited: {e}")
        else:
            self.logger.debug(f"Nessun file visited trovato in '{self.visited_file}'.")

    def _save_visited(self) -> None:
        """Salva gli URL processati su file."""
        try:
            with self.visited_file.open("w", encoding="utf-8") as f:
                for url in sorted(self.visited):
                    f.write(url + "\n")
            self.logger.info(f"Salvati {len(self.visited)} URL in '{self.visited_file}'.")
        except Exception as e:
            self.logger.exception(f"Errore nel salvataggio del file visited: {e}")

    def _create_driver(self) -> webdriver.Chrome:
        """Crea un nuovo WebDriver Chrome."""
        options = ChromeOptions()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--incognito")
        temp_profile = tempfile.mkdtemp()
        options.add_argument(f"--user-data-dir={temp_profile}")
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(5)
        driver.set_page_load_timeout(30)
        self.logger.debug("WebDriver creato.")
        return driver

    async def _init_driver_pool(self) -> asyncio.Queue:
        """Crea un pool di WebDriver e li inserisce in una coda asincrona."""
        pool = asyncio.Queue()
        for _ in range(self.pool_size):
            driver = await asyncio.to_thread(self._create_driver)
            await pool.put(driver)
        self.logger.info(f"Pool di {self.pool_size} WebDriver creato.")
        return pool

    async def process_url(self, url: str, driver_pool: asyncio.Queue) -> None:
        """Processa un singolo URL utilizzando un WebDriver dal pool."""
        self.logger.info(f"Inizio analisi: {url}")
        driver = await driver_pool.get()
        try:
            await asyncio.to_thread(robust_driver_get, driver, url)
            await asyncio.sleep(self.sleep_time)
            axe = Axe(driver)
            for attempt in range(1, 4):
                try:
                    await asyncio.to_thread(axe.inject)
                    results = await asyncio.to_thread(axe.run)
                    break
                except Exception as e:
                    self.logger.exception(f"Errore con axe su {url}, tentativo {attempt}: {e}")
                    if attempt == 3:
                        results = {"violations": []}
                    else:
                        await asyncio.sleep(5)
            issues = []
            for violation in results.get("violations", []):
                for node in violation.get("nodes", []):
                    issue = {
                        "page_url": url,
                        "violation_id": violation.get("id", ""),
                        "impact": violation.get("impact", ""),
                        "description": violation.get("description", ""),
                        "help": violation.get("help", ""),
                        "target": ", ".join([", ".join(x) if isinstance(x, list) else x for x in node.get("target", [])]),
                        "html": node.get("html", ""),
                        "failure_summary": node.get("failureSummary", "")
                    }
                    issues.append(issue)
            self.results[url] = issues
            self.logger.info(f"{url}: {len(issues)} issues trovate.")
            self.visited.add(url)
            self.processed_count += 1
            if self.processed_count % AUTO_SAVE_INTERVAL == 0:
                self._save_visited()
        except Exception as e:
            self.logger.exception(f"Errore durante il processing di {url}: {e}")
        finally:
            # Rilascia il driver nel pool per il riutilizzo
            await driver_pool.put(driver)

    async def run(self) -> None:
        """Processa tutti gli URL pendenti usando il pool di driver."""
        if not self.pending_urls:
            self.logger.warning("Nessun URL da analizzare!")
            return
            
        driver_pool = await self._init_driver_pool()
        tasks = [asyncio.create_task(self.process_url(url, driver_pool))
                 for url in self.pending_urls]
        self.logger.info(f"Avvio di {len(tasks)} task di analisi...")
        await asyncio.gather(*tasks, return_exceptions=True)
        self._save_visited()
        # Chiudi tutti i driver nel pool
        while not driver_pool.empty():
            driver = await driver_pool.get()
            await asyncio.to_thread(driver.quit)
        self.logger.info("Tutti i driver del pool sono stati chiusi.")

    def generate_excel_report(self) -> None:
        """Genera un report Excel dai risultati raccolti, uno sheet per pagina."""
        self.logger.info("Generazione report Excel...")
        if not self.results:
            self.logger.warning("Nessun risultato da esportare.")
            return
        excel_path = Path(self.excel_filename)
        if not excel_path.parent.exists():
            try:
                excel_path.parent.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"Cartella '{excel_path.parent}' creata.")
            except Exception as e:
                self.logger.exception(f"Errore nella creazione della cartella '{excel_path.parent}': {e}")
                return
        try:
            sheet_counter = {}  # Per gestire nomi duplicati
            
            with pd.ExcelWriter(self.excel_filename, engine="openpyxl") as writer:
                for url, issues in self.results.items():
                    # Estrai dominio e percorso per nome sheet
                    parsed = urlparse(url)
                    domain = parsed.netloc.replace("www.", "")
                    
                    # Estrai l'ultimo segmento del percorso per il nome sheet
                    path = parsed.path.rstrip('/')
                    if path:
                        last_segment = path.split('/')[-1]
                    else:
                        last_segment = "home"
                    
                    # Crea nome sheet base
                    base_name = f"{domain}_{last_segment}"
                    base_name = re.sub(r'[\\/*?:\[\]]', '_', base_name)[:28]  # Lascia spazio per un numero
                    
                    # Gestisci i duplicati aggiungendo un contatore
                    if base_name in sheet_counter:
                        sheet_counter[base_name] += 1
                        sheet_name = f"{base_name}_{sheet_counter[base_name]}"
                    else:
                        sheet_counter[base_name] = 1
                        sheet_name = base_name
                    
                    # Limita a 31 caratteri (max per Excel)
                    sheet_name = sheet_name[:31]
                    
                    df = pd.DataFrame(issues) if issues else pd.DataFrame(columns=[
                        "page_url", "violation_id", "impact", "description",
                        "help", "target", "html", "failure_summary"
                    ])
                    
                    # Aggiungi URL alla prima riga se manca
                    if df.empty:
                        df = pd.DataFrame([{"page_url": url, "violation_id": "N/A", 
                                          "impact": "N/A", "description": "Nessun problema rilevato"}])
                    
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    self.logger.debug(f"Sheet '{sheet_name}' creato per {url}")
            
            # Rinomina le intestazioni per renderle più leggibili
            rename_headers(self.excel_filename, self.excel_filename)
            
            self.logger.info(f"Report Excel generato: '{self.excel_filename}'")
            self.logger.info(f"Contiene {len(self.results)} sheet, uno per ogni URL rappresentativo analizzato")
            
        except Exception as e:
            self.logger.exception(f"Errore nella generazione del report Excel: {e}")

    def start(self) -> None:
        """Avvia il processing e genera il report al termine."""
        asyncio.run(self.run())
        self.generate_excel_report()

def main() -> None:
    """
    Esempio d'uso con il nuovo crawler multi-dominio:
    """
    crawler_output_dir = "/home/ec2-user/axeScraper/src/multi_domain_crawler/output_crawler"
    fallback_urls = ["https://sapglegal.com/"]
    
    analyzer = AxeAnalysis(
        crawler_output_dir=crawler_output_dir,
        domains="sapglegal.com",  # Opzionale: limita a questi domini
        max_templates_per_domain=50,  # Limita il numero di URL per dominio
        fallback_urls=fallback_urls,
        pool_size=6,  # Numero di driver paralleli nel pool
        sleep_time=1.5,
        excel_filename="/home/ec2-user/axeScraper/output_axe/accessibility_report_multi.xlsx",
        visited_file="/home/ec2-user/axeScraper/output_axe/visited_urls_multi.txt",
        headless=True,
        resume=True,  # Riprendi l'analisi da dove era stata interrotta
        output_folder="/home/ec2-user/axeScraper/output_axe"
    )
    analyzer.start()

if __name__ == "__main__":
    main()