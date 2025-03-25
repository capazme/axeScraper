# src/axcel/axe_auth_extensions.py
"""
Extensions to the AxeAnalysis class to support authenticated scanning
and funnel-based analysis.

This module extends the core functionality of the axe-core scanner
to analyze authenticated areas and user funnels.
"""

import os
import asyncio
import logging
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
import time
import json

from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium import webdriver
from axe_selenium_python import Axe

from utils.auth_manager import AuthManager
from utils.funnel_manager import FunnelManager
from utils.logging_config import get_logger

class AxeAuthScanner:
    """
    Extension to AxeAnalysis that adds support for authenticated scanning
    and funnel-based analysis.
    """
    
    def __init__(
        self,
        auth_config: Dict[str, Any],
        funnel_config: Dict[str, Any],
        output_manager,
        headless: bool = True,
        wait_time: float = 3.0
    ):
        """
        Initialize the authenticated scanner.
        
        Args:
            auth_config: Authentication configuration
            funnel_config: Funnel configuration
            output_manager: Output manager instance
            headless: Whether to run in headless mode
            wait_time: Wait time between actions
        """
        self.output_manager = output_manager
        self.logger = get_logger("axe_auth_scanner", output_manager=output_manager)
        self.headless = headless
        self.wait_time = wait_time
        
        # Initialize managers
        self.auth_manager = AuthManager(auth_config, output_manager)
        self.funnel_manager = FunnelManager(funnel_config, self.auth_manager, output_manager)
        
        # Initialize results storage
        self.results = {}
        self.visited_urls = set()
        
        self.logger.info("AxeAuthScanner initialized")
        self.logger.info(f"Authentication enabled: {self.auth_manager.enabled}")
        self.logger.info(f"Funnels defined: {len(self.funnel_manager.funnels)}")
    
    def _create_driver(self) -> webdriver.Chrome:
        """
        Create a Selenium WebDriver instance.
        
        Returns:
            WebDriver: Selenium WebDriver instance
        """
        options = ChromeOptions()
        
        if self.headless:
            options.add_argument("--headless")
            
        # Additional Chrome options for robustness
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        
        # Set window size to ensure elements are visible
        options.add_argument("--window-size=1920,1080")
        
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(5)
        driver.set_page_load_timeout(30)
        
        return driver
    
    def run_authenticated_scan(self, url: str) -> Dict[str, Any]:
        """
        Run an accessibility scan on an authenticated page.
        
        Args:
            url: URL to scan
            
        Returns:
            Dict: Scan results
        """
        self.logger.info(f"Running authenticated scan on {url}")
        
        driver = self._create_driver()
        results = {
            'url': url,
            'authenticated': False,
            'success': False,
            'violations': [],
            'error': None
        }
        
        try:
            # Authenticate
            if not self.auth_manager.ensure_authenticated(driver):
                results['error'] = "Authentication failed"
                return results
                
            results['authenticated'] = True
            
            # Navigate to the target URL
            driver.get(url)
            time.sleep(self.wait_time)
            
            # Run axe analysis
            axe = Axe(driver)
            axe.inject()
            axe_results = axe.run()
            
            # Process violations
            violations = []
            for violation in axe_results.get("violations", []):
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
                    violations.append(issue)
            
            results['violations'] = violations
            results['success'] = True
            
            self.logger.info(f"Authenticated scan complete: {url}, {len(violations)} violations found")
            
        except Exception as e:
            self.logger.error(f"Error during authenticated scan: {e}")
            results['error'] = str(e)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
                
        return results
    
    def run_funnel_scan(self, funnel_name: str) -> Dict[str, Any]:
        """
        Run an accessibility scan on a user funnel.
        
        Args:
            funnel_name: Name of the funnel to scan
            
        Returns:
            Dict: Funnel scan results
        """
        self.logger.info(f"Running funnel scan: {funnel_name}")
        
        funnel = self.funnel_manager.get_funnel(funnel_name)
        if not funnel:
            self.logger.error(f"Funnel not found: {funnel_name}")
            return {
                'name': funnel_name,
                'success': False,
                'error': 'Funnel not found',
                'steps': [],
                'violations_by_url': {}
            }
        
        driver = self._create_driver()
        results = {
            'name': funnel_name,
            'description': funnel.get('description', ''),
            'success': False,
            'steps_completed': 0,
            'total_steps': len(funnel.get('steps', [])),
            'steps': [],
            'violations_by_url': {},
            'error': None
        }
        
        try:
            # Execute the funnel
            funnel_results = self.funnel_manager.execute_funnel(driver, funnel_name)
            
            if not funnel_results['success']:
                results['error'] = funnel_results.get('error', 'Unknown funnel execution error')
                results['steps_completed'] = funnel_results.get('steps_completed', 0)
                return results
            
            # Record visited URLs during funnel execution
            visited_urls = funnel_results.get('visited_urls', [])
            self.visited_urls.update(visited_urls)
            
            # Scan each visited URL
            violations_by_url = {}
            for url in visited_urls:
                self.logger.info(f"Scanning URL from funnel: {url}")
                
                # Run axe analysis on this URL
                axe = Axe(driver)
                driver.get(url)
                time.sleep(self.wait_time)
                
                try:
                    axe.inject()
                    axe_results = axe.run()
                    
                    # Process violations
                    url_violations = []
                    for violation in axe_results.get("violations", []):
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
                            url_violations.append(issue)
                    
                    violations_by_url[url] = url_violations
                    self.logger.info(f"Scan complete for {url}: {len(url_violations)} violations found")
                    
                except Exception as e:
                    self.logger.error(f"Error running axe scan on {url}: {e}")
                    violations_by_url[url] = []
            
            results['violations_by_url'] = violations_by_url
            results['success'] = True
            
            # Prepare step results
            steps = []
            for i, step in enumerate(funnel.get('steps', [])):
                step_url = step.get('url', '')
                step_info = {
                    'name': step.get('name', f"Step {i+1}"),
                    'url': step_url,
                    'needs_authentication': step.get('needs_authentication', False),
                    'completed': i < results['steps_completed'],
                    'violations_count': len(violations_by_url.get(step_url, []))
                }
                steps.append(step_info)
            
            results['steps'] = steps
            self.logger.info(f"Funnel scan complete: {funnel_name}")
            
        except Exception as e:
            self.logger.error(f"Error during funnel scan: {e}")
            results['error'] = str(e)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
                
        return results
    
    def run_all_funnel_scans(self) -> Dict[str, Dict[str, Any]]:
        """
        Run accessibility scans on all defined funnels.
        
        Returns:
            Dict: Results for all funnel scans
        """
        results = {}
        
        for funnel_name in self.funnel_manager.list_funnels():
            self.logger.info(f"Starting scan for funnel: {funnel_name}")
            results[funnel_name] = self.run_funnel_scan(funnel_name)
            
        return results
    
    def export_results_to_excel(self, output_path: Optional[str] = None) -> str:
        """
        Export scan results to an Excel file.
        
        Args:
            output_path: Optional path for the Excel file
            
        Returns:
            str: Path to the generated Excel file
        """
        import pandas as pd
        
        if not output_path:
            # Generate default path using output manager
            excel_path = str(self.output_manager.get_path(
                "axe", f"auth_accessibility_report_{self.output_manager.domain_slug}.xlsx"))
        else:
            excel_path = output_path
            
        # Ensure parent directory exists
        Path(excel_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Collect all violations
        all_violations = []
        
        # Add violations from authenticated scans
        for url, scan_result in self.results.get('authenticated_scans', {}).items():
            all_violations.extend(scan_result.get('violations', []))
            
        # Add violations from funnel scans
        for funnel_name, funnel_result in self.results.get('funnel_scans', {}).items():
            for url, violations in funnel_result.get('violations_by_url', {}).items():
                for violation in violations:
                    # Add funnel information to the violation
                    violation['funnel_name'] = funnel_name
                    all_violations.append(violation)
        
        # Create DataFrame
        if all_violations:
            violations_df = pd.DataFrame(all_violations)
        else:
            # Create empty DataFrame with expected columns
            violations_df = pd.DataFrame(columns=[
                "page_url", "violation_id", "impact", "description",
                "help", "target", "html", "failure_summary", "funnel_name"
            ])
        
        # Save to Excel
        with pd.ExcelWriter(excel_path) as writer:
            violations_df.to_excel(writer, sheet_name="All Violations", index=False)
            
            # Create summary sheet
            summary_data = {
                'Metric': [
                    'Total Violations',
                    'Unique URLs Scanned',
                    'Authenticated Scans',
                    'Funnel Scans',
                    'Critical Violations',
                    'Serious Violations',
                    'Moderate Violations',
                    'Minor Violations',
                ],
                'Value': [
                    len(all_violations),
                    len(self.visited_urls),
                    len(self.results.get('authenticated_scans', {})),
                    len(self.results.get('funnel_scans', {})),
                    len([v for v in all_violations if v.get('impact') == 'critical']),
                    len([v for v in all_violations if v.get('impact') == 'serious']),
                    len([v for v in all_violations if v.get('impact') == 'moderate']),
                    len([v for v in all_violations if v.get('impact') == 'minor']),
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            
            # Create funnel summary sheet if there are funnel scans
            if self.results.get('funnel_scans'):
                funnel_data = []
                for funnel_name, result in self.results.get('funnel_scans', {}).items():
                    violation_count = sum(len(violations) for violations in result.get('violations_by_url', {}).values())
                    funnel_data.append({
                        'Funnel Name': funnel_name,
                        'Description': result.get('description', ''),
                        'Success': result.get('success', False),
                        'Steps Completed': result.get('steps_completed', 0),
                        'Total Steps': result.get('total_steps', 0),
                        'Total Violations': violation_count,
                        'URLs Scanned': len(result.get('violations_by_url', {})),
                        'Error': result.get('error', '')
                    })
                funnel_df = pd.DataFrame(funnel_data)
                funnel_df.to_excel(writer, sheet_name="Funnel Summary", index=False)
        
        self.logger.info(f"Results exported to {excel_path}")
        return excel_path
    
    def run(self) -> Dict[str, Any]:
        """
        Run the complete authenticated and funnel scanning workflow.
        
        Returns:
            Dict: Complete scan results
        """
        self.logger.info("Starting authenticated and funnel scanning")
        
        self.results = {
            'authenticated_scans': {},
            'funnel_scans': {},
        }
        
        # Run funnel scans if there are funnels defined
        if self.funnel_manager.funnels:
            self.logger.info(f"Running scans for {len(self.funnel_manager.funnels)} funnels")
            self.results['funnel_scans'] = self.run_all_funnel_scans()
        else:
            self.logger.info("No funnels defined, skipping funnel scans")
        
        # Export results
        output_path = self.export_results_to_excel()
        self.results['output_path'] = output_path
        
        self.logger.info("Authenticated and funnel scanning completed")
        return self.results