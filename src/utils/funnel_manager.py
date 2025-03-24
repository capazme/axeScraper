# src/utils/funnel_manager.py
import logging
import time
import json
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from .auth_manager import AuthManager
from .config_manager import ConfigurationManager

class FunnelStep:
    """Rappresenta un singolo step in un funnel di accessibilità."""
    
    def __init__(
        self,
        name: str,
        actions: List[Dict[str, Any]],
        url: Optional[str] = None,
        wait_for_selector: Optional[str] = None,
        success_condition: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Inizializza uno step del funnel.
        
        Args:
            name: Nome identificativo dello step
            actions: Lista di azioni da eseguire
            url: URL da navigare (opzionale, altrimenti continua dalla pagina corrente)
            wait_for_selector: Selettore CSS da attendere prima di considerare la pagina caricata
            success_condition: Condizione per verificare il successo dello step
            description: Descrizione dello step
            timeout: Timeout in secondi
        """
        self.name = name
        self.actions = actions
        self.url = url
        self.wait_for_selector = wait_for_selector
        self.success_condition = success_condition
        self.description = description or name
        self.timeout = timeout
    
    def execute(self, driver: webdriver.Chrome, logger: logging.Logger) -> bool:
        """
        Esegue lo step del funnel.
        
        Args:
            driver: WebDriver Selenium
            logger: Logger per messaggi di debug
            
        Returns:
            True se lo step è stato completato con successo, False altrimenti
        """
        try:
            logger.info(f"Executing funnel step: {self.name}")
            
            # Se specificato, naviga a un URL
            if self.url:
                logger.info(f"Navigating to URL: {self.url}")
                driver.get(self.url)
            
            # Attendi che la pagina sia caricata
            if self.wait_for_selector:
                logger.debug(f"Waiting for selector: {self.wait_for_selector}")
                WebDriverWait(driver, self.timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, self.wait_for_selector))
                )
            else:
                # Attesa di base per il caricamento della pagina
                time.sleep(2)
            
            # Esegui le azioni specificate
            for action in self.actions:
                self._execute_action(driver, action, logger)
            
            # Verifica condizione di successo se specificata
            if self.success_condition:
                condition_type = self.success_condition.get('type')
                
                if condition_type == 'element_visible':
                    selector = self.success_condition.get('selector')
                    logger.debug(f"Checking success condition: element visible {selector}")
                    try:
                        WebDriverWait(driver, self.timeout).until(
                            EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        logger.info(f"Success condition met for step {self.name}")
                        return True
                    except TimeoutException:
                        logger.warning(f"Success condition failed: element not visible {selector}")
                        return False
                
                elif condition_type == 'url_contains':
                    text = self.success_condition.get('text')
                    logger.debug(f"Checking success condition: URL contains {text}")
                    if text in driver.current_url:
                        logger.info(f"Success condition met for step {self.name}")
                        return True
                    else:
                        logger.warning(f"Success condition failed: URL does not contain {text}")
                        return False
                        
                elif condition_type == 'text_present':
                    text = self.success_condition.get('text')
                    logger.debug(f"Checking success condition: text present {text}")
                    if text in driver.page_source:
                        logger.info(f"Success condition met for step {self.name}")
                        return True
                    else:
                        logger.warning(f"Success condition failed: text not present {text}")
                        return False
            
            # Se non ci sono condizioni di successo, considera lo step completato
            logger.info(f"Step {self.name} completed (no success condition)")
            return True
            
        except Exception as e:
            logger.error(f"Error executing funnel step {self.name}: {e}")
            return False
    
    def _execute_action(self, driver: webdriver.Chrome, action: Dict[str, Any], logger: logging.Logger) -> None:
        """
        Esegue una singola azione nel browser.
        
        Args:
            driver: WebDriver Selenium
            action: Dettagli dell'azione da eseguire
            logger: Logger per messaggi di debug
        """
        try:
            action_type = action.get('type')
            
            if action_type == 'click':
                selector = action.get('selector')
                logger.debug(f"Clicking element: {selector}")
                
                # Prima prova il metodo standard
                try:
                    element = WebDriverWait(driver, self.timeout).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    element.click()
                except WebDriverException:
                    # Se fallisce, prova con JavaScript click (più affidabile con overlay)
                    logger.debug(f"Standard click failed, trying JavaScript click")
                    element = WebDriverWait(driver, self.timeout).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", element)
            
            elif action_type == 'input':
                selector = action.get('selector')
                value = action.get('value', '')
                logger.debug(f"Inputting text to {selector}: {value}")
                element = WebDriverWait(driver, self.timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
                element.clear()
                element.send_keys(value)
            
            elif action_type == 'select':
                selector = action.get('selector')
                value = action.get('value', '')
                option_type = action.get('option_type', 'value')  # value, text, index
                logger.debug(f"Selecting option from {selector}: {value}")
                
                from selenium.webdriver.support.ui import Select
                element = WebDriverWait(driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                select = Select(element)
                
                if option_type == 'value':
                    select.select_by_value(value)
                elif option_type == 'text':
                    select.select_by_visible_text(value)
                elif option_type == 'index':
                    select.select_by_index(int(value))
            
            elif action_type == 'wait':
                seconds = action.get('seconds', 1)
                logger.debug(f"Waiting for {seconds} seconds")
                time.sleep(seconds)
            
            elif action_type == 'wait_for':
                selector = action.get('selector')
                logger.debug(f"Waiting for element: {selector}")
                WebDriverWait(driver, self.timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
            
            elif action_type == 'script':
                code = action.get('code', '')
                logger.debug(f"Executing JavaScript: {code[:50]}...")
                driver.execute_script(code)
                
            elif action_type == 'cookie_banner':
                logger.debug("Handling cookie banner")
                # Gestione specifica per banner cookie comuni
                selectors = [
                    "#onetrust-accept-btn-handler",
                    ".ot-sdk-container button",
                    ".cookie-banner button",
                    "button[aria-label*='cookie']",
                    "button[id*='cookie']",
                    "button[class*='cookie']",
                    "button[id*='accept']",
                    "button[class*='accept']",
                    "button.accept-cookies",
                    ".cookie-notice button",
                    ".cookie-policy button",
                    "#gdpr-banner button"
                ]
                
                for selector in selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.is_displayed():
                                logger.debug(f"Found cookie banner element: {selector}")
                                driver.execute_script("arguments[0].click();", element)
                                time.sleep(0.5)  # Breve attesa dopo il click
                                break
                    except Exception:
                        continue
            
            elif action_type == 'screenshot':
                filename = action.get('filename', f"screenshot_{int(time.time())}.png")
                logger.debug(f"Taking screenshot: {filename}")
                driver.save_screenshot(filename)
                
        except Exception as e:
            logger.warning(f"Error executing action {action}: {e}")

class Funnel:
    """Rappresenta un funnel completo con più step."""
    
    def __init__(
        self,
        name: str,
        steps: List[FunnelStep],
        description: Optional[str] = None,
        auth_required: bool = False,
        domain: Optional[str] = None
    ):
        """
        Inizializza un funnel.
        
        Args:
            name: Nome identificativo del funnel
            steps: Lista di step del funnel
            description: Descrizione del funnel
            auth_required: Se il funnel richiede autenticazione
            domain: Dominio associato al funnel
        """
        self.name = name
        self.steps = steps
        self.description = description or name
        self.auth_required = auth_required
        self.domain = domain
        self.results = []  # Per memorizzare i risultati delle analisi

class FunnelManager:
    """
    Gestisce i funnel di accessibilità definiti in configurazione.
    """
    
    def __init__(self, config_manager: Optional[ConfigurationManager] = None):
        """
        Inizializza il gestore dei funnel.
        
        Args:
            config_manager: Gestore della configurazione
        """
        self.config_manager = config_manager or ConfigurationManager(project_name="axeScraper")
        self.logger = logging.getLogger("funnel_manager")
        self.funnels = {}
        
        # Carica i funnel dalla configurazione
        self._load_funnels()
    
    def _load_funnels(self) -> None:
        """Carica i funnel dalla configurazione."""
        # Cerca funnel nella configurazione
        funnel_configs = self.config_manager.get_nested("FUNNELS", {})
        
        if not funnel_configs:
            self.logger.info("No funnels defined in configuration")
            return
            
        for funnel_name, funnel_config in funnel_configs.items():
            try:
                # Crea gli oggetti step
                steps = []
                for step_config in funnel_config.get('steps', []):
                    step = FunnelStep(
                        name=step_config.get('name', 'Unnamed Step'),
                        actions=step_config.get('actions', []),
                        url=step_config.get('url'),
                        wait_for_selector=step_config.get('wait_for_selector'),
                        success_condition=step_config.get('success_condition'),
                        description=step_config.get('description'),
                        timeout=step_config.get('timeout', 30)
                    )
                    steps.append(step)
                
                # Crea il funnel
                funnel = Funnel(
                    name=funnel_name,
                    steps=steps,
                    description=funnel_config.get('description', funnel_name),
                    auth_required=funnel_config.get('auth_required', False),
                    domain=funnel_config.get('domain')
                )
                
                self.funnels[funnel_name] = funnel
                self.logger.info(f"Loaded funnel: {funnel_name} with {len(steps)} steps")
                
            except Exception as e:
                self.logger.error(f"Error loading funnel {funnel_name}: {e}")
    
    def load_funnel_from_file(self, file_path: Union[str, Path]) -> Optional[str]:
        """
        Carica un funnel da un file di configurazione specifico.
        
        Args:
            file_path: Percorso al file di configurazione del funnel
            
        Returns:
            Nome del funnel caricato o None in caso di errore
        """
        path = Path(file_path)
        if not path.exists():
            self.logger.error(f"Funnel file not found: {file_path}")
            return None
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if path.suffix.lower() == '.json':
                    funnel_config = json.load(f)
                elif path.suffix.lower() in ('.yaml', '.yml'):
                    import yaml
                    funnel_config = yaml.safe_load(f)
                else:
                    self.logger.error(f"Unsupported file format: {path.suffix}")
                    return None
                
            # Estrai il funnel dal file
            if isinstance(funnel_config, dict) and 'name' in funnel_config:
                funnel_name = funnel_config['name']
                
                # Crea gli oggetti step
                steps = []
                for step_config in funnel_config.get('steps', []):
                    step = FunnelStep(
                        name=step_config.get('name', 'Unnamed Step'),
                        actions=step_config.get('actions', []),
                        url=step_config.get('url'),
                        wait_for_selector=step_config.get('wait_for_selector'),
                        success_condition=step_config.get('success_condition'),
                        description=step_config.get('description'),
                        timeout=step_config.get('timeout', 30)
                    )
                    steps.append(step)
                
                # Crea il funnel
                funnel = Funnel(
                    name=funnel_name,
                    steps=steps,
                    description=funnel_config.get('description', funnel_name),
                    auth_required=funnel_config.get('auth_required', False),
                    domain=funnel_config.get('domain')
                )
                
                self.funnels[funnel_name] = funnel
                self.logger.info(f"Loaded funnel from file: {funnel_name} with {len(steps)} steps")
                return funnel_name
                
            else:
                self.logger.error(f"Invalid funnel configuration in file {file_path}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error loading funnel from file {file_path}: {e}")
            return None
    
    def get_funnel(self, name: str) -> Optional[Funnel]:
        """
        Ottiene un funnel per nome.
        
        Args:
            name: Nome del funnel
            
        Returns:
            Funnel o None se non trovato
        """
        if name in self.funnels:
            return self.funnels[name]
        else:
            self.logger.warning(f"Funnel not found: {name}")
            return None
    
    def get_all_funnels(self) -> Dict[str, Funnel]:
        """
        Ottiene tutti i funnel disponibili.
        
        Returns:
            Dizionario di funnel disponibili
        """
        return self.funnels
    
    def get_funnels_for_domain(self, domain: str) -> Dict[str, Funnel]:
        """
        Ottiene tutti i funnel per un dominio specifico.
        
        Args:
            domain: Dominio per cui ottenere i funnel
            
        Returns:
            Dizionario di funnel per il dominio
        """
        return {name: funnel for name, funnel in self.funnels.items() 
                if funnel.domain is None or funnel.domain == domain}