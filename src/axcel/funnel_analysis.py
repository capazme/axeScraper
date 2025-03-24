# src/axcel/funnel_analysis.py
import asyncio
import logging
import time
import tempfile
import json
from typing import Dict, List, Any, Optional, Set, Tuple
from pathlib import Path
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from axe_selenium_python import Axe

from utils.funnel_manager import FunnelManager, Funnel, FunnelStep
from utils.auth_manager import AuthManager
from utils.config_manager import ConfigurationManager
from utils.output_manager import OutputManager

# Setup logger
config_manager = ConfigurationManager(project_name="axeScraper")
logger = logging.getLogger("funnel_analysis")

class FunnelAnalysisResult:
    """Risultato dell'analisi di un funnel."""
    
    def __init__(
        self,
        funnel_name: str,
        domain: str,
        steps_results: Dict[str, Dict[str, Any]],
        total_violations: int = 0,
        critical_violations: int = 0,
        serious_violations: int = 0,
        passed_steps: int = 0,
        total_steps: int = 0
    ):
        """
        Inizializza il risultato dell'analisi.
        
        Args:
            funnel_name: Nome del funnel analizzato
            domain: Dominio analizzato
            steps_results: Risultati per ogni step
            total_violations: Numero totale di violazioni
            critical_violations: Numero di violazioni critiche
            serious_violations: Numero di violazioni serie
            passed_steps: Numero di step completati con successo
            total_steps: Numero totale di step
        """
        self.funnel_name = funnel_name
        self.domain = domain
        self.steps_results = steps_results
        self.total_violations = total_violations
        self.critical_violations = critical_violations
        self.serious_violations = serious_violations
        self.passed_steps = passed_steps
        self.total_steps = total_steps
        self.completion_rate = (passed_steps / total_steps * 100) if total_steps > 0 else 0

