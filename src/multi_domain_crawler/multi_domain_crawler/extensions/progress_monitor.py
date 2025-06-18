# -*- coding: utf-8 -*-
"""
Monitor di progresso in tempo reale per il crawler.
"""

import time
import logging
from datetime import datetime, timedelta

from scrapy import signals
from scrapy.exceptions import NotConfigured
from tqdm import tqdm


class SpiderProgressMonitor:
    """
    Estensione per monitorare e visualizzare lo stato
    di avanzamento dello spider usando tqdm.
    """
    
    def __init__(self, crawler):
        """
        Inizializza il monitor di progresso.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
        """
        self.crawler = crawler
        self.stats = crawler.stats
        self.logger = logging.getLogger('progress_monitor')
        self.progress_bar = None
        self.start_time = None
        self.last_log_time = 0
        
        # Opzioni di visualizzazione da settings con fallback
        settings = crawler.settings
        self.log_interval = settings.getint('PROGRESS_LOG_INTERVAL', 5)  # secondi
        self.show_eta = settings.getbool('PROGRESS_SHOW_ETA', True)
        self.show_domains = settings.getbool('PROGRESS_SHOW_DOMAINS', True)
        self.show_speed = settings.getbool('PROGRESS_SHOW_SPEED', True)
        
        # Integrazione con ConfigurationManager se disponibile nello spider
        self.config_manager = None
        if hasattr(crawler, 'spider') and hasattr(crawler.spider, 'config_manager'):
            self.config_manager = crawler.spider.config_manager
            if self.config_manager:
                self.log_interval = self.config_manager.get('PROGRESS_LOG_INTERVAL', self.log_interval)
                self.show_eta = self.config_manager.get_bool('PROGRESS_SHOW_ETA', self.show_eta)
                self.show_domains = self.config_manager.get_bool('PROGRESS_SHOW_DOMAINS', self.show_domains)
                self.show_speed = self.config_manager.get_bool('PROGRESS_SHOW_SPEED', self.show_speed)
        
        # Collega i segnali
        crawler.signals.connect(self.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(self.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(self.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(self.response_received, signal=signals.response_received)
        
    @classmethod
    def from_crawler(cls, crawler):
        """
        Crea un'istanza del monitor dal crawler.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
            
        Returns:
            SpiderProgressMonitor: Istanza del monitor
        """
        # Verifica se l'estensione è abilitata
        if not crawler.settings.getbool('PROGRESS_MONITOR_ENABLED', True):
            raise NotConfigured
        return cls(crawler)
        
    def spider_opened(self, spider):
        """
        Inizializza la barra di progresso quando lo spider viene avviato.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        try:
            self.start_time = time.time()
            
            # Ottieni la dimensione massima se definita
            max_urls = self._get_max_urls(spider)
            
            # Inizializza la barra di progresso in base al massimo
            if max_urls and max_urls > 0:
                self.progress_bar = tqdm(
                    total=max_urls,
                    unit='page',
                    dynamic_ncols=True, 
                    bar_format='{desc}{percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
                )
            else:
                # Per crawling senza limite, usa un formato diverso senza percentuale
                self.progress_bar = tqdm(
                    unit='page',
                    dynamic_ncols=True,
                    bar_format='{desc} {n_fmt} pages [{elapsed}]'
                )
                
            # Log iniziale
            self.logger.info("Spider avviato: %s", spider.name)
            self.update_progress_bar(spider)
            
        except Exception as e:
            self.logger.error("Errore nell'inizializzazione della barra di progresso: %s", e)
            # Fallback: nessuna barra di progresso
            self.progress_bar = None
        
    def spider_closed(self, spider, reason):
        """
        Chiude la barra di progresso quando lo spider viene chiuso.
        
        Args:
            spider (Spider): Spider in esecuzione
            reason (str): Motivo della chiusura
        """
        try:
            if self.progress_bar is not None:
                self.progress_bar.close()
                
            # Calcola statistiche finali
            end_time = time.time()
            elapsed_time = end_time - self.start_time if self.start_time else 0
            
            # Recupera le statistiche
            pages = self._get_processed_count(spider)
            items = self.stats.get_value('item_scraped_count', 0)
            
            # Log riassuntivo
            self.logger.info("Spider terminato: %s - %s", spider.name, reason)
            self.logger.info("Tempo totale: %.2f secondi", elapsed_time)
            
            if elapsed_time > 0:
                speed = pages / elapsed_time
                self.logger.info("Pagine processate: %d (%.2f pagine/sec)", pages, speed)
            else:
                self.logger.info("Pagine processate: %d", pages)
                
            self.logger.info("Item estratti: %d", items)
            
            # Statistiche per dominio
            if self.show_domains and hasattr(spider, 'domain_counts') and spider.domain_counts:
                self.logger.info("Statistiche per dominio:")
                for domain, count in sorted(spider.domain_counts.items()):
                    domain_speed = self.stats.get_value(f'domain/{domain}/speed', 0)
                    self.logger.info("  %s: %d pagine (%.2f pagine/sec)", 
                                 domain, count, domain_speed)
                    
            # Sommario errori
            error_count = self.stats.get_value('log_count/ERROR', 0)
            if error_count > 0:
                self.logger.info("Errori totali: %d", error_count)
                
            # Statistiche di risposta HTTP
            status_2xx = self.stats.get_value('status_category/2xx', 0)
            status_4xx = self.stats.get_value('status_category/4xx', 0)
            status_5xx = self.stats.get_value('status_category/5xx', 0)
            
            if status_2xx + status_4xx + status_5xx > 0:
                self.logger.info("Risposte HTTP: %d successi, %d errori client, %d errori server", 
                             status_2xx, status_4xx, status_5xx)
                
        except Exception as e:
            self.logger.error("Errore nella chiusura dello spider: %s", e)
        
    def item_scraped(self, item, spider):
        """
        Aggiorna la barra di progresso quando un item viene estratto.
        
        Args:
            item (Item): Item estratto
            spider (Spider): Spider in esecuzione
        """
        self.update_progress_bar(spider)
        
    def response_received(self, response, request, spider):
        """
        Aggiorna la barra di progresso quando viene ricevuta una risposta.
        
        Args:
            response (Response): Risposta ricevuta
            request (Request): Richiesta effettuata
            spider (Spider): Spider in esecuzione
        """
        self.update_progress_bar(spider)
        
    def update_progress_bar(self, spider):
        """
        Aggiorna la barra di progresso con le statistiche correnti.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        current_time = time.time()
        
        # Aggiorna solo ogni log_interval secondi per ridurre overhead
        if current_time - self.last_log_time < self.log_interval:
            return
            
        self.last_log_time = current_time
        
        # Verifica se la barra è stata inizializzata
        if self.progress_bar is None:
            return
            
        try:
            # Recupera statistiche
            processed_count = self._get_processed_count(spider)
            max_urls = self._get_max_urls(spider)
            
            # Calcola velocità e ETA
            elapsed = current_time - self.start_time if self.start_time else 0
            pages_per_second = processed_count / elapsed if elapsed > 0 else 0
            
            eta_str = ""
            if self.show_eta and max_urls and max_urls > processed_count:
                remaining_pages = max_urls - processed_count
                if pages_per_second > 0:
                    remaining_seconds = remaining_pages / pages_per_second
                    eta = datetime.now() + timedelta(seconds=remaining_seconds)
                    eta_str = f" | ETA: {eta.strftime('%H:%M:%S')}"
            
            # Informazioni sul client (Selenium/HTTP)
            client_type = "Selenium" if getattr(spider, 'using_selenium', False) else "HTTP"
            switch_info = " (switched)" if getattr(spider, 'switch_occurred', False) else ""
            client_info = f"Client: {client_type}{switch_info}"
            
            # Informazioni sui domini
            domain_info = ""
            if self.show_domains and hasattr(spider, 'domain_counts') and spider.domain_counts:
                domains = []
                for domain, count in sorted(spider.domain_counts.items(), 
                                          key=lambda x: x[1], reverse=True)[:3]:
                    domains.append(f"{domain}: {count}")
                
                total_domains = len(spider.domain_counts)
                if total_domains > 3:
                    domains.append(f"+{total_domains-3} altri")
                    
                domain_info = f" | Domini: {', '.join(domains)}"
            
            # Informazioni sulla velocità
            speed_info = ""
            if self.show_speed:
                average_speed = self.stats.get_value('crawling_speed/window_avg', pages_per_second)
                speed_info = f" | {pages_per_second:.2f} p/s (avg: {average_speed:.2f})"
                
            # Errori
            error_count = self.stats.get_value('log_count/ERROR', 0)
            error_info = f" | Errori: {error_count}" if error_count > 0 else ""
                
            # Descrizione completa
            desc = f"[{datetime.now().strftime('%H:%M:%S')}] {processed_count} pagine" \
                   f"{speed_info} | {client_info}{domain_info}{eta_str}{error_info} | "
                
            self.progress_bar.set_description(desc)
            
            # Aggiorna il contatore
            self.progress_bar.n = processed_count
            self.progress_bar.refresh()
                
        except Exception as e:
            self.logger.error("Errore nell'aggiornamento della barra di progresso: %s", e)
    
    def _get_processed_count(self, spider):
        """
        Ottiene il numero di pagine processate.
        
        Args:
            spider (Spider): Spider in esecuzione
            
        Returns:
            int: Numero di pagine processate
        """
        # Prima controlla direttamente nello spider
        if hasattr(spider, 'processed_count'):
            return spider.processed_count
            
        # Poi controlla nelle statistiche
        return self.stats.get_value('response_received_count', 0)
    
    def _get_max_urls(self, spider):
        """
        Ottiene il numero massimo di URL da processare.
        
        Args:
            spider (Spider): Spider in esecuzione
            
        Returns:
            int or None: Numero massimo di URL o None se non definito
        """
        # Per spider multi-dominio verifica max_total_urls
        if hasattr(spider, 'max_total_urls') and spider.max_total_urls:
            return spider.max_total_urls
            
        # Per spider singolo dominio verifica max_urls
        if hasattr(spider, 'max_urls') and spider.max_urls:
            return spider.max_urls
            
        # Verifica nelle impostazioni Scrapy
        closespider_pagecount = self.crawler.settings.getint('CLOSESPIDER_PAGECOUNT')
        if closespider_pagecount:
            return closespider_pagecount
            
        return None