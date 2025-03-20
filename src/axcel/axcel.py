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
from ..utils.config_manager import ConfigurationManager
from ..utils.logging_config import get_logger
from ..utils.output_manager import OutputManager

# Initialize configuration manager
config_manager = ConfigurationManager(project_name="axeScraper")

# Set up logger with axe-specific configuration
logger = get_logger("axe_analysis", config_manager.get_logging_config()["components"]["axe_analysis"])

# Auto-save interval
AUTO_SAVE_INTERVAL = config_manager.get_int("CRAWLER_SAVE_INTERVAL", 5)

def load_urls_from_crawler_state(state_file: str, fallback_urls=None) -> list[str]:
    """
    Loads URLs from the crawler state file (pickle).
    Supports both old and new formats from multi_domain_crawler.
    """
    path = Path(state_file)
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
                        urls.extend([data["structures"][t]["url"] for t in data["structures"]])
                        logger.info(f"Loaded {len(urls)} URLs from templates in domain_data[{domain}]")
                        
            # Fallback to old format
            elif "structures" in state and state["structures"]:
                urls = [data["url"] for data in state["structures"].values()]
                logger.info(f"Loaded {len(urls)} unique URLs from file using the old format")
            elif "unique_pages" in state and state["unique_pages"]:
                urls = list(state["unique_pages"])
                logger.info(f"Loaded {len(urls)} unique URLs from file using unique_pages")
            else:
                urls = list(state.get("visited", []))
                logger.info(f"Loaded {len(urls)} URLs (all) from file")
            
            # If no URLs found, use fallback
            if not urls and fallback_urls is not None:
                logger.info("No URLs found, using fallback.")
                urls = fallback_urls
            return urls
        except Exception as e:
            logger.exception(f"Error loading state file {state_file}: {e}")
            try:
                path.unlink()
                logger.info(f"File {state_file} deleted due to corruption.")
            except Exception as unlink_e:
                logger.exception(f"Error deleting file {state_file}: {unlink_e}")
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

