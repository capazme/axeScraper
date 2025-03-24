# src/utils/auth_manager.py
import logging
import time
import json
from typing import Dict, Any, Optional, List, Union
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class AuthenticationStrategy:
    """Interface for authentication strategies."""
    
    def authenticate(self, driver: webdriver.Chrome) -> bool:
        """
        Authenticate using the provided Selenium driver.
        
        Args:
            driver: Selenium WebDriver instance
            
        Returns:
            True if authentication successful, False otherwise
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_auth_cookies(self) -> List[Dict[str, Any]]:
        """
        Get authentication cookies to be used by requests/Scrapy.
        
        Returns:
            List of cookie dictionaries
        """
        raise NotImplementedError("Subclasses must implement this method")

class FormAuthenticationStrategy(AuthenticationStrategy):
    """
    Authentication strategy for form-based login.
    """
    
    def __init__(
        self, 
        login_url: str,
        username: str, 
        password: str,
        username_selector: str, 
        password_selector: str,
        submit_selector: str,
        success_indicator: Optional[str] = None,
        error_indicator: Optional[str] = None,
        pre_login_actions: Optional[List[Dict[str, Any]]] = None,
        post_login_actions: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 30
    ):
        """
        Initialize form authentication strategy.
        
        Args:
            login_url: URL of the login page
            username: Username or email
            password: Password
            username_selector: CSS selector for username input
            password_selector: CSS selector for password input
            submit_selector: CSS selector for submit button
            success_indicator: CSS selector that indicates successful login
            error_indicator: CSS selector that indicates failed login
            pre_login_actions: List of actions to perform before login
            post_login_actions: List of actions to perform after login
            timeout: Timeout in seconds for WebDriverWait
        """
        self.login_url = login_url
        self.username = username
        self.password = password
        self.username_selector = username_selector
        self.password_selector = password_selector
        self.submit_selector = submit_selector
        self.success_indicator = success_indicator
        self.error_indicator = error_indicator
        self.pre_login_actions = pre_login_actions or []
        self.post_login_actions = post_login_actions or []
        self.timeout = timeout
        self.logger = logging.getLogger('auth_manager')
        self.cookies = []
        
    def authenticate(self, driver: webdriver.Chrome) -> bool:
        """
        Authenticate using form login.
        
        Args:
            driver: Selenium WebDriver instance
            
        Returns:
            True if authentication successful, False otherwise
        """
        try:
            # Navigate to login page
            self.logger.info(f"Navigating to login page: {self.login_url}")
            driver.get(self.login_url)
            
            # Wait for page to fully load
            time.sleep(3)
            
            # Handle cookie banner
            try:
                cookie_selectors = [
                    "#onetrust-accept-btn-handler",
                    ".ot-sdk-container button",
                    "button[aria-label='Accept cookies']",
                    "button.cookie-accept",
                    ".ot-bnr-footer button"
                ]
                
                for selector in cookie_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.is_displayed():
                                self.logger.info(f"Attempting to close cookie banner with {selector}")
                                driver.execute_script("arguments[0].click();", element)
                                time.sleep(1)
                                break
                    except Exception as cookie_e:
                        self.logger.debug(f"Cookie selector not found: {selector} - {cookie_e}")
                        continue
            except Exception as e:
                self.logger.warning(f"Error handling cookie banner: {e}")
            
            # Execute pre-login actions
            self._execute_actions(driver, self.pre_login_actions)
            
            # Handle login form
            try:
                username_field = WebDriverWait(driver, self.timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, self.username_selector))
                )
                
                username_field.clear()
                username_field.send_keys(self.username)
                
                password_field = driver.find_element(By.CSS_SELECTOR, self.password_selector)
                password_field.clear()
                password_field.send_keys(self.password)
                
                submit_button = driver.find_element(By.CSS_SELECTOR, self.submit_selector)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", submit_button)
                
                time.sleep(3)
            except Exception as e:
                self.logger.error(f"Error during login form interaction: {e}")
                return False

            # Check login success
            if self.success_indicator:
                try:
                    WebDriverWait(driver, self.timeout).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, self.success_indicator))
                    )
                    self.logger.info("Login successful")
                    self._execute_actions(driver, self.post_login_actions)
                    self.cookies = driver.get_cookies()
                    return True
                except TimeoutException:
                    return self._handle_login_uncertainty(driver)
            else:
                return self._handle_login_uncertainty(driver)
                
        except Exception as e:
            self.logger.exception(f"Authentication failed: {e}")
            return False
            
    def _handle_login_uncertainty(self, driver: webdriver.Chrome) -> bool:
        """Handle cases where login success/failure is uncertain"""
        if self.error_indicator:
            try:
                driver.find_element(By.CSS_SELECTOR, self.error_indicator)
                self.logger.error("Login failed - error indicator found")
                return False
            except NoSuchElementException:
                pass
            
        if driver.current_url != self.login_url:
            self.logger.info("Login likely successful (URL changed)")
            self.cookies = driver.get_cookies()
            return True
            
        self.logger.warning("Login status uncertain, assuming failed")
        return False
    
    def _execute_actions(self, driver: webdriver.Chrome, actions: List[Dict[str, Any]]) -> None:
        """
        Execute a list of actions on the driver.
        
        Args:
            driver: Selenium WebDriver instance
            actions: List of action dictionaries
        """
        for action in actions:
            try:
                action_type = action.get('type')
                
                if action_type == 'click':
                    selector = action.get('selector')
                    self.logger.debug(f"Clicking element: {selector}")
                    element = WebDriverWait(driver, self.timeout).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    driver.execute_script("arguments[0].click();", element)
                
                elif action_type == 'input':
                    selector = action.get('selector')
                    value = action.get('value', '')
                    self.logger.debug(f"Inputting text to {selector}: {value}")
                    element = WebDriverWait(driver, self.timeout).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    element.clear()
                    element.send_keys(value)
                
                elif action_type == 'wait':
                    seconds = action.get('seconds', 1)
                    self.logger.debug(f"Waiting for {seconds} seconds")
                    time.sleep(seconds)
                
                elif action_type == 'wait_for':
                    selector = action.get('selector')
                    self.logger.debug(f"Waiting for element: {selector}")
                    WebDriverWait(driver, self.timeout).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    
                elif action_type == 'script':
                    code = action.get('code', '')
                    self.logger.debug(f"Executing JavaScript: {code[:30]}...")
                    driver.execute_script(code)

            except Exception as e:
                self.logger.warning(f"Error executing action {action}: {e}")
    
    def get_auth_cookies(self) -> List[Dict[str, Any]]:
        """
        Get authentication cookies.
        
        Returns:
            List of cookie dictionaries
        """
        return self.cookies

class AuthManager:
    """
    Manager for authentication strategies.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize authentication manager.
        
        Args:
            config: Authentication configuration
        """
        self.config = config or {}
        self.strategies = {}
        self.logger = logging.getLogger('auth_manager')
    
    def add_strategy(self, domain: str, strategy: AuthenticationStrategy) -> None:
        """
        Add an authentication strategy for a domain.
        
        Args:
            domain: Domain for the strategy
            strategy: Authentication strategy
        """
        self.strategies[domain] = strategy
        self.logger.info(f"Added authentication strategy for {domain}")
    
    def authenticate(self, domain: str, driver: webdriver.Chrome) -> bool:
        """
        Authenticate using the strategy for the specified domain.
        
        Args:
            domain: Domain to authenticate
            driver: Selenium WebDriver instance
            
        Returns:
            True if authentication successful, False otherwise
        """
        if domain in self.strategies:
            self.logger.info(f"Authenticating for domain: {domain}")
            return self.strategies[domain].authenticate(driver)
        else:
            self.logger.warning(f"No authentication strategy for domain: {domain}")
            return False
    
    def get_auth_cookies(self, domain: str) -> List[Dict[str, Any]]:
        """
        Get authentication cookies for a domain.
        
        Args:
            domain: Domain to get cookies for
            
        Returns:
            List of cookie dictionaries or empty list if no strategy
        """
        if domain in self.strategies:
            return self.strategies[domain].get_auth_cookies()
        return []
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'AuthManager':
        """
        Create an AuthManager from configuration.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            AuthManager instance
        """
        manager = cls(config)
        
        # Process authentication configurations
        for domain, auth_config in config.get('auth', {}).items():
            strategy_type = auth_config.get('type', 'form')
            
            if strategy_type == 'form':
                strategy = FormAuthenticationStrategy(
                    login_url=auth_config.get('login_url', ''),
                    username=auth_config.get('username', ''),
                    password=auth_config.get('password', ''),
                    username_selector=auth_config.get('username_selector', ''),
                    password_selector=auth_config.get('password_selector', ''),
                    submit_selector=auth_config.get('submit_selector', ''),
                    success_indicator=auth_config.get('success_indicator'),
                    error_indicator=auth_config.get('error_indicator'),
                    pre_login_actions=auth_config.get('pre_login_actions', []),
                    post_login_actions=auth_config.get('post_login_actions', []),
                    timeout=auth_config.get('timeout', 30)
                )
                manager.add_strategy(domain, strategy)
            
        return manager