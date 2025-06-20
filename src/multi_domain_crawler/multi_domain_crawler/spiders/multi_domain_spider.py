#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Enhanced multi-domain spider with fixed Selenium integration and error handling.
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
from scrapy.http import Request, HtmlResponse, TextResponse
from scrapy.exceptions import CloseSpider
import hashlib

from ..items import PageItem, PageItemLoader
from ..utils.url_filters import URLFilters
from ..utils.link_extractor import AdvancedLinkExtractor
from scrapy_selenium import SeleniumRequest
from ..utils.browser_headers import get_realistic_headers

# Import configuration system
import sys
import os
import importlib.util
try:
    from ....utils.config_manager import ConfigurationManager
except ImportError:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    sys.path.insert(0, project_root)
    try:
        from src.utils.config_manager import ConfigurationManager
    except ImportError:
        ConfigurationManager = None


class MultiDomainSpider(scrapy.Spider):
    """
    Enhanced spider for multi-domain crawling with improved Selenium handling.
    """
    
    name = 'multi_domain_spider'
    allowed_domains = []
    start_urls = []
    
    def __init__(self, *args, **kwargs):
        """Initialize the spider with domains and configurations."""
        super().__init__(*args, **kwargs)
        
        # Initialize configuration manager
        self.config_manager = None
        if ConfigurationManager:
            try:
                self.config_manager = ConfigurationManager()
                self.logger.info("Configuration manager initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize configuration manager: {e}")
        
        # Initialize output manager for centralized path management
        self.output_manager = None
        try:
            from src.utils.output_manager import OutputManager
            from src.utils.config import OUTPUT_ROOT
            temp_domains = self._get_domains(kwargs)
            if temp_domains:
                self.output_manager = OutputManager(base_dir=OUTPUT_ROOT, domain=temp_domains[0], create_dirs=True)
                self.logger.info("Output manager initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize output manager: {e}")
            self.output_manager = None
        
        # Spider configuration with defaults
        self.domains = self._get_domains(kwargs)
        self.allowed_domains = self.domains
        self.start_urls = [f"https://{domain}" for domain in self.domains]
        
        # Crawling limits
        self.max_urls_per_domain = int(kwargs.get('max_urls_per_domain', 
            self.config_manager.get('CRAWLER_MAX_URLS', 100) if self.config_manager else 100))
        self.max_total_urls = int(kwargs.get('max_total_urls', 
            self.config_manager.get('CRAWLER_MAX_TOTAL_URLS', 1000) if self.config_manager else 1000))
        self.depth_limit = int(kwargs.get('depth_limit', 
            self.config_manager.get('CRAWLER_DEPTH_LIMIT', 5) if self.config_manager else 5))
        
        # Mode configuration
        self.hybrid_mode = kwargs.get('hybrid_mode', 
            str(self.config_manager.get('CRAWLER_HYBRID_MODE', 'true') if self.config_manager else 'true')).lower() == 'true'
        self.selenium_threshold = int(kwargs.get('selenium_threshold', 
            self.config_manager.get('CRAWLER_PENDING_THRESHOLD', 30) if self.config_manager else 30))
        self.request_delay = float(kwargs.get('request_delay', 
            self.config_manager.get('CRAWLER_REQUEST_DELAY', 0.5) if self.config_manager else 0.5))
        
        # Tracking
        self.processed_count = 0
        self.domain_counts = defaultdict(int)
        self.using_selenium = True  # Start with Selenium in hybrid mode
        self.selenium_error_count = 0
        self.selenium_max_errors = 10
        
        # Template detection
        self.templates = defaultdict(lambda: defaultdict(list))
        self.template_structures = defaultdict(lambda: defaultdict(dict))
        self.structure_threshold = 0.85
        
        self.domain_limit_reached = set()
        
        self.crawling_finished = False  # Flag per bloccare crawling
        
        self.logger.info(f"Spider initialized with {len(self.domains)} domains")
        self.logger.info(f"Hybrid mode: {self.hybrid_mode}, Selenium threshold: {self.selenium_threshold}")

    def _get_domains(self, kwargs):
        """Extract domains from arguments or configuration."""
        domains = []
        
        # Try domains_file first
        domains_file = kwargs.get('domains_file')
        if domains_file and os.path.exists(domains_file):
            with open(domains_file, 'r') as f:
                domains = [line.strip() for line in f if line.strip()]
        
        # Fallback to domains argument
        if not domains:
            domains_str = kwargs.get('domains', '')
            if domains_str:
                domains = [d.strip() for d in domains_str.split(',') if d.strip()]
        
        # Fallback to configuration
        if not domains and self.config_manager:
            domains_str = self.config_manager.get('DOMAINS', '')
            if domains_str:
                domains = [d.strip() for d in domains_str.split(',') if d.strip()]
        
        # Normalize domains
        normalized_domains = []
        for domain in domains:
            domain = domain.lower().strip()
            domain = re.sub(r'^https?://', '', domain)
            domain = domain.rstrip('/')
            if domain and '.' in domain:
                normalized_domains.append(domain)
        
        if not normalized_domains:
            raise ValueError("No valid domains provided")
        
        return normalized_domains

    def normalize_url(self, url):
        """Normalize URL for consistency."""
        if not url:
            return None
        
        # Ensure URL has a scheme
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Remove fragment
        url, _ = urldefrag(url)
        
        # Remove trailing slash
        url = url.rstrip('/')
        
        return url

    def start_requests(self):
        """Generate initial requests for each domain."""
        if self.crawling_finished:
            self.logger.warning("Crawling già terminato: nessuna richiesta iniziale generata.")
            return
        self.logger.info(f"Starting crawl for {len(self.domains)} domains")
        
        self.processed_count = 0
        self.domain_counts = {domain: 0 for domain in self.domains}
        
        if not self.start_urls:
            self.start_urls = [f"https://{domain}" for domain in self.domains]
        
        # Prepare auth headers if configured
        import base64
        username = self.config_manager.get("AUTH_BASIC_USERNAME", "") if self.config_manager else ""
        password = self.config_manager.get("AUTH_BASIC_PASSWORD", "") if self.config_manager else ""
        auth_headers = {}
        if username and password:
            credentials = f"{username}:{password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            auth_headers["Authorization"] = f"Basic {encoded_credentials}"
            self.logger.info("HTTP Basic authentication configured")
        
        # Process each starting URL
        for i, url in enumerate(self.start_urls):
            if self.crawling_finished:
                self.logger.warning("Crawling terminato: blocco generazione richieste in start_requests.")
                break
            url = self.normalize_url(url)
            headers = get_realistic_headers()
            headers.update(auth_headers)
            
            if i == 0 and self.hybrid_mode:
                self.logger.info(f"First request with Selenium: {url}")
                yield self.make_selenium_request(url, self.parse, depth=0)
            else:
                self.logger.info(f"Requesting: {url}")
                yield Request(
                    url=url,
                    headers=headers,
                    callback=self.parse,
                    meta={
                        'dont_redirect': False,
                        'handle_httpstatus_list': [301, 302, 403, 429],
                        'depth': 0
                    },
                    errback=self.errback_httpbin
                )

    def make_selenium_request(self, url, callback, referer=None, depth=0):
        """Create a properly configured Selenium request."""
        if self.crawling_finished:
            self.logger.warning(f"Crawling terminato: blocco SeleniumRequest per {url}")
            return None
        if not URLFilters.is_valid_url(url):
            self.logger.warning(f"Invalid URL skipped: {url}")
            return None
        
        try:
            url = URLFilters.normalize_url(url)
            if not url:
                return None
            
            # Prepare meta data
            meta = {
                'selenium': True,
                'referer': referer,
                'depth': depth
            }
            
            # Prepare headers
            headers = get_realistic_headers(referer=referer)
            
            # Fixed JavaScript without jQuery selectors
            js_script = """
                // Handle cookie consent and popups
                try {
                    // Find cookie accept buttons by text content
                    var buttons = document.querySelectorAll('button, a, div[role="button"]');
                    for (var i = 0; i < buttons.length; i++) {
                        var text = buttons[i].textContent.toLowerCase();
                        if (text.includes('accept') || text.includes('accetta') || 
                            text.includes('agree') || text.includes('ok') ||
                            text.includes('consent')) {
                            if (buttons[i].offsetParent !== null) {
                                buttons[i].click();
                                console.log('Clicked consent button');
                                break;
                            }
                        }
                    }
                    
                    // Find and click load more buttons
                    buttons = document.querySelectorAll('button, a');
                    for (var i = 0; i < buttons.length; i++) {
                        var text = buttons[i].textContent.toLowerCase();
                        if (text.includes('load more') || text.includes('show more') ||
                            text.includes('carica') || text.includes('mostra')) {
                            if (buttons[i].offsetParent !== null) {
                                buttons[i].click();
                                console.log('Clicked load more button');
                                break;
                            }
                        }
                    }
                    
                    // Scroll to trigger lazy loading
                    window.scrollTo(0, document.body.scrollHeight / 2);
                    setTimeout(function() {
                        window.scrollTo(0, document.body.scrollHeight);
                    }, 1000);
                } catch(e) {
                    console.error('Error in Selenium script:', e);
                }
            """
            
            # Create SeleniumRequest with all parameters in constructor
            return SeleniumRequest(
                url=url,
                callback=callback,
                wait_time=5,  # Increased wait time for Cloudflare
                meta=meta,
                script=js_script,
                headers=headers,  # Pass headers in constructor
                dont_filter=False,
                errback=self.errback_httpbin
            )
            
        except Exception as e:
            self.logger.error(f"Error creating Selenium request for {url}: {e}")
            return None

    def errback_httpbin(self, failure):
        """Handle request errors with improved Selenium fallback."""
        request = failure.request
        url = request.url
        domain = URLFilters.get_domain(url)
        
        self.logger.error(f"Error processing: {url}")
        self.logger.error(f"Error type: {failure.type}")
        self.logger.error(f"Error value: {failure.value}")
        
        # Log detailed response if present
        response = getattr(failure.value, 'response', None)
        if response is not None:
            self.logger.error(f"[errback] Status: {response.status}")
            self.logger.error(f"[errback] Headers: {dict(response.headers)}")
            body_preview = response.text[:500] if hasattr(response, 'text') else str(response.body[:500])
            self.logger.error(f"[errback] Body preview: {body_preview}")
        
        # Update statistics
        if domain in self.domains:
            self.crawler.stats.inc_value(f'domain/{domain}/errors')
        
        # Handle specific error types
        if hasattr(failure.value, 'response'):
            status = failure.value.response.status
            
            # For 429 (Too Many Requests), always try Selenium
            if status == 429 and self.hybrid_mode:
                if not request.meta.get('selenium') and self.selenium_error_count < self.selenium_max_errors:
                    self.logger.info(f"429 error - attempting Selenium fallback for: {url}")
                    time.sleep(2)  # Brief pause before Selenium attempt
                    yield self.make_selenium_request(
                        url, 
                        self.parse,
                        depth=request.meta.get('depth', 0)
                    )
                else:
                    self.logger.warning(f"429 error persists even with Selenium for: {url}")
            
            # For 403 (Forbidden), try Selenium if not already used
            elif status == 403 and self.hybrid_mode:
                if not request.meta.get('selenium'):
                    self.logger.info(f"403 error - attempting Selenium fallback for: {url}")
                    yield self.make_selenium_request(
                        url,
                        self.parse,
                        depth=request.meta.get('depth', 0)
                    )

    def parse(self, response):
        """Parse response and extract data."""
        if self.crawling_finished:
            self.logger.warning(f"Crawling terminato: blocco parse per {response.url}")
            return
        current_url = response.url
        domain = URLFilters.get_domain(current_url)
        depth = response.meta.get('depth', 0)
        
        if domain not in self.domains:
            self.logger.warning(f"Response from unexpected domain: {domain}")
            return
        
        # Check domain limits
        if self.domain_counts[domain] >= self.max_urls_per_domain:
            if domain not in self.domain_limit_reached:
                self.logger.warning(f"Raggiunto max_urls_per_domain={self.max_urls_per_domain} per {domain}. Crawling bloccato per questo dominio.")
                self.domain_limit_reached.add(domain)
            # Se tutti i domini hanno raggiunto il limite, blocca tutto
            if all(self.domain_counts[d] >= self.max_urls_per_domain for d in self.domains):
                self.crawling_finished = True
                self.logger.warning("Tutti i domini hanno raggiunto il limite: crawling globale terminato.")
            return
        
        # Check total limit
        if self.processed_count >= self.max_total_urls:
            self.crawling_finished = True
            self.logger.warning(f"Raggiunto max_total_urls={self.max_total_urls}. Crawling globale terminato.")
            return
        
        # Update counters
        self.domain_counts[domain] += 1
        self.processed_count += 1
        
        # Update statistics
        self.crawler.stats.inc_value(f'domain/{domain}/pages')
        self.crawler.stats.set_value(f'domain/{domain}/prev_count', self.domain_counts[domain])
        
        # Log progress
        was_selenium = response.meta.get('selenium', False)
        self.logger.info(f"[{self.processed_count}/{self.max_total_urls}] Processing: {current_url} "
                        f"(depth: {depth}, selenium: {was_selenium})")
        
        # Switch to normal requests after threshold in hybrid mode
        if self.hybrid_mode and was_selenium and self.domain_counts[domain] > self.selenium_threshold:
            if self.using_selenium:
                self.using_selenium = False
                self.logger.info(f"Switching to normal requests for {domain} after {self.selenium_threshold} pages")
                self.crawler.stats.set_value('hybrid_mode/switch_time', datetime.now().isoformat())
                self.crawler.stats.set_value('hybrid_mode/switch_url', current_url)
        
        # Extract page item
        loader = PageItemLoader(item=PageItem(), response=response)
        loader.add_value('url', current_url)
        loader.add_value('domain', domain)
        loader.add_value('timestamp', datetime.now().isoformat())
        loader.add_value('depth', depth)
        loader.add_value('referer', response.meta.get('referer'))
        loader.add_value('status_code', response.status)

        # Solo se la risposta è HTML, usa i selettori
        if isinstance(response, HtmlResponse):
            loader.add_xpath('title', '//title/text()')
            loader.add_xpath('meta_description', '//meta[@name="description"]/@content')
            loader.add_xpath('h1_text', '//h1//text()')
            loader.add_value('html_content', response.text[:10000])
            text_content = ' '.join(response.xpath('//body//text()').extract())
            text_content = ' '.join(text_content.split())[:5000]
            loader.add_value('text_content', text_content)
        else:
            loader.add_value('title', '')
            loader.add_value('meta_description', '')
            loader.add_value('h1_text', '')
            loader.add_value('html_content', '')
            loader.add_value('text_content', '')
        
        # Detect template
        template_key = self._get_template_key(response)
        loader.add_value('template', template_key)
        self.templates[domain][template_key].append(current_url)
        self.logger.debug(f"[DEBUG] Aggiunto {current_url} a template {template_key} (dominio {domain}), ora {len(self.templates[domain][template_key])} URL")
        
        yield loader.load_item()
        
        # Extract and follow links
        if depth < self.depth_limit:
            yield from self._extract_and_follow_links(response)

    def _extract_and_follow_links(self, response):
        """Extract and generate requests for links."""
        if self.crawling_finished:
            self.logger.warning(f"Crawling terminato: blocco estrazione link da {response.url}")
            return
        current_url = response.url
        domain = URLFilters.get_domain(current_url)
        depth = response.meta.get('depth', 0)
        
        # Extract links
        link_extractor = AdvancedLinkExtractor(
            allowed_domains=self.allowed_domains
        )
        links = link_extractor.extract_links(response)
        
        # Filter and process links
        requests_generated = 0
        for link in links:
            if self.crawling_finished:
                self.logger.warning("Crawling terminato: blocco generazione richieste in _extract_and_follow_links.")
                break
            # Skip if domain limit reached
            link_domain = URLFilters.get_domain(link)
            if link_domain in self.domains and self.domain_counts[link_domain] >= self.max_urls_per_domain:
                self.logger.info(f"Dominio {link_domain} ha raggiunto il limite, skip link {link}")
                continue
            
            # Skip if total limit reached
            if self.processed_count + requests_generated >= self.max_total_urls:
                self.crawling_finished = True
                self.logger.warning(f"Raggiunto max_total_urls={self.max_total_urls} durante estrazione link. Crawling globale terminato.")
                break
            
            # Skip blocked URLs
            if not URLFilters.is_valid_url(link):
                continue
            
            # Generate request
            try:
                new_depth = depth + 1
                if self.depth_limit and new_depth > self.depth_limit:
                    continue
                
                headers = get_realistic_headers(referer=current_url)
                
                # Decide whether to use Selenium
                use_selenium = False
                if self.hybrid_mode:
                    # Use Selenium for first few pages or if still using selenium mode
                    if self.domain_counts[link_domain] < self.selenium_threshold and self.using_selenium:
                        use_selenium = True
                    elif self.domain_counts[link_domain] < 3:  # Always use Selenium for first 3 pages
                        use_selenium = True
                
                if use_selenium:
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
                        headers=headers,
                        callback=self.parse,
                        meta={
                            'referer': current_url,
                            'dont_redirect': False,
                            'handle_httpstatus_list': [301, 302, 403, 429],
                            'depth': new_depth
                        },
                        errback=self.errback_httpbin,
                        dont_filter=True  # Allow retry with different method
                    )
                    
            except Exception as e:
                self.logger.error(f"Error generating request for {link}: {e}")
        
        self.logger.info(f"Generated {requests_generated} new requests from {current_url}")

    def _get_dom_signature(self, response: HtmlResponse) -> str:
        """Crea una firma univoca basata sulla struttura del DOM."""
        try:
            selectors = ['header', 'footer', 'main', 'nav', 'aside']
            parts = []
            for selector in selectors:
                elements = response.css(selector)
                if elements:
                    child_count = len(elements[0].xpath('./*'))
                    parts.append(f"{selector}:{child_count}")
            parts.append(f"h1:{len(response.css('h1'))}")
            parts.append(f"h2:{len(response.css('h2'))}")
            parts.append(f"h3:{len(response.css('h3'))}")
            signature_str = "|".join(parts)
            return hashlib.md5(signature_str.encode()).hexdigest()
        except Exception as e:
            self.logger.warning(f"Impossibile generare la firma del DOM per {getattr(response, 'url', 'unknown')}: {e}")
            return 'unknown_dom_signature'

    def _get_template_key(self, response):
        """Generate a template key for the page using DOM signature."""
        dom_signature = self._get_dom_signature(response)
        domain = URLFilters.get_domain(response.url)
        template_key = f"{domain}:{dom_signature}"
        # Optionally, store the signature for later analysis
        self.template_structures[domain][template_key] = {'dom_signature': dom_signature}
        return template_key

    def closed(self, reason):
        """Log final statistics when spider closes."""
        self.logger.info(f"Spider closed: {reason}")
        self.logger.info(f"Total URLs processed: {self.processed_count}")
        
        for domain in self.domains:
            count = self.domain_counts[domain]
            self.logger.info(f"Domain {domain}: {count} URLs processed")
            
            # Log top templates
            if domain in self.templates:
                self.logger.info(f"Top templates for {domain}:")
                sorted_templates = sorted(
                    self.templates[domain].items(),
                    key=lambda x: len(x[1]),
                    reverse=True
                )[:5]
                
                for i, (template, urls) in enumerate(sorted_templates, 1):
                    self.logger.info(f"  {i}. {template} - {len(urls)} pages")
            
            # DEBUG: Logga la struttura dei template
            if domain in self.templates:
                for template, urls in self.templates[domain].items():
                    self.logger.info(f"[DEBUG] Template {template} ha {len(urls)} URL prima del salvataggio")
            else:
                self.logger.warning(f"[DEBUG] Nessuna entry self.templates per dominio {domain}")
            
            # --- PATCH: Salvataggio persistente delle occorrenze template ---
            try:
                import pickle
                output_path = self.output_manager.get_path("crawler", f"crawler_state_{self.output_manager.domain_slug}.pkl")
                os.makedirs(output_path.parent, exist_ok=True)
                structures = {}
                for template_key, urls in self.templates[domain].items():
                    normalized_urls = list({self.normalize_url(u) for u in urls if u})
                    structures[template_key] = {
                        "urls": normalized_urls,
                        "url": normalized_urls[0] if normalized_urls else None,
                        "count": len(normalized_urls)
                    }
                state = {"structures": structures}
                with open(output_path, "wb") as f:
                    pickle.dump(state, f)
                self.logger.info(f"Template structures saved to {output_path}")
            except Exception as e:
                self.logger.error(f"Failed to save template structures for {domain}: {e}")