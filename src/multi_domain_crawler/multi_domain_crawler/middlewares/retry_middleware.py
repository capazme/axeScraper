# -*- coding: utf-8 -*-
"""
Middleware di retry avanzato con supporto per fallback a Selenium.
"""

import logging
import time
import random
from urllib.parse import urlparse

from twisted.internet import defer
from twisted.internet.error import (
    TimeoutError, DNSLookupError, ConnectionRefusedError,
    ConnectionDone, ConnectError, ConnectionLost
)
from twisted.web.client import ResponseFailed

from scrapy.core.downloader.handlers.http11 import TunnelError
from scrapy.exceptions import NotConfigured
from scrapy.utils.response import response_status_message
from scrapy import signals


class CustomRetryMiddleware:
    """
    Middleware di retry avanzato che supporta:
    - Gestione degli errori comuni
    - Attese esponenziali
    - Fallback a Selenium per errori specifici
    - Statistiche dettagliate
    """
    
    # Errori di connessione da ritentare
    EXCEPTIONS_TO_RETRY = (
        TimeoutError, DNSLookupError, ConnectionRefusedError,
        ConnectionDone, ConnectError, ConnectionLost,
        ResponseFailed, TunnelError
    )
    
    # Errori che potrebbero richiedere Selenium
    JS_FALLBACK_ERRORS = (
        TimeoutError, ResponseFailed
    )
    
    def __init__(self, settings):
        """
        Inizializza il middleware con le impostazioni fornite.
        
        Args:
            settings (Settings): Impostazioni Scrapy
        """
        if not settings.getbool('RETRY_ENABLED'):
            raise NotConfigured
            
        self.max_retry_times = settings.getint('RETRY_TIMES', 3)
        self.retry_http_codes = set(int(x) for x in settings.getlist('RETRY_HTTP_CODES'))
        self.priority_adjust = settings.getint('RETRY_PRIORITY_ADJUST', -1)
        
        # Attese esponenziali con jitter
        self.retry_delay = settings.getfloat('RETRY_DELAY', 1.0)
        self.retry_delay_max = settings.getfloat('RETRY_DELAY_MAX', 60.0)
        self.retry_jitter = settings.getbool('RETRY_JITTER', True)
        
        # Flag per tentare Selenium come fallback
        self.try_selenium_fallback = settings.getbool('RETRY_SELENIUM_FALLBACK', True)
        
        self.stats = None
        self.logger = logging.getLogger('retry_middleware')
    
    @classmethod
    def from_crawler(cls, crawler):
        """
        Crea un'istanza del middleware dal crawler.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
            
        Returns:
            CustomRetryMiddleware: Istanza del middleware
        """
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
    
    def process_response(self, request, response, spider):
        """
        Gestisce i codici di errore HTTP.
        
        Args:
            request (Request): Richiesta processata
            response (Response): Risposta ricevuta
            spider (Spider): Spider in esecuzione
            
        Returns:
            Response o Request: La risposta o una nuova richiesta
        """
        if request.meta.get('dont_retry', False):
            return response
        
        # Verifica se è un codice di errore da ritentare
        if response.status in self.retry_http_codes:
            return self._retry(request, response.status, spider) or response
            
        # Se è 2xx o 3xx, accetta la risposta
        if 200 <= response.status < 400:
            return response
            
        # Casi particolari di errori HTTP
        if response.status == 403:  # Forbidden
            # Potrebbero essere necessarie cookies o headers speciali
            self.logger.debug(f"403 Forbidden: {request.url}")
            if self.try_selenium_fallback and not request.meta.get('selenium'):
                self.logger.info(f"Tentativo fallback a Selenium per 403: {request.url}")
                return self._retry_with_selenium(request, spider) or response
                
        elif response.status == 429:  # Too Many Requests
            # Attesa più lunga prima di ritentare
            self.logger.warning(f"429 Too Many Requests: {request.url}")
            retry_after = response.headers.get('Retry-After')
            delay = float(retry_after) if retry_after else self.retry_delay * 4
            return self._retry(request, response.status, spider, force_delay=delay) or response
            
        elif response.status == 503:  # Service Unavailable
            # Potrebbe avere header Retry-After
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                delay = float(retry_after)
                self.logger.info(f"503 Service Unavailable, retry after {delay}s: {request.url}")
                return self._retry(request, response.status, spider, force_delay=delay) or response
        
        # Altri codici di errore
        return self._retry(request, response.status, spider) or response
    
    def process_exception(self, request, exception, spider):
        """
        Gestisce le eccezioni durante il download.
        
        Args:
            request (Request): Richiesta che ha generato l'eccezione
            exception (Exception): Eccezione sollevata
            spider (Spider): Spider in esecuzione
            
        Returns:
            None o Request: None per continuare o una nuova richiesta
        """
        if request.meta.get('dont_retry', False):
            return None
            
        # Controlla se è un'eccezione da ritentare
        retry_exc = isinstance(exception, self.EXCEPTIONS_TO_RETRY)
        
        if retry_exc:
            # Controlla se potrebbe richiedere Selenium
            if (self.try_selenium_fallback and 
                    isinstance(exception, self.JS_FALLBACK_ERRORS) and 
                    not request.meta.get('selenium')):
                self.logger.info(f"Tentativo fallback a Selenium per errore {type(exception).__name__}: {request.url}")
                return self._retry_with_selenium(request, spider)
                
            # Ritenta normalmente
            return self._retry(request, exception=exception, spider=spider)
    
    def _retry(self, request, reason=None, spider=None, force_delay=None, exception=None):
        """
        Ritenta una richiesta con attesa esponenziale.
        
        Args:
            request (Request): Richiesta da ritentare
            reason (int or Exception, optional): Motivo del retry
            spider (Spider, optional): Spider in esecuzione
            force_delay (float, optional): Delay forzato per il retry
            exception (Exception, optional): Eccezione catturata
        Returns:
            Request or None: Nuova richiesta o None se non si ritenta
        """
        retry_times = request.meta.get('retry_times', 0) + 1

        # Se troppi tentativi, non ritentare più
        if retry_times > self.max_retry_times:
            self.logger.debug(f"Raggiunto numero massimo di tentativi ({self.max_retry_times}) per {request.url}")
            if reason and self.stats:
                self.stats.inc_value(f"retry/max_reached/{reason}")
            return None

        # Log e statistiche
        reason_str = str(reason) if reason else "unknown"
        domain = urlparse(request.url).netloc

        if self.stats:
            self.stats.inc_value("retry/count")
            self.stats.inc_value(f"retry/reason/{reason_str}")
            self.stats.inc_value(f"retry/domain/{domain}")
            self.stats.inc_value(f"retry/attempt/{retry_times}")

        # Calcola ritardo con backoff esponenziale
        if force_delay is not None:
            delay = min(force_delay, self.retry_delay_max)
        else:
            delay = min(self.retry_delay * (2 ** (retry_times - 1)), self.retry_delay_max)

        # Aggiungi jitter per evitare thundering herd
        if self.retry_jitter:
            import random
            delay = delay * (random.uniform(0.5, 1.5))

        self.logger.debug(f"Ritentativo {retry_times}/{self.max_retry_times} per {request.url} in {delay:.2f}s")

        # Ritarda la richiesta
        request.meta['retry_times'] = retry_times
        request.meta['retry_delay'] = delay
        request.meta['retry_reason'] = reason_str
        request.dont_filter = True
        request.priority = request.priority + self.priority_adjust

        # Usa callLater per il ritardo
        from twisted.internet import defer, reactor
        deferred = defer.Deferred()
        reactor.callLater(delay, lambda: deferred.callback(request))
        return deferred

    def _retry_with_selenium(self, request, spider):
        """
        Ritenta una richiesta usando Selenium.
        
        Args:
            request (Request): Richiesta da ritentare
            spider (Spider): Spider in esecuzione
            
        Returns:
            Request or None: Nuova richiesta o None se non si ritenta
        """
        # Verifica se lo spider supporta la modalità ibrida
        if not hasattr(spider, 'hybrid_mode') or not spider.hybrid_mode:
            return self._retry(request, reason="fallback_selenium", spider=spider)
            
        try:
            from scrapy_selenium import SeleniumRequest
            
            # Statistiche per i fallback
            if self.stats:
                self.stats.inc_value("retry/selenium_fallback")
                
            # Copia meta dalla richiesta originale
            meta = dict(request.meta)
            meta['selenium'] = True
            meta['retry_times'] = meta.get('retry_times', 0) + 1
            meta['retry_reason'] = "fallback_selenium"
            
            # Crea la richiesta SeleniumRequest
            selenium_request = SeleniumRequest(
                url=request.url,
                callback=request.callback,
                errback=request.errback,
                wait_time=3,  # Attesa per il rendering JS
                meta=meta,
                headers=request.headers,
                dont_filter=True,
                priority=request.priority + self.priority_adjust,
                script="""
                    // Gestisce popup e bottoni comuni
                    try {
                        // Click su pulsanti di accettazione cookie
                        var acceptBtns = document.querySelectorAll("button:contains('Accetta'), button:contains('Accetto'), button:contains('Accept'), button:contains('I agree'), [id*='cookie'] button, [class*='cookie'] button");
                        for (var i = 0; i < acceptBtns.length; i++) {
                            if (acceptBtns[i].offsetParent !== null) {
                                acceptBtns[i].click();
                                break;
                            }
                        }
                        
                        // Scorrimento pagina
                        window.scrollTo(0, document.body.scrollHeight / 2);
                    } catch(e) {
                        console.error('Error in Selenium script:', e);
                    }
                """
            )
            
            # Ritardo prima del retry
            delay = self.retry_delay * 2
            if self.retry_jitter:
                import random
                delay = delay * (random.uniform(0.7, 1.3))
                
            self.logger.info(f"Fallback a Selenium per {request.url} in {delay:.2f}s")
            
            # Usa callLater per il ritardo
            from twisted.internet import defer, reactor
            deferred = defer.Deferred()
            reactor.callLater(delay, lambda: deferred.callback(selenium_request))
            return deferred
            
        except (ImportError, Exception) as e:
            self.logger.error(f"Errore creando richiesta Selenium fallback: {e}")
            return self._retry(request, reason="selenium_error", spider=spider)