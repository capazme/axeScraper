# -*- coding: utf-8 -*-
"""
Spider principale per il crawling di più domini contemporaneamente.
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

from multi_domain_crawler.items import PageItem, PageItemLoader
from multi_domain_crawler.utils.url_filters import URLFilters
from multi_domain_crawler.utils.link_extractor import AdvancedLinkExtractor
from scrapy_selenium import SeleniumRequest
from ....utils.config import PIPELINE_CONFIG


class MultiDomainSpider(scrapy.Spider):
    """
    Advanced spider for multi-domain crawling with hybrid mode support.
    """
    
    name = 'multi_domain_spider'
    
    # These variables will be initialized dynamically
    allowed_domains = []
    start_urls = []
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the spider with domains and configurations.
        """
        super(MultiDomainSpider, self).__init__(*args, **kwargs)
        
        # Debug the parameters received
        self.logger.info(f"Parameters received: {kwargs}")
        
        # Configuration of domains
        domains_input = kwargs.get('domains', '')
        domains_file = kwargs.get('domains_file', '')
        single_domain = kwargs.get('domain', '')
        
        self.domains = []
        
        # 1. List separated by commas in the 'domains' parameter
        if domains_input:
            self.logger.info(f"Parsing domains input: '{domains_input}'")
            self.domains = [d.strip() for d in domains_input.split(',') if d.strip()]
            
        # 2. File with domain list
        elif domains_file:
            try:
                self.logger.info(f"Attempting to read from file: '{domains_file}'")
                with open(domains_file, 'r') as f:
                    # Supports JSON or plain text
                    if domains_file.endswith('.json'):
                        data = json.load(f)
                        if isinstance(data, list):
                            self.domains = data
                        elif isinstance(data, dict) and 'domains' in data:
                            self.domains = data['domains']
                    else:
                        # One domain per line
                        self.domains = [line.strip() for line in f if line.strip()]
            except Exception as e:
                self.logger.error(f"Error loading domains file: {e}")
                
        # 3. Single domain
        elif single_domain:
            self.logger.info(f"Using single domain: '{single_domain}'")
            self.domains = [single_domain]
        
        # Fallback to demo domain if none specified
        if not self.domains:
            self.logger.warning("No domain specified, using fallback")
            self.domains = ['example.com']
            
        # Normalize domains (remove 'www.' and schemes)
        self.domains = [URLFilters.get_domain(d) for d in self.domains if d]
        
        # Filter empty or invalid domains
        self.domains = [d for d in self.domains if d]
        
        self.logger.info(f"Processed domains: {self.domains}")
            
        # Configure allowed_domains and start_urls
        self.allowed_domains = self.domains.copy()
        
        # Prepare initial URLs (both www and non-www versions)
        self.start_urls = []
        for domain in self.domains:
            self.start_urls.append(f"https://www.{domain}")
            self.start_urls.append(f"https://{domain}")
            
        # Make initial URLs unique
        self.start_urls = list(set(self.start_urls))

        # Configuration limits - read from kwargs with defaults
        # If we could import from utils.config, we could use values from there as defaults
        self.max_urls_per_domain = int(kwargs.get('max_urls_per_domain', 1000)) or 1000
        self.max_total_urls = int(kwargs.get('max_total_urls', 0)) or None
        self.depth_limit = int(kwargs.get('depth_limit', 10)) or 10
        
        # Hybrid mode configuration
        self.hybrid_mode = kwargs.get('hybrid_mode', 'True').lower() == 'true'
        self.request_delay = float(kwargs.get('request_delay', 0.25))
        self.selenium_threshold = int(kwargs.get('selenium_threshold', 30))
        
        # Respect robots.txt
        self.respect_robots = kwargs.get('respect_robots', 'False').lower() == 'true'
        
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
            
        # Log delle configurazioni
        """ self.logger = logging.getLogger(f'{self.name}_logger')
        self.logger.setLevel(logging.INFO)
        
        self.logger.info(f"Spider inizializzato con {len(self.domains)} domini: {', '.join(self.domains)}")
        self.logger.info(f"URL iniziali: {', '.join(self.start_urls)}")
        self.logger.info(f"Configurazione: max_urls_per_domain={self.max_urls_per_domain}, "
                         f"max_total_urls={self.max_total_urls}, "
                         f"hybrid_mode={self.hybrid_mode}, "
                         f"depth_limit={self.depth_limit}") """
    
    def start_requests(self):
        """
        Inizia con richieste personalizzate, assicurando che ci siano
        richieste iniziali valide per ogni dominio.
        
        Yields:
            Request: Richieste iniziali per ogni dominio
        """
        self.logger.info(f"Avvio crawling per {len(self.domains)} domini: {', '.join(self.domains)}")
        self.logger.info(f"URL iniziali: {', '.join(self.start_urls)}")
        
        # Pulisci eventuali stati precedenti
        if hasattr(self, 'domain_counts'):
            self.domain_counts = {domain: 0 for domain in self.domains}
        if hasattr(self, 'processed_count'):
            self.processed_count = 0
        
        # Verifica che gli start_urls siano popolati
        if not self.start_urls:
            self.logger.error("Nessun URL iniziale definito!")
            # Aggiungi URL di fallback per ogni dominio
            self.start_urls = [f"https://www.{domain}" for domain in self.domains]
            
        # Log dettagliato delle richieste iniziali
        for url in self.start_urls:
            self.logger.info(f"Generazione richiesta iniziale per: {url}")
            
            # Se in modalità ibrida, inizia con Selenium
            if self.hybrid_mode and self.using_selenium:
                yield self.make_selenium_request(url, self.parse)
            else:
                yield Request(
                    url=url, 
                    callback=self.parse,
                    meta={
                        'dont_redirect': False, 
                        'handle_httpstatus_list': [301, 302],
                        'depth': 0  # Profondità iniziale
                    },
                    errback=self.errback_httpbin
                )
            
        # Log per debug
        self.logger.info(f"Richieste iniziali generate: {len(self.start_urls)}")
        
    # Modify your is_public_page method to be more permissive
    def is_public_page(self, url):
        # First check disallowed patterns
        url_lower = url.lower()
        
        # Expanded disallowed patterns for non-public content
        disallowed_patterns = [
            '/_layouts/', '/admin/', '/wp-admin/', '/cgi-bin/',
            '/wp-json/', '/wp-content/uploads/', '/xmlrpc.php',
            '/login', '/logout', '/cart', '/checkout'
        ]
        
        for pattern in disallowed_patterns:
            if pattern.lower() in url_lower:
                return False
                
        # Skip static resources but keep the check less restrictive
        extensions_to_skip = ['.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.xml', 
                            '.pdf', '.zip', '.rar', '.exe', '.svg', '.ico']
        
        # Don't use url_has_any_extension - create simpler check
        for ext in extensions_to_skip:
            if url_lower.endswith(ext):
                return False
        
        # By default, consider it public (more inclusive approach)
        return True
    
    def is_user_visible(self, response):
        # More flexible content detection - any of these suggests user-facing content
        has_header = bool(response.css('header, .header, #header, [role="banner"], .navbar, .nav-bar, .top-bar'))
        has_nav = bool(response.css('nav, .nav, #nav, .menu, #menu, [role="navigation"], ul.menu, .navigation'))
        has_main = bool(response.css('main, .main, #main, [role="main"], article, .content, #content, .page-content'))
        has_footer = bool(response.css('footer, .footer, #footer, [role="contentinfo"], .site-footer'))
        
        # Check for basic content indicators
        has_content = bool(response.css('p, h1, h2, h3, div.content, .container, .wrapper'))
        
        # More permissive - only need some indication of being a user page
        return has_content and (has_header or has_nav or has_main or has_footer)

    def has_meaningful_content(self, response):
        # Extract visible text from the page
        texts = response.xpath('//body//text()').getall()
        
        # Join and clean up text
        text_content = ' '.join([t.strip() for t in texts if t.strip()])
        
        # If there's a reasonable amount of text, consider it meaningful
        if len(text_content) > 200:  # Arbitrary threshold
            return True
            
        # Check for common page elements even if text is limited
        if response.css('h1, h2, h3, nav, article, section'):
            return True
            
        return False

    def _extract_js_links(self, response):
        js_links = set()
        
        # Extract URLs from JavaScript
        scripts = response.xpath('//script/text()').getall()
        for script in scripts:
            # Look for URLs in JavaScript
            url_matches = re.findall(r'["\']https?://[^"\']+["\']', script)
            for match in url_matches:
                clean_url = match.strip('\'"')
                if URLFilters.get_domain(clean_url) in self.allowed_domains:
                    js_links.add(clean_url)
                    
            # Look for relative URLs
            rel_matches = re.findall(r'["\'][/][^"\']+["\']', script)
            for match in rel_matches:
                clean_url = match.strip('\'"')
                if clean_url.startswith('/'):
                    full_url = urljoin(response.url, clean_url)
                    js_links.add(full_url)
                    
        return js_links

    def parse(self, response):
        """
        Parser principale delle pagine.
        
        Args:
            response (Response): Risposta HTTP
            
        Yields:
            Item or Request: Item estratti o nuove richieste
        """
        current_url = response.url
        current_domain = URLFilters.get_domain(current_url)
        
        self.logger.info(f"Parsing della pagina: {current_url} (dominio: {current_domain})")
        
        # Verifica se il dominio è tra quelli consentiti
        if current_domain not in self.allowed_domains:
            self.logger.warning(f"Dominio non consentito: {current_domain}, URL: {current_url}")
            return
            
        # Verifica profondità
        depth = response.meta.get('depth', 0)
        if self.depth_limit and depth >= self.depth_limit:
            self.logger.debug(f"Limite profondità raggiunto ({depth}/{self.depth_limit}) per: {current_url}")
            return
            
        # Incrementa contatori
        self.processed_count += 1
        self.domain_counts[current_domain] = self.domain_counts.get(current_domain, 0) + 1
        
        # Verifica limiti di URL per dominio
        if self.max_urls_per_domain and self.domain_counts[current_domain] >= self.max_urls_per_domain:
            self.logger.debug(f"Limite URL raggiunto per dominio {current_domain}")
            return
            
        # Verifica limite totale URL
        if self.max_total_urls and self.processed_count >= self.max_total_urls:
            self.logger.info(f"Raggiunto limite totale URL: {self.max_total_urls}")
            raise CloseSpider(f"Raggiunto limite massimo totale di {self.max_total_urls} URL")
            
        # Aggiorna l'albero URL e strutture
        self._update_url_structure(response)
        
        # Estrai item dalla pagina
        item = self._extract_page_item(response)
        if item:
            yield item
        
        # Estrai link con AdvancedLinkExtractor (solo per dominio corrente)
        links = self.link_extractor.extract_links(response, current_domain)
        self.logger.debug(f"Initial links extracted: {len(links)}")
        for link in links:
            self.logger.debug(f"  - {link}")
            
        # Add JavaScript links
        js_links = self._extract_js_links(response)
        links.update(js_links)
        
        # Filtro aggiuntivo
        filtered_links = {
            link for link in links 
            if URLFilters.is_valid_url(link) and URLFilters.get_domain(link) == current_domain and self.is_public_page(link)
        }
        self.logger.debug(f"Links after filtering: {len(filtered_links)}")
        for link in filtered_links:
            self.logger.debug(f"  - {link}")
        
        # Verifica modalità ibrida
        if self.hybrid_mode and not self.switch_occurred:
            pending_requests = len(self.crawler.engine.slot.scheduler)
            if pending_requests >= self.selenium_threshold:
                self.logger.info(f"Passaggio da Selenium a HTTP normale (pending: {pending_requests})")
                self.using_selenium = False
                self.switch_occurred = True
                
                # Aggiorna statistiche
                self.crawler.stats.set_value('hybrid_mode/switch_time', datetime.now().isoformat())
                self.crawler.stats.set_value('hybrid_mode/switch_url', current_url)
        
        # Log avanzamento
        self.logger.info(f"Progressi: {self.processed_count} totali, {current_domain}: {self.domain_counts[current_domain]}")
        
        # Genera richieste per gli URL trovati
        requests_generated = 0
        for link in filtered_links:
            # Skip se abbiamo raggiunto il limite
            link_domain = URLFilters.get_domain(link)
            if self.max_urls_per_domain and self.domain_counts.get(link_domain, 0) >= self.max_urls_per_domain:
                continue
                
            if self.max_total_urls and self.processed_count >= self.max_total_urls:
                break
            
            # Verifica robots.txt se richiesto
            if self.respect_robots and not self._can_fetch(link):
                self.logger.debug(f"URL bloccato da robots.txt: {link}")
                continue
                
            # Genera la richiesta appropriata in base alla modalità
            try:
                # Incrementa profondità
                new_depth = depth + 1
                
                # Skip se superiamo il limite di profondità
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
                            'depth': new_depth,
                            'dont_filter': True  # Override duplicate filtering
                        },
                        errback=self.errback_httpbin
                    )
            except Exception as e:
                self.logger.error(f"Errore generando richiesta per {link}: {e}")
                
        self.logger.info(f"Generate {requests_generated} nuove richieste da {current_url}")
    
    def errback_httpbin(self, failure):
        """
        Gestione degli errori nelle richieste.
        
        Args:
            failure (Failure): Oggetto Twisted Failure
            
        Yields:
            Request: Eventuale nuova richiesta in caso di fallback
        """
        # Log dettagliato dell'errore
        request = failure.request
        url = request.url
        domain = URLFilters.get_domain(url)
        
        self.logger.error(f"Errore processando: {url}")
        self.logger.error(f"Tipo errore: {failure.type}")
        self.logger.error(f"Valore errore: {failure.value}")
        
        # Aggiorna statistiche
        if domain in self.domains:
            self.crawler.stats.inc_value(f'domain/{domain}/errors')
        
        # Prova a usare Selenium come fallback se in modalità ibrida
        if self.hybrid_mode and not request.meta.get('selenium'):
            self.logger.info(f"Tentativo fallback con Selenium per: {url}")
            yield self.make_selenium_request(
                url, 
                self.parse,
                depth=request.meta.get('depth', 0)
            )
    
    def make_selenium_request(self, url, callback, referer=None, depth=0):
        """
        Crea una richiesta Selenium.
        
        Args:
            url (str): URL della richiesta
            callback (callable): Funzione di callback
            referer (str, optional): URL referer
            depth (int, optional): Profondità della richiesta
            
        Returns:
            SeleniumRequest or None: Richiesta Selenium o None in caso di errore
        """
        # Verifica che l'URL sia valido
        if not URLFilters.is_valid_url(url):
            self.logger.warning(f"URL non valido scartato: {url}")
            return None
            
        try:            
            # Normalizza URL
            url = URLFilters.normalize_url(url)
            if not url:
                return None
            
            # Preparazione meta
            meta = {
                'selenium': True,
                'referer': referer,
                'depth': depth
            }
            
            # Script JavaScript da eseguire
            js_script = """
                // Gestisce popup e bottoni comuni
                try {
                    // Click su pulsanti di accettazione cookie
                    var acceptBtns = document.querySelectorAll(
                        "button:contains('Accetta'), button:contains('Accetto'), " +
                        "button:contains('Accept'), button:contains('I agree'), " +
                        "[id*='cookie'] button, [class*='cookie'] button, " +
                        "[id*='consent'] button, [class*='consent'] button"
                    );
                    for (var i = 0; i < acceptBtns.length; i++) {
                        if (acceptBtns[i].offsetParent !== null) {
                            acceptBtns[i].click();
                            console.log('Cookie button clicked');
                            break;
                        }
                    }
                    
                    // Click su pulsanti "carica altro"
                    var loadMoreBtns = document.querySelectorAll(
                        "button:contains('Mostra altro'), button:contains('Carica di più'), " +
                        "button:contains('Load more'), button:contains('Show more'), " +
                        "[class*='load-more'], [class*='show-more']"
                    );
                    for (var i = 0; i < loadMoreBtns.length; i++) {
                        if (loadMoreBtns[i].offsetParent !== null) {
                            loadMoreBtns[i].click();
                            console.log('Load more button clicked');
                            break;
                        }
                    }
                    
                    // Scorrimento pagina
                    window.scrollTo(0, document.body.scrollHeight / 2);
                    setTimeout(function() {
                        window.scrollTo(0, document.body.scrollHeight);
                    }, 1000);
                } catch(e) {
                    console.error('Error in Selenium script:', e);
                }
            """
            
            return SeleniumRequest(
                url=url,
                callback=callback,
                wait_time=3,  # Secondi di attesa per il caricamento JS
                meta=meta,
                script=js_script,
                dont_filter=False,
                errback=self.errback_httpbin
            )
        except Exception as e:
            self.logger.error(f"Errore creando richiesta Selenium per {url}: {e}")
            return None
    
    def _extract_page_item(self, response):
        """
        Estrae informazioni dalla pagina in un Item strutturato.
        
        Args:
            response (Response): Risposta HTTP
            
        Returns:
            Item or None: Item estratto o None in caso di errore
        """
        try:
            # Crea loader per l'item con il selettore della risposta
            loader = PageItemLoader(item=PageItem(), selector=response)
            
            # Dati base
            url = response.url
            domain = URLFilters.get_domain(url)
            referer = response.meta.get('referer')
            
            # Verifica se il dominio è tra quelli consentiti
            if domain not in self.domains:
                return None
                
            # URL e meta
            loader.add_value('url', url)
            loader.add_value('domain', domain)
            loader.add_value('referer', referer)
            loader.add_value('status', response.status)
            loader.add_value('depth', response.meta.get('depth', 0))
            loader.add_value('timestamp', datetime.now().isoformat())
            loader.add_value('crawl_time', time.time())
            
            # Template URL
            template = URLFilters.get_url_template(url)
            loader.add_value('template', template)
            
            # Estrai contenuto
            loader.add_css('title', 'title::text')
            loader.add_css('meta_description', 'meta[name="description"]::attr(content)')
            loader.add_css('meta_keywords', 'meta[name="keywords"]::attr(content)')
            loader.add_css('h1', 'h1::text')
            
            # Estrai links
            links = self.link_extractor.extract_links(response)
            loader.add_value('links', list(links))
            
            # Opzionale: salva il contenuto HTML
            if self.settings.getbool('PIPELINE_KEEP_HTML', False):
                loader.add_value('content', response.text)
            
            # Aggiorna statistiche
            self.crawler.stats.inc_value(f'domain/{domain}/items')
            
            return loader.load_item()
        except Exception as e:
            self.logger.error(f"Errore estraendo item da {response.url}: {e}")
            return None
        
    def _update_url_structure(self, response):
        """
        Aggiorna strutture URL e template.
        
        Args:
            response (Response): Risposta HTTP
        """
        url = response.url
        domain = URLFilters.get_domain(url)
        
        # Genera template
        template = URLFilters.get_url_template(url)
        
        # Memorizza struttura template (con dominio come prefisso)
        domain_template = f"{domain}:{template}"
        
        # Cerca template simili
        similar = self._find_similar_template(domain_template)
        if similar:
            # Incrementa contatore
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
            # Nuovo template
            self.structures[domain_template] = {
                'template': domain_template,
                'url': url,
                'domain': domain,
                'count': 1
            }
    
    def _find_similar_template(self, template, threshold=0.90):
        """
        Trova template simili già incontrati.
        
        Args:
            template (str): Template da confrontare
            threshold (float, optional): Soglia di similarità
            
        Returns:
            str or None: Template simile o None
        """
        for existing in self.structures.keys():
            # Confronta solo template dello stesso dominio
            if template.split(':', 1)[0] == existing.split(':', 1)[0]:
                ratio = difflib.SequenceMatcher(None, existing, template).ratio()
                if ratio >= threshold:
                    return existing
        return None
    
    def _can_fetch(self, url):
        """
        Verifica se l'URL può essere scaricato secondo robots.txt.
        
        Args:
            url (str): URL da verificare
            
        Returns:
            bool: True se l'URL può essere scaricato
        """
        if not self.respect_robots:
            return True
            
        try:
            from scrapy.robotstxt import RobotFileParser
            
            domain = URLFilters.get_domain(url)
            
            # Crea parser per questo dominio se non esiste
            if domain not in self.robots_parsers:
                self.robots_parsers[domain] = RobotFileParser()
                robots_url = f"https://{domain}/robots.txt"
                
                # Prova a scaricare robots.txt
                try:
                    request = Request(robots_url)
                    response = self.crawler.engine.download(request)
                    if response.status == 200:
                        self.robots_parsers[domain].parse(response.body.splitlines())
                    else:
                        # Se non è disponibile, consenti tutto
                        return True
                except Exception:
                    # In caso di errore, consenti tutto
                    return True
            
            # Controlla se il parser consente l'URL
            return self.robots_parsers[domain].can_fetch("*", url)
        except Exception as e:
            self.logger.error(f"Errore verificando robots.txt per {url}: {e}")
            return True  # In caso di errore, consenti
    
    def closed(self, reason):
        """
        Operazioni di chiusura dello spider.
        
        Args:
            reason (str): Motivo della chiusura
        """
        self.logger.info(f"Spider chiuso: {reason}")
        self.logger.info(f"URL totali processati: {self.processed_count}")
        
        # Statistiche per dominio
        for domain, count in sorted(self.domain_counts.items(), key=lambda x: x[1], reverse=True):
            self.logger.info(f"Dominio {domain}: {count} URL processati")
        
        # Chiudi l'estrattore di link
        if hasattr(self, 'link_extractor'):
            self.link_extractor.close()
            
        # Template più comuni per ogni dominio
        domain_templates = defaultdict(list)
        for template, data in self.structures.items():
            domain = data.get('domain', '')
            domain_templates[domain].append((template, data))
        
        # Log dei template più comuni per ogni dominio
        for domain, templates in domain_templates.items():
            sorted_templates = sorted(templates, key=lambda x: x[1]['count'], reverse=True)
            
            self.logger.info(f"Template più comuni per {domain}:")
            for i, (template, data) in enumerate(sorted_templates[:5], 1):
                self.logger.info(f"  {i}. {template} - {data['count']} pagine")