class FunnelAccessibilityAnalyzer:
    """
    Analizzatore di accessibilità basato su funnel.
    """
    
    def __init__(
        self,
        funnel_manager: Optional[FunnelManager] = None,
        auth_manager: Optional[AuthManager] = None,
        output_manager: Optional[OutputManager] = None,
        headless: bool = True,
        pool_size: int = 1  # Per i funnel, un pool di 1 è più stabile
    ):
        """
        Inizializza l'analizzatore di funnel.
        
        Args:
            funnel_manager: Gestore dei funnel
            auth_manager: Gestore dell'autenticazione
            output_manager: Gestore dell'output
            headless: Se eseguire in modalità headless
            pool_size: Dimensione del pool di driver
        """
        self.funnel_manager = funnel_manager or FunnelManager()
        self.auth_manager = auth_manager
        self.output_manager = output_manager
        self.headless = headless
        self.pool_size = pool_size
        
        # Per memorizzare risultati
        self.results = {}
    
    def _create_driver(self) -> webdriver.Chrome:
        """Crea un nuovo driver Chrome."""
        options = ChromeOptions()
        
        if self.headless:
            options.add_argument("--headless")
            
        # Opzioni aggiuntive per robustezza
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")  # Dimensione schermo ragionevole
        
        # Profilo temporaneo
        temp_profile = tempfile.mkdtemp()
        options.add_argument(f"--user-data-dir={temp_profile}")
        
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(10)
        
        return driver
    
    async def analyze_funnel(self, funnel_name: str) -> Optional[FunnelAnalysisResult]:
        """
        Analizza un funnel di accessibilità.
        
        Args:
            funnel_name: Nome del funnel da analizzare
            
        Returns:
            Risultato dell'analisi o None in caso di errore
        """
        # Ottieni il funnel
        funnel = self.funnel_manager.get_funnel(funnel_name)
        if not funnel:
            logger.error(f"Funnel not found: {funnel_name}")
            return None
            
        try:
            # Crea il driver
            driver = await asyncio.to_thread(self._create_driver)
            
            # Prepara variabili di risultato
            steps_results = {}
            total_violations = 0
            critical_violations = 0
            serious_violations = 0
            passed_steps = 0
            
            # Autentica se necessario
            authenticated = False
            if funnel.auth_required and self.auth_manager and funnel.domain:
                try:
                    logger.info(f"Authenticating for domain: {funnel.domain}")
                    authenticated = await asyncio.to_thread(
                        self.auth_manager.authenticate, 
                        funnel.domain, 
                        driver
                    )
                    if authenticated:
                        logger.info(f"Authentication successful for domain: {funnel.domain}")
                    else:
                        logger.warning(f"Authentication failed for domain: {funnel.domain}")
                except Exception as e:
                    logger.error(f"Error during authentication: {e}")
            
            # Esegui ogni step del funnel
            for i, step in enumerate(funnel.steps):
                logger.info(f"Starting funnel step {i+1}/{len(funnel.steps)}: {step.name}")
                
                # Esegui lo step
                step_success = await asyncio.to_thread(step.execute, driver, logger)
                
                # Analizza accessibilità
                violations = await self._analyze_accessibility(driver, step.name)
                
                # Calcola statistiche dello step
                step_total_violations = len(violations)
                step_critical = sum(1 for v in violations if v.get('impact') == 'critical')
                step_serious = sum(1 for v in violations if v.get('impact') == 'serious')
                
                # Aggiorna le statistiche totali
                total_violations += step_total_violations
                critical_violations += step_critical
                serious_violations += step_serious
                if step_success:
                    passed_steps += 1
                
                # Salva i risultati dello step
                steps_results[step.name] = {
                    'success': step_success,
                    'url': driver.current_url,
                    'violations': violations,
                    'total_violations': step_total_violations,
                    'critical_violations': step_critical,
                    'serious_violations': step_serious,
                    'area_type': 'restricted' if authenticated else 'public'
                }
                
                # Se lo step fallisce, salta i successivi
                if not step_success:
                    logger.warning(f"Step failed: {step.name}. Skipping remaining steps.")
                    
                    # Aggiungi step falliti al risultato con violazioni vuote
                    for j in range(i+1, len(funnel.steps)):
                        skipped_step = funnel.steps[j]
                        steps_results[skipped_step.name] = {
                            'success': False,
                            'url': None,
                            'violations': [],
                            'total_violations': 0,
                            'critical_violations': 0,
                            'serious_violations': 0,
                            'area_type': 'restricted' if authenticated else 'public',
                            'skipped': True
                        }
                    
                    break
            
            # Crea il risultato
            result = FunnelAnalysisResult(
                funnel_name=funnel_name,
                domain=funnel.domain or '',
                steps_results=steps_results,
                total_violations=total_violations,
                critical_violations=critical_violations,
                serious_violations=serious_violations,
                passed_steps=passed_steps,
                total_steps=len(funnel.steps)
            )
            
            # Salva il risultato
            self.results[funnel_name] = result
            
            # Chiudi il driver
            await asyncio.to_thread(driver.quit)
            
            return result
            
        except Exception as e:
            logger.exception(f"Error analyzing funnel {funnel_name}: {e}")
            return None
    
    async def _analyze_accessibility(self, driver: webdriver.Chrome, step_name: str) -> List[Dict[str, Any]]:
        """
        Analizza l'accessibilità della pagina corrente.
        
        Args:
            driver: WebDriver Chrome
            step_name: Nome dello step per riferimento
            
        Returns:
            Lista di violazioni di accessibilità
        """
        try:
            # Inizializza Axe
            axe = Axe(driver)
            
            # Inietta lo script axe-core
            await asyncio.to_thread(axe.inject)
            
            # Esegui l'analisi
            results = await asyncio.to_thread(axe.run)
            
            # Estrai le violazioni
            violations = []
            for violation in results.get("violations", []):
                for node in violation.get("nodes", []):
                    issue = {
                        "step": step_name,
                        "page_url": driver.current_url,
                        "violation_id": violation.get("id", ""),
                        "impact": violation.get("impact", ""),
                        "description": violation.get("description", ""),
                        "help": violation.get("help", ""),
                        "target": ", ".join([", ".join(x) if isinstance(x, list) else x for x in node.get("target", [])]),
                        "html": node.get("html", ""),
                        "failure_summary": node.get("failureSummary", "")
                    }
                    violations.append(issue)
            
            logger.info(f"{step_name}: {len(violations)} accessibility issues found")
            return violations
            
        except Exception as e:
            logger.error(f"Error analyzing accessibility: {e}")
            return []
    
    def generate_excel_report(self, funnel_name: str, output_path: Optional[str] = None) -> Optional[str]:
        """
        Genera un report Excel per un funnel.
        
        Args:
            funnel_name: Nome del funnel
            output_path: Percorso di output (opzionale)
            
        Returns:
            Percorso del file Excel generato o None in caso di errore
        """
        # Verifica che esista il risultato
        if funnel_name not in self.results:
            logger.error(f"No results for funnel: {funnel_name}")
            return None
            
        result = self.results[funnel_name]
        
        # Genera il percorso di output se non specificato
        if not output_path:
            if self.output_manager:
                output_path = str(self.output_manager.get_path(
                    "analysis", f"funnel_{funnel_name}_{int(time.time())}.xlsx"))
            else:
                output_path = f"funnel_{funnel_name}_{int(time.time())}.xlsx"
        
        try:
            # Crea il writer Excel
            with pd.ExcelWriter(output_path) as writer:
                # Sheet di panoramica
                summary_data = {
                    "Funnel Name": [result.funnel_name],
                    "Domain": [result.domain],
                    "Completion Rate": [f"{result.completion_rate:.1f}%"],
                    "Steps Passed": [f"{result.passed_steps}/{result.total_steps}"],
                    "Total Violations": [result.total_violations],
                    "Critical Violations": [result.critical_violations],
                    "Serious Violations": [result.serious_violations]
                }
                pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
                
                # Sheet per step
                steps_data = []
                for step_name, step_result in result.steps_results.items():
                    steps_data.append({
                        "Step Name": step_name,
                        "Success": "Yes" if step_result['success'] else "No",
                        "URL": step_result['url'] or "N/A",
                        "Total Violations": step_result['total_violations'],
                        "Critical Violations": step_result['critical_violations'],
                        "Serious Violations": step_result['serious_violations'],
                        "Area Type": step_result['area_type'],
                        "Skipped": "Yes" if step_result.get('skipped', False) else "No"
                    })
                pd.DataFrame(steps_data).to_excel(writer, sheet_name="Steps", index=False)
                
                # Sheet per violazioni
                all_violations = []
                for step_name, step_result in result.steps_results.items():
                    for violation in step_result['violations']:
                        violation['step_name'] = step_name
                        all_violations.append(violation)
                
                if all_violations:
                    pd.DataFrame(all_violations).to_excel(writer, sheet_name="Violations", index=False)
            
            logger.info(f"Excel report generated: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error generating Excel report: {e}")
            return None
    
    async def analyze_multiple_funnels(self, funnel_names: List[str]) -> Dict[str, FunnelAnalysisResult]:
        """
        Analizza multipli funnel in sequenza.
        
        Args:
            funnel_names: Lista di nomi dei funnel da analizzare
            
        Returns:
            Dizionario di risultati per funnel
        """
        results = {}
        
        for funnel_name in funnel_names:
            result = await self.analyze_funnel(funnel_name)
            if result:
                results[funnel_name] = result
        
        return results
    
    def get_results(self) -> Dict[str, FunnelAnalysisResult]:
        """
        Ottiene tutti i risultati dell'analisi.
        
        Returns:
            Dizionario di risultati per funnel
        """
        return self.results