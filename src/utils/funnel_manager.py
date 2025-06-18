#!/usr/bin/env python3
"""
Funnel Manager for axeScraper

Manages the execution of predefined user journeys (funnels) through websites.
Supports step-by-step navigation with actions and success verification.
"""

import logging
import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException
from typing import Dict, Any, Optional, List, Union, Tuple

from utils.logging_config import get_logger
from utils.config_manager import ConfigurationManager
from utils.decorators import log_method

class FunnelManager:
    """
    Manager for defining and executing user funnels (specific paths through a website).
    Supports step-by-step navigation, actions, and success verification.
    """
    
    def __init__(
        self,
        config_manager: Optional[ConfigurationManager] = None,
        domain: Optional[str] = None,
        output_manager = None,
        auth_manager = None
    ):
        """
        Initialize the funnel manager.
        
        Args:
            config_manager: Configuration manager instance
            domain: Target domain for funnels
            output_manager: Output manager for managing files and directories
            auth_manager: Authentication manager for authenticated funnels
        """
        self.config_manager = config_manager or ConfigurationManager(project_name="axeScraper")
        self.domain = domain
        self.output_manager = output_manager
        self.auth_manager = auth_manager
        
        # Setup logger
        self.logger = get_logger("funnel_manager", 
                           self.config_manager.get_logging_config()["components"].get("funnel_manager", {}),
                           output_manager,
                           domain=self.domain)
        
        # Load funnel configuration
        self.funnel_config = self._load_funnel_config()
        
        # Initialize state
        self.driver = None
        self.all_visited_urls = set()
        
        self.logger.info("Funnel Manager initialized")
    
    @log_method
    def _load_funnel_config(self) -> Dict[str, Any]:
        """
        Load funnel configuration from config manager.
        
        Returns:
            Dictionary containing funnel configuration
        """
        funnel_enabled = self.config_manager.get_bool("FUNNEL_ANALYSIS_ENABLED", False)
        funnel_definition = self.config_manager.get("FUNNELS", {})
        
        # Validate funnel definitions
        if funnel_enabled and not funnel_definition:
            self.logger.warning("Funnel analysis is enabled but no funnels are defined")
        
        return {
            "enabled": funnel_enabled,
            "funnels": funnel_definition
        }
    
    def use_existing_driver(self, driver):
        """Use an existing driver instead of creating a new one."""
        self.driver = driver
        self.logger.info("Using existing driver for funnel execution")

    @log_method
    def initialize_driver(self, headless: bool = True) -> None:
        """
        Initialize Selenium webdriver for funnel execution.
        
        Args:
            headless: Whether to run the browser in headless mode
        """
        if self.driver is not None:
            return
            
        self.logger.info("Initializing funnel driver")
        
        try:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless")
            
            options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.cookies": 1,  # Accetta cookie
                "profile.block_third_party_cookies": False,
                "profile.default_content_settings.popups": 0,
                #"profile.managed_default_content_settings.images": 2  # Blocca immagini per velocizzare
            })  
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            self.driver.set_script_timeout(30)
            self.driver.set_page_load_timeout(60)
            
            self.logger.info("Funnel driver initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error initializing funnel driver: {e}")
            raise
    
    @log_method
    def perform_action(self, action: Dict[str, Any]) -> bool:
        """
        Perform a single action on the page during funnel execution.
        
        Args:
            action: Dictionary describing the action to perform
            
        Returns:
            True if action was performed successfully
        """
        if not self.driver:
            self.logger.error("Driver not initialized")
            return False
            
        try:
            action_type = action.get("type", "")
            context = {
                "action_type": action_type,
                "current_url": self.driver.current_url if self.driver else None,
                "action_params": action
            }
            self.logger.debug(f"Contesto azione: {json.dumps(context, indent=2)}")
            
            if action_type == "wait":
                seconds = action.get("seconds", 1)
                selector = action.get("selector", None)
                
                if selector:
                    self.logger.debug(f"Waiting for element: {selector}")
                    try:
                        WebDriverWait(self.driver, seconds).until(
                            EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    except TimeoutException:
                        self.logger.warning(f"Timeout waiting for element: {selector}")
                        return False
                else:
                    self.logger.debug(f"Waiting for {seconds} seconds")
                    time.sleep(seconds)
                
            elif action_type == "click":
                selector = action.get("selector", "")
                self.logger.debug(f"Clicking on element: {selector}")
                try:
                    element = WebDriverWait(self.driver, 20).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    # Scroll element into view before clicking
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)  # Small pause after scrolling
                    element.click()
                except ElementNotInteractableException:
                    # Try JavaScript click as fallback
                    self.logger.warning(f"Element not interactable, trying JavaScript click: {selector}")
                    element = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    self.driver.execute_script("arguments[0].click();", element)
                
            elif action_type == "input":
                selector = action.get("selector", "")
                value = action.get("value", "")
                self.logger.debug(f"Entering text in element: {selector}")
                element = WebDriverWait(self.driver, 20).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
                element.clear()
                element.send_keys(value)
                
            elif action_type == "select":
                selector = action.get("selector", "")
                value = action.get("value", "")
                self.logger.debug(f"Selecting option in element: {selector}")
                from selenium.webdriver.support.ui import Select
                element = WebDriverWait(self.driver, 20).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
                select = Select(element)
                select.select_by_value(value)
                
            elif action_type == "submit_form":
                selector = action.get("selector", "")
                self.logger.debug(f"Submitting form: {selector}")
                if selector:
                    element = WebDriverWait(self.driver, 20).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    element.submit()
                else:
                    self.driver.execute_script("document.querySelector('form').submit();")
                
            elif action_type == "screenshot":
                if self.output_manager:
                    filename = action.get("filename", f"funnel_{int(time.time())}.png")
                    file_path = self.output_manager.get_path("screenshots", filename)
                    self.output_manager.ensure_path_exists("screenshots")
                    self.driver.save_screenshot(str(file_path))
                    self.logger.debug(f"Screenshot saved to {file_path}")
                
            elif action_type == "script":
                code = action.get("code", "")
                self.logger.debug("Executing JavaScript")
                self.driver.execute_script(code)
                
            elif action_type == "cookie_banner":
                self.logger.debug("Handling cookie banner")
                cookie_script = """
                try {
                    var cookieButtons = document.querySelectorAll(
                        'button[id*="cookie"], button[class*="cookie"], ' +
                        'button[id*="consent"], button[class*="consent"], ' +
                        '#onetrust-accept-btn-handler, .cookie-banner .accept, ' +
                        '.cookie-notice .accept'
                    );
                    for(var i=0; i<cookieButtons.length; i++) {
                        if(cookieButtons[i].offsetParent !== null) {
                            cookieButtons[i].click();
                            return true;
                        }
                    }
                    return false;
                } catch(e) {
                    console.error("Error in cookie handling:", e);
                    return false;
                }
                """
                return self.driver.execute_script(cookie_script)
                
            else:
                self.logger.warning(f"Unknown action type: {action_type}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(
                f"Errore esecuzione azione:\n"
                f"Tipo: {action_type}\n"
                f"URL corrente: {self.driver.current_url if self.driver else 'N/A'}\n"
                f"Parametri: {json.dumps(action, indent=2)}\n"
                f"Errore: {str(e)}"
            )
            self.logger.exception("Stack trace completo:")
            return False
    
    @log_method
    def check_success_condition(self, condition: Dict[str, Any]) -> bool:
        """
        Check if a success condition is met.
        
        Args:
            condition: Dictionary describing the success condition
            
        Returns:
            True if the condition is met
        """
        if not self.driver or not condition:
            return False
            
        try:
            condition_type = condition.get("type", "")
            
            if condition_type == "element_visible":
                selector = condition.get("selector", "")
                self.logger.debug(f"Checking if element is visible: {selector}")
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    return True
                except TimeoutException:
                    self.logger.warning(f"Element not visible: {selector}")
                    return False
                    
            elif condition_type == "element_clickable":
                selector = condition.get("selector", "")
                self.logger.debug(f"Checking if element is clickable: {selector}")
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    return True
                except TimeoutException:
                    self.logger.warning(f"Element not clickable: {selector}")
                    return False
                    
            elif condition_type == "url_contains":
                text = condition.get("text", "")
                self.logger.debug(f"Checking if URL contains: {text}")
                return text in self.driver.current_url
                
            elif condition_type == "text_contains":
                text = condition.get("text", "")
                self.logger.debug(f"Checking if page contains text: {text}")
                return text in self.driver.page_source
                
            else:
                self.logger.warning(f"Unknown condition type: {condition_type}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error checking success condition: {e}")
            return False
    
    @log_method
    def save_screenshot(self, filename: str, subdirectory: Optional[str] = None) -> Optional[Path]:
        """
        Safely save a screenshot from the current driver state.
        
        Args:
            filename: Name of screenshot file
            subdirectory: Optional subdirectory under screenshots
            
        Returns:
            Path or None: Path to saved screenshot or None if failed
        """
        if not self.driver:
            self.logger.warning("Cannot save screenshot - driver not initialized")
            return None
            
        if not self.output_manager:
            self.logger.warning("Cannot save screenshot - no output manager")
            return None
            
        try:
            # Determine path with proper directory creation
            if subdirectory:
                screenshot_dir = self.output_manager.ensure_nested_path_exists("screenshots", subdirectory)
                screenshot_path = screenshot_dir / filename
            else:
                screenshot_dir = self.output_manager.ensure_path_exists("screenshots")
                screenshot_path = screenshot_dir / filename
            
            # Take the screenshot
            success = self.driver.save_screenshot(str(screenshot_path))
            
            if success:
                self.logger.info(f"Screenshot saved to: {screenshot_path}")
                return screenshot_path
            else:
                self.logger.warning(f"Failed to save screenshot to: {screenshot_path}")
                return None
        except Exception as e:
            self.logger.error(f"Error saving screenshot: {e}")
            return None

    @log_method
    def _set_ab_testing_cookies(self, params):
        """Set AB testing cookies with correct domain formats"""
        if not params:
            return
            
        current_url = self.driver.current_url
        from urllib.parse import urlparse
        domain = urlparse(current_url).netloc
        
        # Remove 'www.' prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
            
        domains_to_try = [
            f".{domain}",  # Most reliable for cross-subdomain
            domain,
            f"www.{domain}"
        ]
        
        self.logger.info(f"Setting AB testing cookies for {current_url}")
        
        for cookie_domain in domains_to_try:
            try:
                self.logger.info(f"Trying cookie domain: {cookie_domain}")
                
                if "version" in params:
                    self.driver.add_cookie({
                        "name": "ab_testing_version", 
                        "value": params["version"],
                        "domain": cookie_domain,
                        "path": "/"
                    })
                    
                if "code" in params:
                    self.driver.add_cookie({
                        "name": "ab_testing_code", 
                        "value": params["code"],
                        "domain": cookie_domain,
                        "path": "/"
                    })
                
                # Try localStorage as fallback
                try:
                    self.driver.execute_script(
                        f"localStorage.setItem('ab_testing_version', '{params.get('version', '')}');"
                    )
                    self.driver.execute_script(
                        f"localStorage.setItem('ab_testing_code', '{params.get('code', '')}');"
                    )
                    self.logger.info("Set AB testing parameters in localStorage")
                except Exception as ls_error:
                    self.logger.warning(f"Error setting localStorage: {ls_error}")
                    
            except Exception as e:
                self.logger.warning(f"Error setting cookies for {cookie_domain}: {e}")
        
        all_cookies = self.driver.get_cookies()
        self.logger.info(f"Cookies after setting ({len(all_cookies)}):")
        for cookie in all_cookies:
            self.logger.info(f"  {cookie['name']} = {cookie['value']} (domain: {cookie['domain']})")

    @log_method
    def execute_funnel(self, funnel_id: str) -> List[Tuple[str, str, bool]]:
        """
        Execute a funnel by navigating through its steps.
        
        Args:
            funnel_id: ID of the funnel to execute
            
        Returns:
            List of (step_name, url, success) tuples for each step in the funnel
        """
        if not self.funnel_config["enabled"]:
            self.logger.info("Funnel analysis is disabled")
            return []
            
        if funnel_id not in self.funnel_config["funnels"]:
            self.logger.error(f"Funnel not found: {funnel_id}")
            return []
            
        funnel = self.funnel_config["funnels"][funnel_id]
        self.logger.info(f"Executing funnel: {funnel_id} - {funnel.get('description', '')}")
        
        # Initialize driver if not already
        self.initialize_driver(headless=self.config_manager.get_bool("AXE_HEADLESS", True))
        
        # Memorizza i parametri di AB testing
        ab_testing_params = {}
        first_step_url = None
        
        # Trova l'URL del primo step per estrarre i parametri
        if funnel.get("steps") and funnel["steps"] and "url" in funnel["steps"][0]:
            first_step_url = funnel["steps"][0]["url"]
            
        if first_step_url and "ab-testing" in first_step_url:
            # Estrai i parametri dalla URL iniziale
            import urllib.parse
            self.logger.info(f"Analizzando parametri AB testing dalla URL: {first_step_url}")
            parsed_url = urllib.parse.urlparse(first_step_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if "code" in query_params:
                ab_testing_params["code"] = query_params["code"][0]
            if "version" in query_params:
                ab_testing_params["version"] = query_params["version"][0]
            self.logger.info(f"Rilevati parametri AB testing: {ab_testing_params}")
        else:
            self.logger.info("Nessun parametro AB testing rilevato nell'URL iniziale")

        # Handle authentication if required
        if funnel.get("auth_required", False) and self.auth_manager:
            self.logger.info(f"Funnel {funnel_id} requires authentication")
            if not self.auth_manager.is_authenticated:
                self.logger.info("Logging in for funnel execution")
                if not self.auth_manager.login():
                    self.logger.error(f"Cannot execute funnel {funnel_id} - Authentication failed")
                    return []
            
            # Apply authentication to this driver
            self.auth_manager.apply_auth_to_driver(self.driver)
        else:
            self.logger.info(f"Funnel {funnel_id} does not require authentication")
        
        # Track results for each step
        results = []
        
        # Create funnel results directory safely
        if self.output_manager:
            try:
                funnel_dir = self.output_manager.ensure_nested_path_exists("funnels", funnel_id)
                self.logger.info(f"Created funnel directory: {funnel_dir}")
            except Exception as e:
                self.logger.error(f"Error creating funnel directory: {e}")
                return []
        
        # Execute each step
        for i, step in enumerate(funnel.get("steps", [])):
            step_name = step.get("name", f"Step {i+1}")
            step_url = step.get("url", None)
            
            self.logger.info(f"Executing step {i+1}/{len(funnel.get('steps', []))}: {step_name}")
            self.logger.info(f"Step URL originale: {step_url}")
            
            try:
                # Navigate to URL if specified
                if step_url:
                    # Aggiungi parametri AB testing se necessario
                    if ab_testing_params and "ab-testing" not in step_url:
                        params = "&".join([f"{k}={v}" for k, v in ab_testing_params.items()])
                        if "?" in step_url:
                            step_url = f"{step_url}&{params}"
                        else:
                            step_url = f"{step_url}?{params}"
                        self.logger.info(f"URL modificato con parametri AB testing: {step_url}")
                    self.logger.info(f"Navigando a {step_url}")
                    self.driver.get(step_url)
                    
                    # Dopo il caricamento, controlla l'URL effettivo
                    actual_url = self.driver.current_url
                    self.logger.info(f"URL effettivamente caricato: {actual_url}")
                    
                    # Imposta cookie AB testing solo nel primo step (i == 0)
                    if i == 0 and "ab-testing" in step_url:
                        self.logger.info("Impostazione manuale dei cookie di AB testing")
                        
                        # Prova con entrambi i formati di dominio per essere sicuri
                        domains_to_try = ["locautorent.com", ".locautorent.com", "www.locautorent.com"]
                        
                        for domain in domains_to_try:
                            try:
                                self.logger.info(f"Tentativo con dominio cookie: {domain}")
                                self.driver.add_cookie({
                                    "name": "ab_testing_version", 
                                    "value": "v1",
                                    "domain": domain
                                })
                                self.driver.add_cookie({
                                    "name": "ab_testing_code", 
                                    "value": "9N0C47hqP2o5HTU4QhPx0K1b",
                                    "domain": domain
                                })
                                self.logger.info(f"Cookie impostati con successo per dominio: {domain}")
                            except Exception as e:
                                self.logger.warning(f"Errore impostando cookie per dominio {domain}: {e}")
                        
                        # Ricarica la pagina per applicare i cookie
                        self.logger.info("Ricaricando la pagina per applicare i cookie")
                        self.driver.refresh()
                        
                        # Verifica l'URL dopo il refresh
                        post_refresh_url = self.driver.current_url
                        self.logger.info(f"URL dopo refresh: {post_refresh_url}")
                        
                        # Controlla se ci sono cookie impostati
                        all_cookies = self.driver.get_cookies()
                        self.logger.info(f"Cookie presenti dopo refresh: {len(all_cookies)}")
                        for cookie in all_cookies:
                            self.logger.info(f"Cookie: {cookie['name']} = {cookie['value']} (domain: {cookie['domain']})")
                
                # Wait for a specific element if needed
                wait_selector = step.get("wait_for_selector", None)
                if wait_selector:
                    self.logger.info(f"Attesa elemento con selettore: {wait_selector}")
                    try:
                        WebDriverWait(self.driver, 30).until(
                            EC.visibility_of_element_located((By.CSS_SELECTOR, wait_selector))
                        )
                        self.logger.info(f"Elemento trovato: {wait_selector}")
                    except TimeoutException:
                        self.logger.warning(f"Timeout attesa elemento: {wait_selector}")
                
                # Take screenshot at step start
                if self.output_manager:
                    screenshot_path = self.save_screenshot(
                        f"step_{i+1}_start.png",
                        subdirectory=f"funnels/{funnel_id}"
                    )
                    self.logger.info(f"Screenshot iniziale salvato: {screenshot_path}")

                # Execute actions
                for j, action in enumerate(step.get("actions", [])):
                    action_type = action.get("type", "unknown")
                    self.logger.info(f"Esecuzione azione {j+1} di tipo '{action_type}'")
                    if not self.perform_action(action):
                        self.logger.warning(f"Azione {j+1} ({action_type}) fallita nello step {step_name}")
                    else:
                        self.logger.info(f"Azione {j+1} ({action_type}) completata con successo")
                    
                    # Small pause between actions
                    time.sleep(0.5)
                
                # Take screenshot after actions
                if self.output_manager:
                    screenshot_path = self.save_screenshot(
                        f"step_{i+1}_end.png",
                        subdirectory=f"funnels/{funnel_id}"
                    )
                    self.logger.info(f"Screenshot finale salvato: {screenshot_path}")
                
                # Check success condition
                success_condition = step.get("success_condition", None)
                if success_condition:
                    condition_type = success_condition.get("type", "unknown")
                    self.logger.info(f"Verifica condizione di successo di tipo '{condition_type}'")
                    success = self.check_success_condition(success_condition)
                    self.logger.info(f"Condizione di successo: {'Soddisfatta' if success else 'Non soddisfatta'}")
                else:
                    success = True
                    self.logger.info("Nessuna condizione di successo specificata, step considerato riuscito")
                
                # Record URL for accessibility analysis
                current_url = self.driver.current_url
                self.logger.info(f"URL finale step: {current_url}")
                self.all_visited_urls.add(current_url)
                
                # Record result
                results.append((step_name, current_url, success))
                self.logger.info(f"Step {step_name} {'completato con successo' if success else 'fallito'}")
                
                # Save current page source for later analysis
                if self.output_manager:
                    try:
                        page_source = self.driver.page_source
                        safe_name = step_name.lower().replace(' ', '_').replace('/', '_')
                        page_source_path = funnel_dir / f"step_{i+1}_{safe_name}.html"
                        
                        success = self.output_manager.safe_write_file(
                            page_source_path,
                            page_source
                        )
                        if success:
                            self.logger.info(f"Sorgente HTML salvato: {page_source_path}")
                    except Exception as e:
                        self.logger.error(f"Errore nel salvataggio del sorgente HTML: {e}")
                
                # Check if we should continue
                if not success:
                    self.logger.warning(f"Step {step_name} fallito, esecuzione funnel interrotta")
                    break
                    
                # Wait before next step
                step_timeout = step.get("timeout", 30)
                self.logger.info(f"Pausa di 2 secondi prima del prossimo step")
                time.sleep(2)  # Small pause between steps
                
            except Exception as e:
                self.logger.error(f"Errore durante l'esecuzione dello step {step_name}: {e}")
                self.logger.exception("Dettaglio errore:")
                current_url = self.driver.current_url if self.driver else "unknown"
                results.append((step_name, current_url, False))
                break
        
        # Save funnel results
        if self.output_manager:
            try:
                results_data = json.dumps([
                    {"step": name, "url": url, "success": success} 
                    for name, url, success in results
                ], indent=2)
                
                results_path = funnel_dir / "results.json"
                success = self.output_manager.safe_write_file(results_path, results_data)
                
                if success:
                    self.logger.info(f"Risultati funnel salvati in: {results_path}")
            except Exception as e:
                self.logger.error(f"Errore nel salvataggio dei risultati funnel: {e}")
        
        # Log results
        success_count = sum(1 for _, _, success in results if success)
        self.logger.info(f"Funnel {funnel_id} completato: {success_count}/{len(results)} step riusciti")
        
        # Driver cleanup
        try:
            all_cookies = self.driver.get_cookies()
            self.logger.info(f"Stato finale dei cookie ({len(all_cookies)}):")
            for cookie in all_cookies:
                self.logger.info(f"  {cookie['name']} = {cookie['value']} (domain: {cookie['domain']})")
        except Exception as e:
            self.logger.warning(f"Impossibile ottenere i cookie finali: {e}")
        
        return results
    
    def get_available_funnels(self, domain_slug: Optional[str] = None) -> List[str]:
        """
        Get IDs of available funnels for a domain.
        
        Args:
            domain_slug: Domain slug to filter funnels
            
        Returns:
            List of funnel IDs available for the domain
        """
        if not self.funnel_config["enabled"]:
            return []
            
        if not domain_slug:
            domain_slug = self.config_manager.domain_to_slug(self.domain) if self.domain else None
            
        available_funnels = []
        
        for funnel_id, funnel in self.funnel_config["funnels"].items():
            funnel_domain = funnel.get("domain", None)
            if funnel_domain == domain_slug or funnel_domain is None:
                available_funnels.append(funnel_id)
                
        return available_funnels
    
    def get_all_visited_urls(self) -> List[str]:
        """
        Get all URLs visited during funnel execution.
        
        Returns:
            List of all URLs visited during funnel execution
        """
        return list(self.all_visited_urls)
    
    def close(self) -> None:
        """Close the funnel driver and clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("Funnel driver closed")
            except Exception as e:
                self.logger.error(f"Error closing funnel driver: {e}")
            finally:
                self.driver = None