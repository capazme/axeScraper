# -*- coding: utf-8 -*-
"""
Middleware di retry avanzato con supporto migliorato per fallback a Selenium.
"""

import logging
import time
import random
from urllib.parse import urlparse

from twisted.internet import defer, reactor
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
        ResponseFailed, TunnelError,
        AttributeError  # Aggiunto per gestire gli AttributeError
    )
    
    # Errori che potrebbero richiedere Selenium
    JS_FALLBACK_ERRORS = (
        TimeoutError, ResponseFailed, AttributeError
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
            if retry_after:
                try:
                    delay = float(retry_after.decode('utf-8'))
                except:
                    delay = self.retry_delay * 4
            else:
                delay = self.retry_delay * 4
            
            # Sempre tentare con Selenium per 429
            if self.try_selenium_fallback and not request.meta.get('selenium'):
                self.logger.info(f"Tentativo fallback a Selenium per 429: {request.url}")
                return self._retry_with_selenium(request, spider, force_delay=delay) or response
            else:
                return self._retry(request, response.status, spider, force_delay=delay) or response
            
        elif response.status == 503:  # Service Unavailable
            # Potrebbe avere header Retry-After
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    delay = float(retry_after.decode('utf-8'))
                except:
                    delay = self.retry_delay * 2
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
            
        # Log dell'eccezione per debug
        self.logger.debug(f"Exception {type(exception).__name__} for {request.url}: {str(exception)}")
        
        # Controlla se è un'eccezione da ritentare
        retry_exc = isinstance(exception, self.EXCEPTIONS_TO_RETRY)
        
        if retry_exc:
            # Per AttributeError, sempre tentare con Selenium
            if isinstance(exception, AttributeError) and self.try_selenium_fallback and not request.meta.get('selenium'):
                self.logger.info(f"AttributeError - tentativo fallback a Selenium per: {request.url}")
                return self._retry_with_selenium(request, spider)
            
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
            reason: Motivo del retry (status code o exception)
            spider (Spider): Spider in esecuzione
            force_delay (float): Ritardo forzato
            exception (Exception): Eccezione sollevata
            
        Returns:
            Request or None: Nuova richiesta o None se limite raggiunto
        """
        retries = request.meta.get('retry_times', 0) + 1
        
        if retries > self.max_retry_times:
            self.logger.warning(f"Raggiunto numero massimo di tentativi ({self.max_retry_times}) per {request.url}")
            if self.stats:
                reason_key = f'retry/max_reached/{reason}' if reason else 'retry/max_reached'
                self.stats.inc_value(reason_key)
            return None
        
        # Calcola il ritardo
        if force_delay is not None:
            delay = force_delay
        else:
            delay = min(self.retry_delay * (2 ** (retries - 1)), self.retry_delay_max)
        
        if self.retry_jitter:
            delay = delay * random.uniform(0.7, 1.3)
        
        # Statistiche
        if self.stats:
            self.stats.inc_value('retry/count')
            self.stats.inc_value(f'retry/attempt/{retries}')
            if reason:
                self.stats.inc_value(f'retry/reason/{reason}')
            domain = urlparse(request.url).netloc
            if domain:
                self.stats.inc_value(f'retry/domain/{domain}')
        
        self.logger.info(f"Retry {retries}/{self.max_retry_times} per {request.url} "
                        f"(motivo: {reason or exception}) in {delay:.2f}s")
        
        # Crea nuova richiesta
        new_request = request.copy()
        new_request.meta['retry_times'] = retries
        new_request.priority = request.priority + self.priority_adjust
        new_request.dont_filter = True
        
        # Usa Deferred per il ritardo
        deferred = defer.Deferred()
        reactor.callLater(delay, lambda: deferred.callback(new_request))
        return deferred
    
    def _retry_with_selenium(self, request, spider, force_delay=None):
        """
        Ritenta una richiesta usando Selenium.
        
        Args:
            request (Request): Richiesta da ritentare
            spider (Spider): Spider in esecuzione
            force_delay (float): Ritardo forzato prima del retry
            
        Returns:
            Request or None: Nuova richiesta o None se non si ritenta
        """
        # Verifica se lo spider supporta la modalità ibrida
        if not hasattr(spider, 'hybrid_mode') or not spider.hybrid_mode:
            return self._retry(request, reason="no_selenium_support", spider=spider)
        
        # Verifica se abbiamo già tentato con Selenium
        if request.meta.get('selenium'):
            self.logger.debug(f"Già tentato con Selenium per {request.url}")
            return self._retry(request, reason="selenium_failed", spider=spider)
        
        # Verifica se lo spider ha il metodo make_selenium_request
        if not hasattr(spider, 'make_selenium_request'):
            self.logger.warning(f"Spider non ha metodo make_selenium_request")
            return self._retry(request, reason="no_selenium_method", spider=spider)
        
        try:
            # Statistiche per i fallback
            if self.stats:
                self.stats.inc_value("retry/selenium_fallback")
            
            # Calcola ritardo
            if force_delay is not None:
                delay = force_delay
            else:
                delay = self.retry_delay * 2
            
            if self.retry_jitter:
                delay = delay * random.uniform(0.7, 1.3)
            
            self.logger.info(f"Fallback a Selenium per {request.url} in {delay:.2f}s")
            
            # Crea richiesta Selenium tramite lo spider
            selenium_request = spider.make_selenium_request(
                request.url,
                request.callback or spider.parse,
                referer=request.meta.get('referer'),
                depth=request.meta.get('depth', 0)
            )
            
            if selenium_request:
                # Copia metadati importanti
                selenium_request.meta['retry_times'] = request.meta.get('retry_times', 0) + 1
                selenium_request.meta['retry_reason'] = "fallback_selenium"
                selenium_request.priority = request.priority + self.priority_adjust
                
                # Usa Deferred per il ritardo
                deferred = defer.Deferred()
                reactor.callLater(delay, lambda: deferred.callback(selenium_request))
                return deferred
            else:
                self.logger.error(f"Impossibile creare richiesta Selenium per {request.url}")
                return None
            
        except Exception as e:
            self.logger.error(f"Errore creando richiesta Selenium fallback: {e}")
            return self._retry(request, reason="selenium_error", spider=spider)