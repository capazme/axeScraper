#!/usr/bin/env python3
"""
Authentication Manager for axeScraper

Handles website authentication to enable accessibility testing of protected areas.
Supports form-based authentication with cookie persistence for session management.
"""

import logging
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from typing import Dict, Any, Optional, List, Union

from utils.logging_config import get_logger
from utils.config_manager import ConfigurationManager

class AuthenticationManager:
    """
    Manager for website authentication using Selenium.
    Supports form-based authentication and session management.
    """
    
    def __init__(
        self,
        config_manager: Optional[ConfigurationManager] = None,
        domain: Optional[str] = None,
        output_manager = None
    ):
        """
        Initialize the authentication manager.
        
        Args:
            config_manager: Configuration manager instance
            domain: Target domain for authentication
            output_manager: Output manager for managing files and directories
        """
        self.config_manager = config_manager or ConfigurationManager(project_name="axeScraper")
        self.domain = domain
        self.output_manager = output_manager
        
        # Setup logger
        self.logger = get_logger("auth_manager", 
                           self.config_manager.get_logging_config()["components"].get("auth_manager", {}),
                           output_manager)
        
        # Load auth configuration
        self.auth_config = self._load_auth_config()
        
        # Initialize state
        self.driver = None
        self.is_authenticated = False
        self.cookies = None
        self.authenticated_urls = []
        
        self.logger.info("Authentication Manager initialized")
    
    def _load_auth_config(self) -> Dict[str, Any]:
        """
        Load authentication configuration from config manager.
        
        Returns:
            Dictionary containing authentication configuration
        """
        auth_config = {
            "enabled": self.config_manager.get_bool("AUTH_ENABLED", False),
            "strategy": self.config_manager.get("AUTH_STRATEGY", "form"),
            "login_url": self.config_manager.get("AUTH_LOGIN_URL", ""),
            "username": self.config_manager.get("AUTH_USERNAME", ""),
            "password": self.config_manager.get("AUTH_PASSWORD", ""),
            "username_selector": self.config_manager.get("AUTH_USERNAME_SELECTOR", ""),
            "password_selector": self.config_manager.get("AUTH_PASSWORD_SELECTOR", ""),
            "submit_selector": self.config_manager.get("AUTH_SUBMIT_SELECTOR", ""),
            "success_indicator": self.config_manager.get("AUTH_SUCCESS_INDICATOR", ""),
            "error_indicator": self.config_manager.get("AUTH_ERROR_INDICATOR", ""),
            "pre_login_actions": self.config_manager.get("AUTH_PRE_LOGIN_ACTIONS", []),
            "post_login_actions": self.config_manager.get("AUTH_POST_LOGIN_ACTIONS", []),
            "domains": self.config_manager.get("AUTH_DOMAINS", {})
        }
        
        # Validate required fields
        if auth_config["enabled"]:
            missing_fields = []
            for field in ["login_url", "username", "password", "username_selector", "password_selector", "submit_selector"]:
                if not auth_config[field]:
                    missing_fields.append(field)
            
            if missing_fields:
                self.logger.warning(f"Missing required authentication fields: {', '.join(missing_fields)}")
        
        return auth_config
    
    def is_auth_required(self, url: str) -> bool:
        """
        Check if a URL requires authentication.
        
        Args:
            url: URL to check
            
        Returns:
            True if the URL requires authentication
        """
        if not self.auth_config["enabled"]:
            return False
            
        # Check if URL is in restricted areas
        domain_slug = self.config_manager.domain_to_slug(self.domain) if self.domain else None
        
        if domain_slug and domain_slug in self.auth_config["domains"]:
            # Check restricted URLs for this domain
            restricted_urls = self.auth_config["domains"][domain_slug].get("restricted_urls", [])
            for restricted_url in restricted_urls:
                if url.startswith(restricted_url):
                    return True
        
        # Check URL against restricted patterns
        restricted_patterns = self.config_manager.get_list("RESTRICTED_AREA_PATTERNS", [])
        for pattern in restricted_patterns:
            if pattern in url:
                return True
                
        return False
    
    def initialize_driver(self, headless: bool = True) -> None:
        """
        Initialize Selenium webdriver for authentication.
        
        Args:
            headless: Whether to run the browser in headless mode
        """
        if self.driver is not None:
            return
            
        self.logger.info("Initializing authentication driver")
        
        try:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless")
                
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            
            self.logger.info("Authentication driver initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error initializing authentication driver: {e}")
            raise
    
    def perform_action(self, action: Dict[str, Any]) -> bool:
        """
        Perform a single action on the page during authentication.
        
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
            
            if action_type == "wait":
                seconds = action.get("seconds", 1)
                self.logger.debug(f"Waiting for {seconds} seconds")
                time.sleep(seconds)
                
            elif action_type == "click":
                selector = action.get("selector", "")
                self.logger.debug(f"Clicking on element: {selector}")
                element = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                element.click()
                
            elif action_type == "input":
                selector = action.get("selector", "")
                value = action.get("value", "")
                self.logger.debug(f"Entering text in element: {selector}")
                element = WebDriverWait(self.driver, 20).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
                element.clear()
                element.send_keys(value)
                
            elif action_type == "screenshot":
                if self.output_manager:
                    filename = action.get("filename", f"auth_{int(time.time())}.png")
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
                var cookieButtons = document.querySelectorAll('button[id*="cookie"], button[class*="cookie"], button[id*="consent"], button[class*="consent"], #onetrust-accept-btn-handler');
                for(var i=0; i<cookieButtons.length; i++) {
                    if(cookieButtons[i].offsetParent !== null) {
                        cookieButtons[i].click();
                        return true;
                    }
                }
                return false;
                """
                self.driver.execute_script(cookie_script)
                
            else:
                self.logger.warning(f"Unknown action type: {action_type}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error performing action: {e}")
            return False
    
    def login(self) -> bool:
        """
        Perform authentication to the website.
        
        Returns:
            True if authentication was successful
        """
        if not self.auth_config["enabled"]:
            self.logger.info("Authentication is disabled")
            return False
            
        if not self.auth_config["login_url"]:
            self.logger.error("Login URL not specified")
            return False
            
        if self.is_authenticated:
            self.logger.info("Already authenticated")
            return True
            
        self.logger.info(f"Performing authentication to {self.auth_config['login_url']}")
        
        try:
            # Initialize driver if not already
            self.initialize_driver(headless=self.config_manager.get_bool("AXE_HEADLESS", True))
            
            # Navigate to login page
            self.driver.get(self.auth_config["login_url"])
            
            # Take screenshot of login page
            if self.output_manager:
                screenshot_path = self.output_manager.get_path("screenshots", "auth_login_page.png")
                self.output_manager.ensure_path_exists("screenshots")
                self.driver.save_screenshot(str(screenshot_path))
            
            # Perform pre-login actions
            for action in self.auth_config["pre_login_actions"]:
                self.perform_action(action)
            
            # Fill username
            if self.auth_config["username_selector"]:
                username_field = WebDriverWait(self.driver, 20).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, self.auth_config["username_selector"]))
                )
                username_field.clear()
                username_field.send_keys(self.auth_config["username"])
            
            # Fill password
            if self.auth_config["password_selector"]:
                password_field = WebDriverWait(self.driver, 20).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, self.auth_config["password_selector"]))
                )
                password_field.clear()
                password_field.send_keys(self.auth_config["password"])
            
            # Submit form
            if self.auth_config["submit_selector"]:
                submit_button = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, self.auth_config["submit_selector"]))
                )
                submit_button.click()
            
            # Wait for login to complete
            time.sleep(5)
            
            # Perform post-login actions
            for action in self.auth_config["post_login_actions"]:
                self.perform_action(action)
            
            # Check for success indicator
            if self.auth_config["success_indicator"]:
                try:
                    WebDriverWait(self.driver, 20).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, self.auth_config["success_indicator"]))
                    )
                    self.logger.info("Authentication successful - success indicator found")
                    self.is_authenticated = True
                except TimeoutException:
                    self.logger.error("Authentication failed - success indicator not found")
                    return False
            
            # Check for error indicator
            if self.auth_config["error_indicator"]:
                try:
                    error_element = self.driver.find_element(By.CSS_SELECTOR, self.auth_config["error_indicator"])
                    if error_element.is_displayed():
                        self.logger.error(f"Authentication failed - error detected: {error_element.text}")
                        return False
                except:
                    # No error found, which is good
                    pass
            
            # If no explicit success/error indicators, assume success if neither is set
            if not self.auth_config["success_indicator"] and not self.auth_config["error_indicator"]:
                self.logger.info("Authentication assumed successful (no indicators set)")
                self.is_authenticated = True
            
            # Store cookies for later use
            self.cookies = self.driver.get_cookies()
            
            # Take a screenshot of successful login
            if self.output_manager:
                screenshot_path = self.output_manager.get_path("screenshots", "auth_success.png")
                self.output_manager.ensure_path_exists("screenshots")
                self.driver.save_screenshot(str(screenshot_path))
                self.logger.info(f"Authentication screenshot saved to {screenshot_path}")
            
            self.logger.info("Authentication completed successfully")
            return self.is_authenticated
            
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            
            # Take screenshot of error state
            if self.output_manager and self.driver:
                screenshot_path = self.output_manager.get_path("screenshots", "auth_error.png")
                self.output_manager.ensure_path_exists("screenshots")
                self.driver.save_screenshot(str(screenshot_path))
                self.logger.info(f"Authentication error screenshot saved to {screenshot_path}")
                
            return False
    
    def apply_auth_to_driver(self, driver: webdriver.Chrome) -> bool:
        """
        Apply authentication cookies to another Selenium driver.
        
        Args:
            driver: Selenium webdriver to apply authentication to
            
        Returns:
            True if authentication was applied successfully
        """
        if not self.is_authenticated or not self.cookies:
            self.logger.warning("Cannot apply authentication - not authenticated or no cookies")
            return False
            
        try:
            # Get current URL to return to it after setting cookies
            current_url = driver.current_url
            
            # Extract domain from login URL to set cookies
            main_domain = self.auth_config["login_url"].split("//")[1].split("/")[0]
            
            # Need to visit the domain before setting cookies
            driver.get(f"https://{main_domain}")
            
            # Add each cookie to the driver
            for cookie in self.cookies:
                try:
                    # Remove problematic cookie attributes that might cause issues
                    if 'expiry' in cookie:
                        # Convert to int as required by Selenium
                        cookie['expiry'] = int(cookie['expiry'])
                    
                    # Remove attributes not supported by Selenium
                    for attr in ['sameSite', 'priority', 'storeId', 'hostOnly']:
                        if attr in cookie:
                            del cookie[attr]
                    
                    driver.add_cookie(cookie)
                except Exception as e:
                    self.logger.warning(f"Error adding cookie: {e}")
            
            # Return to original URL
            driver.get(current_url)
            
            self.logger.info(f"Authentication cookies applied to driver")
            return True
            
        except Exception as e:
            self.logger.error(f"Error applying authentication to driver: {e}")
            return False
    
    def collect_authenticated_urls(self, require_auth=True) -> List[str]:
        """
        Collect URLs of authenticated sections for analysis.
        
        Args:
            require_auth: Whether authentication is required to collect URLs
            
        Returns:
            List of URLs in authenticated sections
        """
        if require_auth and not self.is_authenticated:
            self.logger.warning("Cannot collect authenticated URLs - not authenticated")
            return []
            
        try:
            self.authenticated_urls = []
            domain_slug = self.config_manager.domain_to_slug(self.domain) if self.domain else None
            self.logger.info(f"Collecting restricted URLs for domain slug: {domain_slug}")
            
            if domain_slug and domain_slug in self.auth_config["domains"]:
                # Get restricted URLs for this domain
                restricted_urls = self.auth_config["domains"][domain_slug].get("restricted_urls", [])
                explore_restricted = self.auth_config["domains"][domain_slug].get("explore_restricted_area", False)
                
                # If not authenticated or exploration disabled, just return the static list 
                if not self.is_authenticated or not explore_restricted:
                    self.authenticated_urls = restricted_urls.copy()
                    self.logger.info(f"Using {len(self.authenticated_urls)} specified restricted URLs for analysis")
                else:
                    # Visit each restricted URL and collect links within the same area
                    self.logger.info(f"Exploring restricted area to collect authenticated URLs")
                    for base_url in restricted_urls:
                        try:
                            self.driver.get(base_url)
                            time.sleep(3)  # Wait for page to load
                            
                            # Collect links on the page
                            links = self.driver.find_elements(By.TAG_NAME, "a")
                            for link in links:
                                try:
                                    href = link.get_attribute("href")
                                    if href and any(href.startswith(r) for r in restricted_urls):
                                        if href not in self.authenticated_urls:
                                            self.authenticated_urls.append(href)
                                except:
                                    pass
                        except Exception as e:
                            self.logger.warning(f"Error exploring {base_url}: {e}")
                    
                    self.logger.info(f"Collected {len(self.authenticated_urls)} authenticated URLs")
            else:
                self.logger.warning(f"Domain slug '{domain_slug}' not found in AUTH_DOMAINS")
                # Try alternative formats
                alt_slug = domain_slug.replace("_", "")
                if alt_slug in self.auth_config["domains"]:
                    restricted_urls = self.auth_config["domains"][alt_slug].get("restricted_urls", [])
                    self.authenticated_urls = restricted_urls.copy()
                    self.logger.info(f"Found {len(self.authenticated_urls)} restricted URLs with alternate slug format")
            
            return self.authenticated_urls
                
        except Exception as e:
            self.logger.error(f"Error collecting authenticated URLs: {e}")
            return []
    
    def close(self) -> None:
        """Close the authentication driver and clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("Authentication driver closed")
            except Exception as e:
                self.logger.error(f"Error closing authentication driver: {e}")
            finally:
                self.driver = None