def load_urls_from_multi_domain_output(output_dir: str, domains=None, max_templates_per_domain=None, fallback_urls=None) -> list[str]:
    """
    Load one representative URL for each template from the multi-domain crawler.
    
    Supports the new multi_domain_crawler format with a different structure
    for storing templates and their information.
    """
    representative_urls = []
    output_path = Path(output_dir)
    
    # If specific domains are provided, use only those
    if domains:
        domain_list = [d.strip() for d in domains.split(',')] if isinstance(domains, str) else domains
    else:
        # Otherwise look for all domain folders in output_dir
        domain_list = [d.name for d in output_path.glob("*") if d.is_dir() and not d.name.startswith('.')]
    
    logger.info(f"Looking for representative URLs for domains: {domain_list}")
    
    for domain in domain_list:
        domain_templates = []
        domain_dir = output_path / domain
        
        # Priority 1: Look for crawler state files (for new multi_domain_crawler format)
        state_files = list(domain_dir.glob("crawler_state_*.pkl"))
        if state_files:
            latest_state = sorted(state_files)[-1]  # Get the most recent
            logger.info(f"Using crawler state file: {latest_state}")
            
            try:
                with open(latest_state, 'rb') as f:
                    state = pickle.load(f)
                
                # Handle new multi_domain_crawler format
                if "domain_data" in state:
                    for domain_name, data in state["domain_data"].items():
                        if domain_name == domain or domain_name == f"{domain}:":  # Some domains end with ':'
                            if "structures" in data:
                                for template_key, template_data in data["structures"].items():
                                    if isinstance(template_data, dict) and "url" in template_data:
                                        domain_templates.append({
                                            'template': template_key,
                                            'url': template_data['url'],
                                            'count': template_data.get('count', 1)
                                        })
                # Fallback to old format
                elif "structures" in state:
                    for template_key, template_data in state["structures"].items():
                        if isinstance(template_data, dict) and "url" in template_data:
                            domain_templates.append({
                                'template': template_key,
                                'url': template_data['url'],
                                'count': template_data.get('count', 1)
                            })
            except Exception as e:
                logger.exception(f"Error loading state file {latest_state}: {e}")

        # Continue with existing priorities if state format not recognized
        if not domain_templates:
            # Priority 2: Look for template JSON files
            json_files = list(domain_dir.glob("templates_*.json"))
            if json_files:
                latest_json = sorted(json_files)[-1]  # Get the most recent
                logger.info(f"Using template JSON file: {latest_json}")
                
                try:
                    with open(latest_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if 'templates' in data:
                            # Extract templates from standard format
                            for template_key, template_data in data['templates'].items():
                                if isinstance(template_data, dict) and 'url' in template_data and 'count' in template_data:
                                    domain_templates.append({
                                        'template': template_key,
                                        'url': template_data['url'],
                                        'count': template_data['count']
                                    })
                        elif 'domains' in data and domain in data['domains']:
                            # Alternative format (consolidated report)
                            for template_key, template_data in data['domains'][domain]['top_templates'].items():
                                if isinstance(template_data, dict) and 'url' in template_data:
                                    domain_templates.append({
                                        'template': template_key,
                                        'url': template_data['url'],
                                        'count': template_data.get('count', 1)
                                    })
                except Exception as e:
                    logger.exception(f"Error loading JSON file {latest_json}: {e}")
        
        # Priority 3: Look for templates in CSV files
        if not domain_templates:
            csv_files = list(domain_dir.glob("templates_*.csv"))
            if csv_files:
                latest_csv = sorted(csv_files)[-1]  # Get the most recent
                logger.info(f"Using CSV file: {latest_csv}")
                
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
                    logger.exception(f"Error loading CSV file {latest_csv}: {e}")
        
        # Sort by count (most common templates first)
        domain_templates.sort(key=lambda x: x['count'], reverse=True)
        
        # Limit number of templates if specified
        if max_templates_per_domain and len(domain_templates) > max_templates_per_domain:
            logger.info(f"Limiting domain {domain} to {max_templates_per_domain} templates " +
                        f"(from {len(domain_templates)})")
            domain_templates = domain_templates[:max_templates_per_domain]
        
        # Extract only representative URLs
        domain_urls = [template['url'] for template in domain_templates]
        logger.info(f"Found {len(domain_urls)} representative URLs for domain {domain} " +
                    f"(one for each of {len(domain_templates)} templates)")
        
        # Add metadata for debugging
        for i, (template, url) in enumerate(zip([t['template'] for t in domain_templates], domain_urls)):
            logger.debug(f"  {i+1}. Template: {template} -> URL: {url}")
        
        representative_urls.extend(domain_urls)
    
    # Remove duplicates (in case one URL represents multiple templates)
    unique_urls = list(dict.fromkeys(representative_urls))
    
    # Use fallback if needed
    if not unique_urls and fallback_urls:
        logger.info("No representative URLs found, using fallback.")
        unique_urls = fallback_urls
    
    logger.info(f"Total: {len(unique_urls)} unique URLs to analyze (one per template)")
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
        pool_size: int = None,
        sleep_time: float = None,
        excel_filename: str = None,
        visited_file: str = None,
        headless: bool = None,
        resume: bool = None,
        output_folder: str = None,
        output_manager = None
    ) -> None:
        """
        Initialize the accessibility analysis on representative URLs for templates.
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
                        "failure_summary": node.get("failureSummary", "")
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
            # Release the driver back to the pool for reuse
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
        asyncio.run(self.run())
        self.generate_excel_report()

def main() -> None:
    """
    Example usage with the new multi-domain crawler:
    """
    # Initialize configuration
    config = config_manager.load_domain_config("sapglegal.com")
    
    crawler_output_dir = "/home/ec2-user/axeScraper/src/multi_domain_crawler/output_crawler"
    fallback_urls = ["https://sapglegal.com/"]
    
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