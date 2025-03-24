#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Enhanced multi-domain spider that fully utilizes the configuration system.
This spider integrates with config_manager.py and respects environment variables
set in the .env file or passed directly to the application.
"""

from collections import defaultdict
import re
import json
import logging
import difflib
import html
from datetime import datetime
from urllib.parse import urljoin, urldefrag, urlparse
import time
import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.utils.url import url_has_any_extension
from scrapy.http import Request
from scrapy.exceptions import CloseSpider

from ..items import PageItem, PageItemLoader
from ..utils.url_filters import URLFilters
from ..utils.link_extractor import AdvancedLinkExtractor
from scrapy_selenium import SeleniumRequest
from selenium import webdriver
# Import configuration system
import sys
import os
import importlib.util
try:
    # Try relative import from this package
    from ....utils.config_manager import ConfigurationManager
    from ....utils.auth_manager import AuthManager, FormAuthenticationStrategy
except ImportError:
    # If running standalone, try to find the module in the project
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    sys.path.insert(0, project_root)
    try:
        from src.utils.config_manager import ConfigurationManager
    except ImportError:
        # Fallback to basic configuration if config_manager can't be imported
        ConfigurationManager = None


class MultiDomainSpider(scrapy.Spider):
    """
    Enhanced spider for multi-domain crawling with improved configuration handling.
    
    This spider integrates with the axeScraper configuration system, respecting:
    - Environment variables from .env files
    - Command-line arguments
    - Default configuration values
    """
    
    name = 'multi_domain_spider'
    
    # These variables will be initialized dynamically
    allowed_domains = []
    start_urls = []
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the spider with domains and configurations from multiple sources.
        
        Respects configuration hierarchy:
        1. Command-line arguments (highest priority)
        2. Environment variables
        3. Configuration files (.env, etc.)
        4. Default values (lowest priority)
        """
        super(MultiDomainSpider, self).__init__(*args, **kwargs)
        
        """  # Initialize logger
            self.logger = logging.getLogger(f'{self.name}_logger')
            self.logger.setLevel(logging.INFO) """
        
        # Load the configuration system if available
        self.config_manager = self._initialize_config_manager(kwargs)
        
        # Configuration of domains - with multiple fallback options
        self.domains = self._extract_domains(kwargs)
        
        # Debug the parameters and domains
        self.logger.info(f"Initialized with {len(self.domains)} domains: {', '.join(self.domains)}")
            
        # Configure allowed_domains and start_urls
        self.allowed_domains = self.domains.copy()
        
        # Prepare initial URLs (both www and non-www versions)
        self.start_urls = []
        for domain in self.domains:
            self.start_urls.append(f"https://www.{domain}")
            self.start_urls.append(f"https://{domain}")
            
        # Make initial URLs unique
        self.start_urls = list(set(self.start_urls))
        self.logger.info(f"Starting URLs: {', '.join(self.start_urls)}")

        # Configuration limits - read from config with fallback to kwargs with defaults
        self.max_urls_per_domain = self._get_config('max_urls_per_domain', 'CRAWLER_MAX_URLS', 
                                                 kwargs, default=1000)
        self.max_total_urls = self._get_config('max_total_urls', 'CRAWLER_MAX_TOTAL_URLS', 
                                            kwargs, default=None)
        self.depth_limit = self._get_config('depth_limit', 'CRAWLER_DEPTH_LIMIT', 
                                         kwargs, default=10)
        
        # Hybrid mode configuration
        self.hybrid_mode = self._get_config_bool('hybrid_mode', 'CRAWLER_HYBRID_MODE', 
                                             kwargs, default=True)
        self.request_delay = self._get_config_float('request_delay', 'CRAWLER_REQUEST_DELAY', 
                                                kwargs, default=0.25)
        self.selenium_threshold = self._get_config('selenium_threshold', 'CRAWLER_PENDING_THRESHOLD', 
                                               kwargs, default=30)
        
        # Respect robots.txt
        self.respect_robots = self._get_config_bool('respect_robots', 'CRAWLER_RESPECT_ROBOTS', 
                                                kwargs, default=False)
        
        # Statistics and counters by domain
        self.processed_count = 0
        self.domain_counts = {domain: 0 for domain in self.domains}
        self.url_tree = {}
        self.structures = {}
        self.template_cache = {}
        
        # Navigation mode flags
        self.using_selenium = self.hybrid_mode
        self.switch_occurred = False
        
        # Advanced link extractor
        self.link_extractor = AdvancedLinkExtractor(allowed_domains=self.domains)
        
        # Settings for robots.txt
        if self.respect_robots:
            from scrapy.robotstxt import RobotFileParser
            self.robots_parsers = {}
        self.auth_enabled = self._get_config_bool('auth_enabled', 'AUTH_ENABLED', kwargs, False)
        self.auth_domains = set(self._get_config('auth_domains', 'AUTH_DOMAINS', kwargs, []))
        self.authenticated_domains = set()
        self.auth_cookies = {}
        self.auth_driver = None

        # Log the configuration settings
        self._log_configuration()
    
    def _initialize_config_manager(self, kwargs):
        """Initialize the configuration manager using only configuration file and CLI arguments."""
        if ConfigurationManager is None:
            return None
        # Non si cerca più il file .env; si passa solo il config_file (se specificato) e i CLI args.
        return ConfigurationManager(
            project_name="axeScraper",
            config_file=kwargs.get('config_file'),  # Puoi passare il percorso al file di configurazione
            cli_args=kwargs
        )

    def _extract_domains(self, kwargs):
        domains = []
        
        domains_input = kwargs.get('domains', '')
        domains_file = kwargs.get('domains_file', '')
        single_domain = kwargs.get('domain', '')
        
        # 1. List from CLI parameter
        if domains_input:
            self.logger.info(f"Using domains from CLI parameter: '{domains_input}'")
            raw_domains = [d.strip() for d in domains_input.split(',') if d.strip()]
            
            # Improved domain extraction
            for raw_domain in raw_domains:
                # Extract just the domain from URLs
                if '://' in raw_domain or raw_domain.startswith('www.'):
                    parsed = urlparse(raw_domain if '://' in raw_domain else f"https://{raw_domain}")
                    clean_domain = parsed.netloc
                    # Remove www. prefix if present
                    if clean_domain.startswith('www.'):
                        clean_domain = clean_domain[4:]
                    domains.append(clean_domain)
                else:
                    # Check if it contains path elements and strip them
                    if '/' in raw_domain:
                        clean_domain = raw_domain.split('/', 1)[0]
                    else:
                        clean_domain = raw_domain
                    domains.append(clean_domain)
                    
        # Rest of the method remains the same...
        
        # Ensure we have valid domains
        domains = [d for d in domains if d and '.' in d]
        
        return domains
    
    def _get_config(self, kwarg_name, config_key, kwargs, default=None):
        """
        Get configuration value with proper fallback priority.
        
        Ordine di priorità:
        1. Argomenti da linea di comando (CLI args)
        2. File di configurazione (attraverso il ConfigurationManager)
        3. Valore predefinito
        
        Args:
            kwarg_name: Nome del parametro nei kwargs (CLI)
            config_key: Chiave del file di configurazione
            kwargs: Dizionario dei parametri passati
            default: Valore predefinito se non trovato
            
        Returns:
            Valore di configurazione
        """
        # 1. Check CLI arguments
        if kwarg_name in kwargs:
            try:
                return int(kwargs[kwarg_name])
            except (ValueError, TypeError):
                return kwargs[kwarg_name]
        
        # 2. Check configuration manager (file di configurazione)
        if self.config_manager is not None:
            value = self.config_manager.get(config_key)
            if value is not None:
                return value
        
        # 3. Default value
        return default

    def _get_config_bool(self, kwarg_name, env_name, kwargs, default=False):
        """Get boolean configuration with proper type conversion."""
        value = self._get_config(kwarg_name, env_name, kwargs, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 'yes', 'y', 'on')
        return bool(value)
    
    def _get_config_float(self, kwarg_name, env_name, kwargs, default=0.0):
        """Get float configuration with proper type conversion."""
        value = self._get_config(kwarg_name, env_name, kwargs, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _log_configuration(self):
        """Log the active configuration settings for debugging."""
        self.logger.info(f"Configuration: max_urls_per_domain={self.max_urls_per_domain}, "
                         f"max_total_urls={self.max_total_urls}, "
                         f"hybrid_mode={self.hybrid_mode}, "
                         f"depth_limit={self.depth_limit}, "
                         f"request_delay={self.request_delay}, "
                         f"selenium_threshold={self.selenium_threshold}")
    
    def _authenticate(self, domain: str):
        """
        Autentica il crawler per un dominio specifico.
        
        Args:
            domain: Dominio da autenticare
        
        Returns:
            True se l'autenticazione ha successo, False altrimenti
        """
        # Skip se l'autenticazione non è abilitata
        if not self.auth_enabled:
            self.logger.debug(f"Autenticazione non abilitata per {domain}")
            return False
        
        # Skip se il dominio non è nella lista dei domini con autenticazione
        if self.auth_domains and domain not in self.auth_domains:
            self.logger.debug(f"Autenticazione non configurata per {domain}")
            return False
        
        # Ottieni configurazione di autenticazione per il dominio
        auth_config = self.config_manager.get_auth_config(domain)
        
        # Skip se la configurazione non è valida
        if not auth_config.get("enabled", False):
            self.logger.debug(f"Autenticazione non abilitata per {domain}")
            return False
        
        # Crea la strategia di autenticazione
        strategy_type = auth_config.get("type", "form")
        
        if strategy_type == "form":
            strategy = FormAuthenticationStrategy(
                login_url=auth_config.get("login_url", ""),
                username=auth_config.get("username", ""),
                password=auth_config.get("password", ""),
                username_selector=auth_config.get("username_selector", ""),
                password_selector=auth_config.get("password_selector", ""),
                submit_selector=auth_config.get("submit_selector", ""),
                success_indicator=auth_config.get("success_indicator", ""),
                error_indicator=auth_config.get("error_indicator", ""),
                pre_login_actions=auth_config.get("pre_login_actions", []),
                post_login_actions=auth_config.get("post_login_actions", []),
                timeout=auth_config.get("timeout", 30)
            )
            
            # Autentica con Selenium se la modalità ibrida è abilitata
            if self.hybrid_mode and self.using_selenium and not self.switch_occurred:
                # Crea un nuovo driver Selenium se necessario
                if not hasattr(self, "auth_driver") or self.auth_driver is None:
                    options = webdriver.ChromeOptions()
                    options.add_argument("--headless")
                    options.add_argument("--no-sandbox")
                    options.add_argument("--disable-dev-shm-usage")
                    
                    self.auth_driver = webdriver.Chrome(options=options)
                
                # Esegui l'autenticazione
                success = strategy.authenticate(self.auth_driver)
                
                if success:
                    # Salva i cookies per Scrapy
                    self.logger.info(f"Autenticazione riuscita per {domain}")
                    
                    # Aggiorna lo stato di autenticazione
                    self.authenticated_domains.add(domain)
                    
                    # Ottieni i cookies
                    cookies = strategy.get_auth_cookies()
                    
                    # Memorizza i cookies per essere usati nelle richieste HTTP
                    self.auth_cookies[domain] = cookies
                    
                    return True
                else:
                    self.logger.error(f"Autenticazione fallita per {domain}")
                    return False
        
        return False
    
    def start_requests(self):
        """
        Generate initial requests based on the configured parameters.
        Includes authentication if enabled.
        
        Yields:
            Request: Requests for each starting URL
        """
        self.logger.info(f"Starting crawl for {len(self.domains)} domains: {', '.join(self.domains)}")
        
        # Reset counters
        self.processed_count = 0
        self.domain_counts = {domain: 0 for domain in self.domains}
        
        # Authenticate for each domain if enabled
        if self.auth_enabled:
            for domain in self.domains:
                self._authenticate(domain)
        
        # Verify starting URLs
        if not self.start_urls:
            self.logger.error("No starting URLs defined!")
            self.start_urls = [f"https://www.{domain}" for domain in self.domains]
            
        # Process each starting URL
        for url in self.start_urls:
            self.logger.info(f"Requesting initial URL: {url}")
            
            # Get domain for this URL
            domain = URLFilters.get_domain(url)
            
            # Use Selenium or HTTP based on configuration
            if self.hybrid_mode and self.using_selenium:
                yield self.make_selenium_request(url, self.parse)
            else:
                # Add auth cookies if authenticated for this domain
                cookies = self.auth_cookies.get(domain, [])
                
                yield Request(
                    url=url, 
                    callback=self.parse,
                    cookies={c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c},
                    meta={
                        'dont_redirect': False, 
                        'handle_httpstatus_list': [301, 302],
                        'depth': 0  # Initial depth
                    },
                    errback=self.errback_httpbin
                )
                
    def is_public_page(self, url):
        """
        Determine if a URL represents a public page that should be crawled.
        
        Args:
            url: URL to evaluate
            
        Returns:
            bool: True if the URL should be crawled
        """
        url_lower = url.lower()
        
        # Check against disallowed patterns for non-public content
        disallowed_patterns = [
            '/_layouts/', '/admin/', '/wp-admin/', '/cgi-bin/',
            '/wp-json/', '/wp-content/uploads/', '/xmlrpc.php',
            '/login', '/logout', '/cart', '/checkout'
        ]
        
        for pattern in disallowed_patterns:
            if pattern.lower() in url_lower:
                return False
                
        # Skip static resources
        extensions_to_skip = ['.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.xml', 
                            '.pdf', '.zip', '.rar', '.exe', '.svg', '.ico']
        
        for ext in extensions_to_skip:
            if url_lower.endswith(ext):
                return False
        
        # By default, consider it public
        return True
    
    def is_user_visible(self, response):
        """
        Detect if a page contains user-visible content.
        
        Args:
            response: Scrapy Response object
            
        Returns:
            bool: True if the page appears to be user-facing content
        """
        # Look for common page structure elements
        has_header = bool(response.css('header, .header, #header, [role="banner"], .navbar, .nav-bar, .top-bar'))
        has_nav = bool(response.css('nav, .nav, #nav, .menu, #menu, [role="navigation"], ul.menu, .navigation'))
        has_main = bool(response.css('main, .main, #main, [role="main"], article, .content, #content, .page-content'))
        has_footer = bool(response.css('footer, .footer, #footer, [role="contentinfo"], .site-footer'))
        
        # Check for basic content indicators
        has_content = bool(response.css('p, h1, h2, h3, div.content, .container, .wrapper'))
        
        # Only need some indication of being a user page
        return has_content and (has_header or has_nav or has_main or has_footer)

    def has_meaningful_content(self, response):
        """
        Determine if a page has meaningful content worth analyzing.
        
        Args:
            response: Scrapy Response object
            
        Returns:
            bool: True if the page has substantive content
        """
        # Extract visible text
        texts = response.xpath('//body//text()').getall()
        
        # Clean and join text
        text_content = ' '.join([t.strip() for t in texts if t.strip()])
        
        # Check for reasonable text length
        if len(text_content) > 200:
            return True
            
        # Also check for important page elements
        if response.css('h1, h2, h3, nav, article, section'):
            return True
            
        return False

    def _extract_js_links(self, response):
        """
        Extract links from JavaScript content.
        
        Args:
            response: Scrapy Response object
            
        Returns:
            set: Set of URLs found in JavaScript
        """
        js_links = set()
        
        # Extract URLs from script tags
        scripts = response.xpath('//script/text()').getall()
        for script in scripts:
            # Find absolute URLs
            url_matches = re.findall(r'["\']https?://[^"\']+["\']', script)
            for match in url_matches:
                clean_url = match.strip('\'"')
                if URLFilters.get_domain(clean_url) in self.allowed_domains:
                    js_links.add(clean_url)
                    
            # Find relative URLs
            rel_matches = re.findall(r'["\'][/][^"\']+["\']', script)
            for match in rel_matches:
                clean_url = match.strip('\'"')
                if clean_url.startswith('/'):
                    full_url = urljoin(response.url, clean_url)
                    js_links.add(full_url)
                    
        return js_links

    def parse(self, response):
        """
        Main parsing method for web pages.
        
        Args:
            response: Scrapy Response object
            
        Yields:
            Item or Request: Scraped items or new requests
        """
        current_url = response.url
        current_domain = URLFilters.get_domain(current_url)
        
        self.logger.info(f"Parsing page: {current_url} ({current_domain})")
        
        # Check if domain is allowed
        if current_domain not in self.allowed_domains:
            self.logger.warning(f"Domain not allowed: {current_domain}, URL: {current_url}")
            return
            
        # Check depth limit
        depth = response.meta.get('depth', 0)
        if self.depth_limit and depth >= self.depth_limit:
            self.logger.debug(f"Depth limit reached ({depth}/{self.depth_limit}) for: {current_url}")
            return
            
        # Update counters
        self.processed_count += 1
        self.domain_counts[current_domain] = self.domain_counts.get(current_domain, 0) + 1
        
        # Check domain URL limit
        if self.max_urls_per_domain and self.domain_counts[current_domain] >= self.max_urls_per_domain:
            self.logger.debug(f"URL limit reached for domain {current_domain}")
            return
            
        # Check total URL limit
        if self.max_total_urls and self.processed_count >= self.max_total_urls:
            self.logger.info(f"Reached total URL limit: {self.max_total_urls}")
            raise CloseSpider(f"Reached maximum total of {self.max_total_urls} URLs")
            
        # Update URL structure
        self._update_url_structure(response)
        
        # Extract page item
        item = self._extract_page_item(response)
        if item:
            yield item
        
        # Extract links
        links = self.link_extractor.extract_links(response, current_domain)
        
        # Add JavaScript links
        js_links = self._extract_js_links(response)
        links.update(js_links)
        
        # Filter links
        filtered_links = {
            link for link in links 
            if URLFilters.is_valid_url(link) and URLFilters.get_domain(link) == current_domain and self.is_public_page(link)
        }
        
        # Check if we should switch from Selenium to HTTP in hybrid mode
        if self.hybrid_mode and not self.switch_occurred:
            pending_requests = len(self.crawler.engine.slot.scheduler)
            if pending_requests >= self.selenium_threshold:
                self.logger.info(f"Switching from Selenium to HTTP (pending: {pending_requests})")
                self.using_selenium = False
                self.switch_occurred = True
                
                # Update statistics
                self.crawler.stats.set_value('hybrid_mode/switch_time', datetime.now().isoformat())
                self.crawler.stats.set_value('hybrid_mode/switch_url', current_url)
        
        # Log progress
        self.logger.info(f"Progress: {self.processed_count} total, {current_domain}: {self.domain_counts[current_domain]}")
        
        # Generate requests for found URLs
        requests_generated = 0
        for link in filtered_links:
            # Skip if we've reached limits
            link_domain = URLFilters.get_domain(link)
            if self.max_urls_per_domain and self.domain_counts.get(link_domain, 0) >= self.max_urls_per_domain:
                continue
                
            if self.max_total_urls and self.processed_count >= self.max_total_urls:
                break
            
            # Check robots.txt if required
            if self.respect_robots and not self._can_fetch(link):
                self.logger.debug(f"URL blocked by robots.txt: {link}")
                continue
                
            # Generate appropriate request
            try:
                # Increment depth
                new_depth = depth + 1
                
                # Skip if exceeding depth limit
                if self.depth_limit and new_depth > self.depth_limit:
                    continue
                
                if self.hybrid_mode and self.using_selenium:
                    req = self.make_selenium_request(
                        link, 
                        self.parse, 
                        referer=current_url,
                        depth=new_depth
                    )
                    if req:
                        requests_generated += 1
                        yield req
                else:
                    requests_generated += 1
                    yield Request(
                        url=link, 
                        callback=self.parse,
                        meta={
                            'referer': current_url,
                            'dont_redirect': False,
                            'handle_httpstatus_list': [301, 302],
                            'depth': new_depth
                        },
                        errback=self.errback_httpbin
                    )
            except Exception as e:
                self.logger.error(f"Error generating request for {link}: {e}")
                
        self.logger.info(f"Generated {requests_generated} new requests from {current_url}")
    
    def errback_httpbin(self, failure):
        """
        Handle request errors with fallback to Selenium if appropriate.
        
        Args:
            failure: Twisted Failure object
            
        Yields:
            Request: Potential fallback request
        """
        request = failure.request
        url = request.url
        domain = URLFilters.get_domain(url)
        
        self.logger.error(f"Error processing: {url}")
        self.logger.error(f"Error type: {failure.type}")
        self.logger.error(f"Error value: {failure.value}")
        
        # Update statistics
        if domain in self.domains:
            self.crawler.stats.inc_value(f'domain/{domain}/errors')
        
        # Try Selenium fallback in hybrid mode
        if self.hybrid_mode and not request.meta.get('selenium'):
            self.logger.info(f"Attempting Selenium fallback for: {url}")
            yield self.make_selenium_request(
                url, 
                self.parse,
                depth=request.meta.get('depth', 0)
            )
    
    def make_selenium_request(self, url, callback, referer=None, depth=0):
        """
        Create a Selenium request with appropriate parameters.
        
        Args:
            url: Target URL
            callback: Callback function
            referer: Referrer URL
            depth: Crawl depth
            
        Returns:
            SeleniumRequest or None
        """
        # Verify URL validity
        if not URLFilters.is_valid_url(url):
            self.logger.warning(f"Invalid URL skipped: {url}")
            return None
            
        try:            
            # Normalize URL
            url = URLFilters.normalize_url(url)
            if not url:
                return None
            
            # Get domain for authentication cookies
            domain = URLFilters.get_domain(url)
            
            # Prepare meta data
            meta = {
                'selenium': True,
                'referer': referer,
                'depth': depth
            }
            
            # Add authenticated flag if domain is authenticated
            if domain in self.authenticated_domains:
                meta['authenticated'] = True
            
            # JavaScript to execute
            js_script = """
                // Handle popups and common interface elements
                try {
                    // Click cookie accept buttons
                    var acceptBtns = document.querySelectorAll(
                        "button:contains('Accept'), button:contains('Accetta'), " +
                        "button:contains('I agree'), button:contains('Accetto'), " +
                        "[id*='cookie'] button, [class*='cookie'] button, " +
                        "[id*='consent'] button, [class*='consent'] button"
                    );
                    for (var i = 0; i < acceptBtns.length; i++) {
                        if (acceptBtns[i].offsetParent !== null) {
                            acceptBtns[i].click();
                            console.log('Clicked cookie consent button');
                            break;
                        }
                    }
                    
                    // Click "load more" buttons
                    // Click "load more" buttons
                    var loadMoreBtns = document.querySelectorAll(
                        "button:contains('Load more'), button:contains('Show more'), " +
                        "button:contains('Mostra altro'), button:contains('Carica di più'), " +
                        "[class*='load-more'], [class*='show-more']"
                    );
                    for (var i = 0; i < loadMoreBtns.length; i++) {
                        if (loadMoreBtns[i].offsetParent !== null) {
                            loadMoreBtns[i].click();
                            console.log('Clicked load more button');
                            break;
                        }
                    }
                    
                    // Scroll page to help load lazy content
                    window.scrollTo(0, document.body.scrollHeight / 2);
                    setTimeout(function() {
                        window.scrollTo(0, document.body.scrollHeight);
                    }, 1000);
                } catch(e) {
                    console.error('Error in Selenium script:', e);
                }
            """
            
            # Add auth cookie preparation script if domain is authenticated
            if domain in self.authenticated_domains and domain in self.auth_cookies:
                cookies_js = """
                // Add auth cookies
                try {
                    const cookies = %s;
                    for (const cookie of cookies) {
                        document.cookie = `${cookie.name}=${cookie.value}; path=${cookie.path || '/'}`;
                        console.log(`Added cookie: ${cookie.name}`);
                    }
                } catch(e) {
                    console.error('Error adding cookies:', e);
                }
                """ % json.dumps(self.auth_cookies[domain])
                
                js_script = cookies_js + js_script
            
            return SeleniumRequest(
                url=url,
                callback=callback,
                wait_time=3,  # Wait for JS rendering
                meta=meta,
                script=js_script,
                dont_filter=False,
                errback=self.errback_httpbin
            )
        except Exception as e:
            self.logger.error(f"Error creating Selenium request for {url}: {e}")
            return None
                
    def _extract_page_item(self, response):
        """
        Extract page data into a structured item.
        
        Args:
            response: Scrapy Response object
            
        Returns:
            Item or None: Extracted data
        """
        try:
            # Create item loader
            loader = PageItemLoader(item=PageItem(), selector=response)
            
            # Basic information
            url = response.url
            domain = URLFilters.get_domain(url)
            referer = response.meta.get('referer')
            
            # Check domain validity
            if domain not in self.domains:
                return None
                
            # URL and metadata
            loader.add_value('url', url)
            loader.add_value('domain', domain)
            loader.add_value('referer', referer)
            loader.add_value('status', response.status)
            loader.add_value('depth', response.meta.get('depth', 0))
            loader.add_value('timestamp', datetime.now().isoformat())
            loader.add_value('crawl_time', time.time())
            
            # URL template
            template = URLFilters.get_url_template(url)
            loader.add_value('template', template)
            
            # Page content
            loader.add_css('title', 'title::text')
            loader.add_css('meta_description', 'meta[name="description"]::attr(content)')
            loader.add_css('meta_keywords', 'meta[name="keywords"]::attr(content)')
            loader.add_css('h1', 'h1::text')
            
            # Links
            links = self.link_extractor.extract_links(response)
            loader.add_value('links', list(links))
            
            # Save HTML content if configured
            if self.settings.getbool('PIPELINE_KEEP_HTML', False):
                loader.add_value('content', response.text)
            
            # Update statistics
            self.crawler.stats.inc_value(f'domain/{domain}/items')
            
            return loader.load_item()
        except Exception as e:
            self.logger.error(f"Error extracting item from {response.url}: {e}")
            return None
        
    def _update_url_structure(self, response):
        """
        Update URL structure and template data.
        
        Args:
            response: Scrapy Response object
        """
        url = response.url
        domain = URLFilters.get_domain(url)
        
        # Generate template
        template = URLFilters.get_url_template(url)
        
        # Store structure with domain prefix
        domain_template = f"{domain}:{template}"
        
        # Look for similar templates
        similar = self._find_similar_template(domain_template)
        if similar:
            # Increment counter for existing template
            if similar in self.structures:
                self.structures[similar]['count'] += 1
            else:
                self.structures[similar] = {
                    'template': similar,
                    'url': url,
                    'domain': domain,
                    'count': 1
                }
        else:
            # Create new template entry
            self.structures[domain_template] = {
                'template': domain_template,
                'url': url,
                'domain': domain,
                'count': 1
            }
    
    def _find_similar_template(self, template, threshold=0.90):
        """
        Find similar templates to avoid duplication.
        
        Args:
            template: Template string to compare
            threshold: Similarity threshold (0.0-1.0)
            
        Returns:
            str or None: Similar template if found
        """
        for existing in self.structures.keys():
            # Only compare templates from the same domain
            if template.split(':', 1)[0] == existing.split(':', 1)[0]:
                ratio = difflib.SequenceMatcher(None, existing, template).ratio()
                if ratio >= threshold:
                    return existing
        return None
    
    def _can_fetch(self, url):
        """
        Check if a URL can be fetched according to robots.txt.
        
        Args:
            url: URL to check
            
        Returns:
            bool: True if the URL can be fetched
        """
        if not self.respect_robots:
            return True
            
        try:
            from scrapy.robotstxt import RobotFileParser
            
            domain = URLFilters.get_domain(url)
            
            # Create parser for this domain if it doesn't exist
            if domain not in self.robots_parsers:
                self.robots_parsers[domain] = RobotFileParser()
                robots_url = f"https://{domain}/robots.txt"
                
                # Try to download robots.txt
                try:
                    request = Request(robots_url)
                    response = self.crawler.engine.download(request)
                    if response.status == 200:
                        self.robots_parsers[domain].parse(response.body.splitlines())
                    else:
                        # If not available, allow all
                        return True
                except Exception:
                    # In case of error, allow all
                    return True
            
            # Check if the URL is allowed
            return self.robots_parsers[domain].can_fetch("*", url)
        except Exception as e:
            self.logger.error(f"Error checking robots.txt for {url}: {e}")
            return True  # Allow in case of error
    
    def closed(self, reason):
        """
        Execute cleanup actions when the spider is closed.
        
        Args:
            reason: Reason for closing
        """
        self.logger.info(f"Spider closed: {reason}")
        self.logger.info(f"Total URLs processed: {self.processed_count}")
        
        # Domain statistics
        for domain, count in sorted(self.domain_counts.items(), key=lambda x: x[1], reverse=True):
            self.logger.info(f"Domain {domain}: {count} URLs processed")
        
        # Clean up the link extractor
        if hasattr(self, 'link_extractor'):
            self.link_extractor.close()
            
        # Log top templates by domain
        domain_templates = defaultdict(list)
        for template, data in self.structures.items():
            domain = data.get('domain', '')
            domain_templates[domain].append((template, data))
        
        for domain, templates in domain_templates.items():
            sorted_templates = sorted(templates, key=lambda x: x[1]['count'], reverse=True)
            
            self.logger.info(f"Top templates for {domain}:")
            for i, (template, data) in enumerate(sorted_templates[:5], 1):
                self.logger.info(f"  {i}. {template} - {data['count']} pages")