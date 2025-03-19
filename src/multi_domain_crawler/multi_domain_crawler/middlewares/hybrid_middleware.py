# -*- coding: utf-8 -*-
"""
Middleware per la modalità ibrida che alterna tra richieste Selenium e normali.
"""

import logging
import re
from urllib.parse import urlparse

from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.exceptions import NotConfigured, IgnoreRequest

from multi_domain_crawler.utils.url_filters import URLFilters


class HybridDownloaderMiddleware:
    """
    Middleware che gestisce la modalità ibrida di crawling, alternando
    tra Selenium e richieste HTTP normali in base alle necessità.
    """
    
    def __init__(self, settings):
        """
        Inizializza il middleware con le impostazioni fornite.
        
        Args:
            settings (Settings): Impostazioni Scrapy
        """
        self.stats = None
        self.logger = logging.getLogger('hybrid_middleware')
        
        # Indicatori che suggeriscono che una pagina potrebbe richiedere JavaScript
        self.js_indicators = [
            'window.addEventListener', 
            'document.addEventListener',
            'onclick=', 
            'axios', 
            'fetch(',
            'Vue',
            'React',
            'Angular',
            'window.onload',
            'jQuery',
            '$(',
            'SPA_',
            'data-react',
            'data-vue'
        ]
        
        # Cache per domini che necessitano JS
        self.js_domains = set()
        
        # Tipi di URL che probabilmente richiedono JS
        self.likely_js_patterns = [
            r'/ajax/',
            r'/api/',
            r'#',
            r'\?_=\d+',
            r'\.json$',
            r'\.jsp$',
            r'/spa/',
            r'/app/'
        ]
        
        # Soglia per il switch automatico da Selenium a HTTP
        self.selenium_threshold = settings.getint('SELENIUM_THRESHOLD', 30)
        
        self.logger.info("HybridDownloaderMiddleware inizializzato")
    
    @classmethod
    def from_crawler(cls, crawler):
        """
        Crea un'istanza del middleware dal crawler.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
            
        Returns:
            HybridDownloaderMiddleware: Istanza del middleware
        """
        # Verifica se la modalità ibrida è abilitata
        if not crawler.settings.getbool('HYBRID_MODE', False):
            raise NotConfigured('Hybrid mode is disabled')
            
        middleware = cls(crawler.settings)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware
    
    def spider_opened(self, spider):
        """
        Configurazione all'apertura dello spider.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        self.stats = spider.crawler.stats
    
    def process_request(self, request, spider):
        """
        Processa ogni richiesta determinando se usare Selenium o HTTP normale.
        
        Args:
            request (Request): Richiesta da processare
            spider (Spider): Spider in esecuzione
            
        Returns:
            None o HtmlResponse: None per continuare il processing, o una risposta
                                se viene gestita qui
        """
        # Skip se la richiesta è già stata configurata per Selenium
        if 'selenium' in request.meta and request.meta['selenium']:
            return None
            
        # Verifica che l'URL sia valido
        if not URLFilters.is_valid_url(request.url):
            raise IgnoreRequest(f"URL non valido: {request.url}")
            
        # Se lo spider è in modalità ibrida e ha impostato la proprietà using_selenium
        if hasattr(spider, 'hybrid_mode') and spider.hybrid_mode:
            # Verifica se lo switch è già avvenuto
            if hasattr(spider, 'switch_occurred') and spider.switch_occurred:
                # Se lo switch è avvenuto, usa richieste normali
                return None
                
            # Se lo switch non è avvenuto ma lo spider sta usando Selenium,
            # converti tutte le richieste in richieste Selenium fino allo switch
            if hasattr(spider, 'using_selenium') and spider.using_selenium:
                # Controlla quante richieste sono in attesa
                if hasattr(spider.crawler.engine, 'slot'):
                    pending_requests = len(spider.crawler.engine.slot.scheduler)
                    
                    # Se ci sono troppe richieste in coda, considera di passare a HTTP
                    if pending_requests >= self.selenium_threshold:
                        self.logger.info(f"Troppe richieste in coda ({pending_requests}), "
                                         f"passando da Selenium a HTTP")
                        
                        # Segnala allo spider di passare a HTTP
                        spider.using_selenium = False
                        spider.switch_occurred = True
                        
                        # Aggiorna statistiche
                        self.stats.inc_value('hybrid/switch_to_http')
                        
                        # Continua con una richiesta normale
                        return None
                    
                # Usa Selenium per questa richiesta
                return self._create_selenium_request(request)
                
            # Per pagine specifiche che potrebbero richiedere JS
            domain = URLFilters.get_domain(request.url)
            url = request.url.lower()
            
            # Verifica se il dominio è noto per richiedere JS
            if domain in self.js_domains:
                return self._create_selenium_request(request)
                
            # Verifica pattern URL che potrebbero richiedere JS
            if any(re.search(pattern, url) for pattern in self.likely_js_patterns):
                self.js_domains.add(domain)
                return self._create_selenium_request(request)
        
        # Comportamento normale per richieste non Selenium
        return None
    
    def process_response(self, request, response, spider):
        """
        Analizza le risposte per identificare pagine che potrebbero
        richiedere JavaScript per essere renderizzate correttamente.
        
        Args:
            request (Request): Richiesta processata
            response (Response): Risposta ottenuta
            spider (Spider): Spider in esecuzione
            
        Returns:
            Response: La risposta, eventualmente modificata
        """
        # Skip se non è una risposta HTML
        if not isinstance(response, HtmlResponse):
            return response
            
        # Se siamo in modalità ibrida e non abbiamo ancora fatto lo switch
        if hasattr(spider, 'hybrid_mode') and spider.hybrid_mode:
            if not hasattr(spider, 'switch_occurred') or not spider.switch_occurred:
                # Controlla se la pagina è vuota o potrebbe richiedere JS
                if self._page_needs_javascript(response):
                    domain = URLFilters.get_domain(response.url)
                    self.js_domains.add(domain)
                    self.logger.debug(f"Dominio {domain} aggiunto a js_domains")
                    
                    # Aggiorna statistiche
                    self.stats.inc_value('hybrid/detected_js_pages')
                    
                    # Se la richiesta non era già una richiesta Selenium, 
                    # considera di ritentare con Selenium
                    if not request.meta.get('selenium') and not getattr(spider, 'switch_occurred', False):
                        self.logger.debug(f"Riprova con Selenium: {response.url}")
                        return self._create_selenium_request(request)
        
        return response
    
    def _create_selenium_request(self, request):
        """
        Crea una richiesta Selenium da una richiesta normale.
        
        Args:
            request (Request): Richiesta normale
            
        Returns:
            SeleniumRequest: Richiesta Selenium
        """
        try:
            from scrapy_selenium import SeleniumRequest
            
            # Copia meta dalla richiesta originale
            meta = dict(request.meta)
            meta['selenium'] = True
            
            # Crea la richiesta SeleniumRequest
            return SeleniumRequest(
                url=request.url,
                callback=request.callback,
                errback=request.errback,
                wait_time=3,  # Attesa per il rendering JS
                meta=meta,
                headers=request.headers,
                dont_filter=request.dont_filter,
                script="""
                    // Gestisce popup e bottoni comuni
                    try {
                        // Click su pulsanti di accettazione cookie
                        var acceptBtns = document.querySelectorAll("button:contains('Accetta'), button:contains('Accetto'), button:contains('Accept'), button:contains('I agree'), [id*='cookie'] button, [class*='cookie'] button, [id*='consent'] button, [class*='consent'] button");
                        for (var i = 0; i < acceptBtns.length; i++) {
                            if (acceptBtns[i].offsetParent !== null) {
                                acceptBtns[i].click();
                                break;
                            }
                        }
                        
                        // Click su pulsanti "carica altro"
                        var loadMoreBtns = document.querySelectorAll("button:contains('Mostra altro'), button:contains('Carica di più'), button:contains('Load more'), button:contains('Show more'), [class*='load-more'], [class*='show-more']");
                        for (var i = 0; i < loadMoreBtns.length; i++) {
                            if (loadMoreBtns[i].offsetParent !== null) {
                                loadMoreBtns[i].click();
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
            )
        except (ImportError, Exception) as e:
            self.logger.error(f"Errore creando una richiesta Selenium: {e}")
            return None
    
    def _page_needs_javascript(self, response):
        """
        Identifica pagine che probabilmente richiedono JavaScript
        
        Args:
            response (Response): Risposta HTTP
            
        Returns:
            bool: True se la pagina probabilmente richiede JavaScript
        """
        # Verifica dimensione pagina
        if len(response.body) < 5000:
            # Cerca indicatori come elementi script con redirect
            for indicator in self.js_indicators:
                if indicator.encode() in response.body:
                    return True
            
            # Controlla presenza tag body vuoto o quasi vuoto
            body_content = re.search(b'<body[^>]*>(.*?)</body>', response.body, re.DOTALL)
            if body_content:
                body_text = body_content.group(1)
                if len(body_text.strip()) < 200:  # corpo molto piccolo
                    return True
        
        # Verifica tag specifici che indicano framework JS
        js_framework_indicators = [
            b'ng-app',            # Angular
            b'data-reactroot',    # React
            b'vue-app',           # Vue.js
            b'ember-app',         # Ember.js
            b'backbone',          # Backbone.js
            b'svelte',            # Svelte
            b'alpinejs',          # Alpine.js
            b'SPA'                # Generic SPA indicator
        ]
        
        for indicator in js_framework_indicators:
            if indicator in response.body:
                return True
                
        # Altre verifiche
        if b'javascript:' in response.body and b'href="javascript:' in response.body:
            return True
            
        # Controlla URL che potrebbero indicare necessità di JS
        url = response.url.lower()
        if any(re.search(pattern, url) for pattern in self.likely_js_patterns):
            return True
                
        return False