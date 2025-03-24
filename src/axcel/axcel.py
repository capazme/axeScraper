#!/usr/bin/env python3
"""
AxeAnalysis

Analyzes a set of URLs using axe-core (via Selenium) and generates an Excel report,
with one sheet per analyzed URL. Progress is saved periodically to allow resuming
in case of interruption.

Compatible with output from multi_domain_crawler.
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

# Import configuration management
from utils.config_manager import ConfigurationManager
from utils.logging_config import get_logger
from utils.output_manager import OutputManager

# Initialize configuration manager
config_manager = ConfigurationManager(project_name="axeScraper")

# Set up logger with axe-specific configuration
logger = get_logger("axe_analysis", config_manager.get_logging_config()["components"]["axe_analysis"])

# Auto-save interval
AUTO_SAVE_INTERVAL = config_manager.get_int("CRAWLER_SAVE_INTERVAL", 5)


# In src/axcel/axcel.py
def load_urls_from_crawler_state(state_file: str, fallback_urls=None) -> list[str]:
    """
    Loads URLs from the crawler state file (pickle).
    Supports both old and new formats from multi_domain_crawler.
    
    Args:
        state_file: Path to crawler state pickle file
        fallback_urls: URLs to use if state file can't be processed
        
    Returns:
        List of URLs to analyze
    """
    path = Path(state_file)
    logger.info(f"Tentativo di caricamento URL da {state_file}")
    
    if path.exists():
        try:
            with path.open("rb") as f:
                state = pickle.load(f)
            
            urls = []
            
            # Try the new multi_domain_crawler format
            if "domain_data" in state:
                # The new format stores domain data in domain_data
                for domain, data in state["domain_data"].items():
                    if "structures" in data and data["structures"]:
                        urls.extend([data["structures"][t]["url"] for t in data["structures"] 
                                    if "url" in data["structures"][t]])
                        logger.info(f"Loaded {len(urls)} URLs from templates in domain_data[{domain}]")
            
            # Check alternative formats in domain_data
            elif isinstance(state, dict) and any(k for k in state.keys() if isinstance(k, str) and k.endswith(':')):
                # Format where domain names end with colon
                for domain, data in state.items():
                    if isinstance(data, dict) and "structures" in data and data["structures"]:
                        domain_urls = [data["structures"][t]["url"] for t in data["structures"] 
                                       if "url" in data["structures"][t]]
                        urls.extend(domain_urls)
                        logger.info(f"Loaded {len(domain_urls)} URLs from domain {domain}")
                        
            # Fallback to old format
            elif "structures" in state and state["structures"]:
                urls = [data["url"] for data in state["structures"].values() 
                        if "url" in data]
                logger.info(f"Loaded {len(urls)} unique URLs from file using the old format")
            elif "unique_pages" in state and state["unique_pages"]:
                urls = list(state["unique_pages"])
                logger.info(f"Loaded {len(urls)} unique URLs from file using unique_pages")
            else:
                for key in ["visited", "visited_urls", "pages"]:
                    if key in state and state[key]:
                        urls = list(state[key])
                        logger.info(f"Loaded {len(urls)} URLs from '{key}' key")
                        break
            
            # If no URLs found, use fallback
            if not urls and fallback_urls is not None:
                logger.warning("No URLs found in state file, using fallback")
                urls = fallback_urls
                
            # Remove duplicates and invalid URLs
            urls = [url for url in list(dict.fromkeys(urls)) if url and isinstance(url, str)]
            logger.info(f"Successfully loaded {len(urls)} unique URLs from state file")
            return urls
            
        except Exception as e:
            logger.exception(f"Error loading state file {state_file}: {e}")
            try:
                # Don't delete the file - it might be needed for troubleshooting
                logger.info(f"State file {state_file} could not be processed.")
            except Exception as unlink_e:
                logger.exception(f"Error handling file {state_file}: {unlink_e}")
            return fallback_urls if fallback_urls is not None else []
    else:
        logger.warning(f"State file {state_file} not found.")
        return fallback_urls if fallback_urls is not None else []
        
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((TimeoutException, WebDriverException))
)
def robust_driver_get(driver, url):
    """Load page with driver.get(url) with retry for errors."""
    driver.get(url)

def safe_pickle_dump(data, filename):
    """Save data safely to file."""
    tmpfile = filename + ".tmp"
    with open(tmpfile, "wb") as f:
        pickle.dump(data, f)
    os.replace(tmpfile, filename)
    logger.debug(f"State saved to '{tmpfile}' and replaced in '{filename}'.")

def load_urls_from_multi_domain_output(
    output_dir: str = None, 
    output_manager: 'OutputManager' = None,
    domains=None, 
    max_templates_per_domain=None, 
    fallback_urls=None
) -> list[str]:
    """
    Carica un URL rappresentativo per ogni template dal multi-domain crawler.
    
    Supporta sia l'uso di OutputManager per una gestione coerente dei path,
    sia il metodo tradizionale basato sul percorso di output del crawler.
    
    Args:
        output_dir: Directory di output del crawler (usato se output_manager è None)
        output_manager: Istanza di OutputManager per gestione centralizzata dei path
        domains: Lista o stringa separata da virgole con i domini da analizzare
        max_templates_per_domain: Numero massimo di template da analizzare per dominio
        fallback_urls: URL di fallback se non vengono trovati URL nei template
        
    Returns:
        Lista di URL unici da analizzare (uno per ogni template)
    """
    representative_urls = []
    
    # Determina la lista dei domini da analizzare
    if domains:
        domain_list = [d.strip() for d in domains.split(',')] if isinstance(domains, str) else domains
    elif output_manager:
        # Se c'è un output_manager, utilizza il suo dominio
        domain_list = [output_manager.domain_slug]
    else:
        # Altrimenti cerca tutte le cartelle di dominio nella directory di output
        output_path = Path(output_dir)
        domain_list = [d.name for d in output_path.glob("*") if d.is_dir() and not d.name.startswith('.')]
    
    logger.info(f"Ricerca URL rappresentativi per i domini: {domain_list}")
    
    for domain in domain_list:
        domain_templates = []
        
        # Usa OutputManager o path diretto a seconda di cosa è disponibile
        if output_manager:
            # Se abbiamo l'output_manager, usiamo il suo metodo per trovare i file di stato
            state_path = output_manager.get_crawler_state_path()
            if state_path and state_path.exists():
                logger.info(f"Utilizzo file di stato dal percorso gestito: {state_path}")
                try:
                    with open(state_path, 'rb') as f:
                        state = pickle.load(f)
                    
                    # Estrai i template dallo stato caricato
                    domain_templates.extend(_extract_templates_from_state(state, domain))
                except Exception as e:
                    logger.exception(f"Errore caricando il file di stato {state_path}: {e}")
        else:
            # Altrimenti, usa il comportamento tradizionale
            domain_dir = Path(output_dir) / domain
            
            # Priorità 1: Cerca i file di stato del crawler
            state_files = list(domain_dir.glob("crawler_state_*.pkl"))
            if state_files:
                latest_state = sorted(state_files)[-1]  # Ottieni il più recente
                logger.info(f"Utilizzo file di stato: {latest_state}")
                
                try:
                    with open(latest_state, 'rb') as f:
                        state = pickle.load(f)
                    
                    # Estrai i template dallo stato caricato
                    domain_templates.extend(_extract_templates_from_state(state, domain))
                except Exception as e:
                    logger.exception(f"Errore caricando il file di stato {latest_state}: {e}")
                    
        # Se non abbiamo trovato template nei file di stato, continua con la ricerca tradizionale
        if not domain_templates:
            if output_manager:
                # Cerca file JSON dei template usando OutputManager
                json_path = output_manager.find_latest_file("crawler", f"templates_{domain}_*.json")
                if json_path:
                    logger.info(f"Utilizzo file JSON: {json_path}")
                    domain_templates.extend(_extract_templates_from_json(json_path, domain))
                
                # Cerca file CSV dei template
                csv_path = output_manager.find_latest_file("crawler", f"templates_{domain}_*.csv")
                if csv_path and not domain_templates:
                    logger.info(f"Utilizzo file CSV: {csv_path}")
                    domain_templates.extend(_extract_templates_from_csv(csv_path))
            else:
                # Comportamento tradizionale - ricerca file nella directory del dominio
                domain_dir = Path(output_dir) / domain
                
                # Priorità 2: Cerca file template JSON
                json_files = list(domain_dir.glob("templates_*.json"))
                if json_files:
                    latest_json = sorted(json_files)[-1]  # Ottieni il più recente
                    logger.info(f"Utilizzo file JSON: {latest_json}")
                    domain_templates.extend(_extract_templates_from_json(latest_json, domain))
                
                # Priorità 3: Cerca template nei file CSV
                if not domain_templates:
                    csv_files = list(domain_dir.glob("templates_*.csv"))
                    if csv_files:
                        latest_csv = sorted(csv_files)[-1]  # Ottieni il più recente
                        logger.info(f"Utilizzo file CSV: {latest_csv}")
                        domain_templates.extend(_extract_templates_from_csv(latest_csv))
        
        # Ordina per conteggio (template più comuni prima)
        domain_templates.sort(key=lambda x: x['count'], reverse=True)
        
        # Limita il numero di template se specificato
        if max_templates_per_domain and len(domain_templates) > max_templates_per_domain:
            logger.info(f"Limitando il dominio {domain} a {max_templates_per_domain} template " +
                        f"(da {len(domain_templates)})")
            domain_templates = domain_templates[:max_templates_per_domain]
        
        # Estrai solo gli URL rappresentativi
        domain_urls = [template['url'] for template in domain_templates]
        logger.info(f"Trovati {len(domain_urls)} URL rappresentativi per il dominio {domain} " +
                    f"(uno per ciascuno dei {len(domain_templates)} template)")
        
        # Aggiungi metadati per debugging
        for i, (template, url) in enumerate(zip([t['template'] for t in domain_templates], domain_urls)):
            logger.debug(f"  {i+1}. Template: {template} -> URL: {url}")
        
        representative_urls.extend(domain_urls)
    
    # Rimuovi duplicati (nel caso in cui un URL rappresenti più template)
    unique_urls = list(dict.fromkeys(representative_urls))
    
    # Usa fallback se necessario
    if not unique_urls and fallback_urls:
        logger.info("Nessun URL rappresentativo trovato, utilizzo fallback.")
        unique_urls = fallback_urls
    
    logger.info(f"Totale: {len(unique_urls)} URL unici da analizzare (uno per template)")
    return unique_urls

def _extract_templates_from_state(state, domain):
    """
    Estrae le informazioni sui template da un file di stato del crawler.
    Supporta sia il formato nuovo che quello vecchio del multi_domain_crawler.
    
    Args:
        state: Stato del crawler caricato
        domain: Dominio corrente
        
    Returns:
        Lista di dizionari con informazioni sui template
    """
    templates = []
    
    # Gestisce il formato nuovo multi_domain_crawler
    if "domain_data" in state:
        for domain_name, data in state["domain_data"].items():
            if domain_name == domain or domain_name == f"{domain}:":  # Alcuni domini terminano con ':'
                if "structures" in data:
                    for template_key, template_data in data["structures"].items():
                        if isinstance(template_data, dict) and "url" in template_data:
                            templates.append({
                                'template': template_key,
                                'url': template_data['url'],
                                'count': template_data.get('count', 1)
                            })
    # Fallback al formato vecchio
    elif "structures" in state:
        for template_key, template_data in state["structures"].items():
            if isinstance(template_data, dict) and "url" in template_data:
                templates.append({
                    'template': template_key,
                    'url': template_data['url'],
                    'count': template_data.get('count', 1)
                })
    
    return templates

def _extract_templates_from_csv(csv_path):
    """
    Estrae le informazioni sui template da un file CSV.
    
    Args:
        csv_path: Percorso al file CSV
        
    Returns:
        Lista di dizionari con informazioni sui template
    """
    templates = []
    try:
        df = pd.read_csv(csv_path)
        if all(col in df.columns for col in ['template', 'example_url']):
            for _, row in df.iterrows():
                templates.append({
                    'template': row['template'],
                    'url': row['example_url'],
                    'count': row.get('count', 1)
                })
    except Exception as e:
        logger.exception(f"Errore caricando il file CSV {csv_path}: {e}")
    
    return templates

def _extract_templates_from_json(json_path, domain):
    """
    Estrae le informazioni sui template da un file JSON.
    
    Args:
        json_path: Percorso al file JSON
        domain: Dominio corrente
        
    Returns:
        Lista di dizionari con informazioni sui template
    """
    templates = []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'templates' in data:
                # Estrai template dal formato standard
                for template_key, template_data in data['templates'].items():
                    if isinstance(template_data, dict) and 'url' in template_data and 'count' in template_data:
                        templates.append({
                            'template': template_key,
                            'url': template_data['url'],
                            'count': template_data['count']
                        })
            elif 'domains' in data and domain in data['domains']:
                # Formato alternativo (report consolidato)
                for template_key, template_data in data['domains'][domain]['top_templates'].items():
                    if isinstance(template_data, dict) and 'url' in template_data:
                        templates.append({
                            'template': template_key,
                            'url': template_data['url'],
                            'count': template_data.get('count', 1)
                        })
    except Exception as e:
        logger.exception(f"Errore caricando il file JSON {json_path}: {e}")
    
    return templates

class AxeAnalysis:
    def __init__(
        self,
        urls: list[str] = None,
        analysis_state_file: str = None,
        crawler_output_dir: str = None,
        domains: str = None,
        max_templates_per_domain: int = None,
        fallback_urls: list[str] = None,
        pool_size: int = None,
        sleep_time: float = None,
        excel_filename: str = None,
        visited_file: str = None,
        headless: bool = None,
        resume: bool = None,
        output_folder: str = None,
        output_manager = None,
        auth_manager = None  # New parameter
    ) -> None:
        """
        Initialize the accessibility analysis on representative URLs for templates.
        
        Args:
            urls: List of URLs to analyze
            analysis_state_file: Path to crawler state file
            crawler_output_dir: Path to crawler output directory
            domains: Comma-separated list of domains
            max_templates_per_domain: Maximum number of templates per domain
            fallback_urls: URLs to use if no templates found
            pool_size: Number of webdrivers to use
            sleep_time: Time to sleep between requests
            excel_filename: Path to Excel output file
            visited_file: Path to visited URLs file
            headless: Whether to run browser in headless mode
            resume: Whether to resume from visited file
            output_folder: Path to output folder
            output_manager: Output manager instance
            auth_manager: Authentication manager instance
        """
        # Use output manager if provided
        self.output_manager = output_manager
        
        # Use configuration manager for defaults
        self.config = config_manager.get_nested("axe_config", {})
        
        # Override with instance-specific values if provided
        self.pool_size = pool_size if pool_size is not None else self.config.get("pool_size", 5)
        self.sleep_time = sleep_time if sleep_time is not None else self.config.get("sleep_time", 1.0)
        self.headless = headless if headless is not None else self.config.get("headless", True)
        self.resume = resume if resume is not None else self.config.get("resume", True)
        
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
        logger.info(f"{len(self.all_urls)} representative URLs will be analyzed.")

        # Determine paths from output manager if available
        if self.output_manager:
            self.visited_file = self.output_manager.get_path("axe", "visited_urls.txt")
            self.excel_filename = self.output_manager.get_path(
                "axe", f"accessibility_report_{self.output_manager.domain_slug}.xlsx")
            self.output_folder = str(self.output_manager.get_path("axe"))
        else:
            # Use provided paths or defaults from config
            domain_slug = self.config.get("domain_slug", "unknown")
            self.visited_file = Path(visited_file or self.config.get("visited_file", f"visited_urls_{domain_slug}.txt"))
            self.excel_filename = excel_filename or self.config.get("excel_filename", f"accessibility_report_{domain_slug}.xlsx")
            self.output_folder = output_folder or self.config.get("output_folder", "output_axe")
            
            # Create output directory if needed
            Path(self.output_folder).mkdir(parents=True, exist_ok=True)

        self.visited: set[str] = set()
        if self.resume:
            self._load_visited()
        else:
            logger.info("Resume mode disabled: ignoring visited state.")

        self.pending_urls = list(self.all_urls - self.visited)
        logger.info(f"{len(self.pending_urls)} pending URLs to process.")

        self.results: dict[str, list[dict]] = {}
        self.processed_count = 0
        
        # Store auth_manager
        self.auth_manager = auth_manager
        
        # If auth_manager is provided, log it
        if self.auth_manager:
            logger.info("Authentication manager provided, will be used for restricted areas")

    def _load_visited(self) -> None:
        """Load already processed URLs from the visited file."""
        if isinstance(self.visited_file, str):
            visited_path = Path(self.visited_file)
        else:
            visited_path = self.visited_file
            
        if visited_path.exists():
            try:
                with visited_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        url = line.strip()
                        if url:
                            self.visited.add(url)
                logger.info(f"Loaded {len(self.visited)} URLs from file '{visited_path}'.")
            except Exception as e:
                logger.exception(f"Error loading visited file: {e}")
        else:
            logger.debug(f"No visited file found at '{visited_path}'.")

    def _save_visited(self) -> None:
        """Save processed URLs to file."""
        try:
            if isinstance(self.visited_file, str):
                visited_path = Path(self.visited_file)
            else:
                visited_path = self.visited_file
                
            # Ensure parent directory exists
            visited_path.parent.mkdir(parents=True, exist_ok=True)
            
            with visited_path.open("w", encoding="utf-8") as f:
                for url in sorted(self.visited):
                    f.write(url + "\n")
            logger.info(f"Saved {len(self.visited)} URLs in '{visited_path}'.")
        except Exception as e:
            logger.exception(f"Error saving visited file: {e}")

    def _create_driver(self) -> webdriver.Chrome:
        """Create a new Chrome WebDriver."""
        options = ChromeOptions()
        
        # Set headless mode based on configuration
        if self.headless:
            options.add_argument("--headless")
            
        # Additional Chrome options for robustness
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--incognito")
        options.add_argument("--disable-dev-shm-usage")
        
        # Create temporary profile
        temp_profile = tempfile.mkdtemp()
        options.add_argument(f"--user-data-dir={temp_profile}")
        
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(5)
        driver.set_page_load_timeout(30)
        logger.debug("WebDriver created.")
        return driver

    async def _init_driver_pool(self) -> asyncio.Queue:
        """Create a pool of WebDrivers and put them in an async queue."""
        pool = asyncio.Queue()
        for _ in range(self.pool_size):
            driver = await asyncio.to_thread(self._create_driver)
            await pool.put(driver)
        logger.info(f"Pool of {self.pool_size} WebDrivers created.")
        return pool

    async def process_url(self, url: str, driver_pool: asyncio.Queue) -> None:
        """Process a single URL using a WebDriver from the pool."""
        logger.info(f"Starting analysis: {url}")
        driver = await driver_pool.get()
        try:
            # Check if authentication is needed
            auth_required = False
            if self.auth_manager and hasattr(self.auth_manager, 'is_auth_required'):
                auth_required = self.auth_manager.is_auth_required(url)
            
            # Apply authentication if needed
            if auth_required and self.auth_manager:
                if not self.auth_manager.is_authenticated:
                    await asyncio.to_thread(self.auth_manager.login)
                if self.auth_manager.is_authenticated:
                    await asyncio.to_thread(self.auth_manager.apply_auth_to_driver, driver)
                    logger.info(f"Applied authentication for {url}")

            await asyncio.to_thread(robust_driver_get, driver, url)
            await asyncio.sleep(self.sleep_time)
            axe = Axe(driver)
            for attempt in range(1, 4):
                try:
                    await asyncio.to_thread(axe.inject)
                    results = await asyncio.to_thread(axe.run)
                    break
                except Exception as e:
                    logger.exception(f"Error with axe on {url}, attempt {attempt}: {e}")
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
                        "failure_summary": node.get("failureSummary", ""),
                        "auth_required": auth_required  # Add authentication flag
                    }
                    issues.append(issue)
            
            self.results[url] = issues
            logger.info(f"{url}: {len(issues)} issues found.")
            self.visited.add(url)
            self.processed_count += 1
            if self.processed_count % AUTO_SAVE_INTERVAL == 0:
                self._save_visited()
        except Exception as e:
            logger.exception(f"Error processing {url}: {e}")
        finally:
            await driver_pool.put(driver)

    async def run(self) -> None:
        """Process all pending URLs using the driver pool."""
        if not self.pending_urls:
            logger.warning("No URLs to analyze!")
            return
            
        driver_pool = await self._init_driver_pool()
        tasks = [asyncio.create_task(self.process_url(url, driver_pool))
                 for url in self.pending_urls]
        logger.info(f"Starting {len(tasks)} analysis tasks...")
        await asyncio.gather(*tasks, return_exceptions=True)
        self._save_visited()
        # Close all drivers in the pool
        while not driver_pool.empty():
            driver = await driver_pool.get()
            await asyncio.to_thread(driver.quit)
        logger.info("All pool drivers have been closed.")

    def generate_excel_report(self) -> None:
        """Generate an Excel report from collected results, one sheet per page."""
        logger.info("Generating Excel report...")
        if not self.results:
            logger.warning("No results to export.")
            return
            
        # Support both string and Path objects for excel_filename
        if isinstance(self.excel_filename, str):
            excel_path = Path(self.excel_filename)
        else:
            excel_path = self.excel_filename
            
        # Ensure parent directory exists
        if not excel_path.parent.exists():
            try:
                excel_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory '{excel_path.parent}'.")
            except Exception as e:
                logger.exception(f"Error creating directory '{excel_path.parent}': {e}")
                return
        try:
            sheet_counter = {}  # For handling duplicate names
            
            with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
                for url, issues in self.results.items():
                    # Extract domain and path for sheet name
                    parsed = urlparse(url)
                    domain = parsed.netloc.replace("www.", "")
                    
                    # Extract the last segment of the path for the sheet name
                    path = parsed.path.rstrip('/')
                    if path:
                        last_segment = path.split('/')[-1]
                    else:
                        last_segment = "home"
                    
                    # Create base sheet name
                    base_name = f"{domain}_{last_segment}"
                    base_name = re.sub(r'[\\/*?:\[\]]', '_', base_name)[:28]  # Leave room for a number
                    
                    # Handle duplicates by adding a counter
                    if base_name in sheet_counter:
                        sheet_counter[base_name] += 1
                        sheet_name = f"{base_name}_{sheet_counter[base_name]}"
                    else:
                        sheet_counter[base_name] = 1
                        sheet_name = base_name
                    
                    # Limit to 31 characters (Excel max)
                    sheet_name = sheet_name[:31]
                    
                    df = pd.DataFrame(issues) if issues else pd.DataFrame(columns=[
                        "page_url", "violation_id", "impact", "description",
                        "help", "target", "html", "failure_summary"
                    ])
                    
                    # Add URL to first row if missing
                    if df.empty:
                        df = pd.DataFrame([{"page_url": url, "violation_id": "N/A", 
                                          "impact": "N/A", "description": "No issues detected"}])
                    
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    logger.debug(f"Sheet '{sheet_name}' created for {url}")
            
            # Rename headers to make them more readable
            rename_headers(str(excel_path), str(excel_path))
            
            logger.info(f"Excel report generated: '{excel_path}'")
            logger.info(f"Contains {len(self.results)} sheets, one for each representative URL analyzed")
            
        except Exception as e:
            logger.exception(f"Error generating Excel report: {e}")

    def start(self) -> None:
        """Start processing and generate the report when done."""
        # Initialize authentication if needed
        if self.auth_manager and not getattr(self.auth_manager, 'is_authenticated', False):
            logger.info("Logging in before starting accessibility analysis")
            self.auth_manager.login()
        
        # Continue with regular processing
        asyncio.run(self.run())
        self.generate_excel_report()

def main() -> None:
    """
    Example usage with the new multi-domain crawler:
    """
    # Initialize configuration
    config = config_manager.load_domain_config("sapglegal.com")
    
    crawler_output_dir = "/home/ec2-user/axeScraper/src/multi_domain_crawler/output_crawler"
    fallback_urls = [""]
    
    analyzer = AxeAnalysis(
        crawler_output_dir=crawler_output_dir,
        domains="sapglegal.com",  # Optional: limit to these domains
        max_templates_per_domain=config["axe_config"]["max_templates_per_domain"],
        fallback_urls=fallback_urls,
        pool_size=config["axe_config"]["pool_size"],
        sleep_time=config["axe_config"]["sleep_time"],
        excel_filename=config["axe_config"]["excel_filename"],
        visited_file=config["axe_config"]["visited_file"],
        headless=config["axe_config"]["headless"],
        resume=config["axe_config"]["resume"],
        output_folder=config["axe_config"]["output_folder"]
    )
    analyzer.start()

if __name__ == "__main__":
    main()