# -*- coding: utf-8 -*-
"""
Collettore di statistiche avanzato per il crawler.
"""

import time
import logging
from datetime import datetime
from collections import defaultdict

from scrapy.statscollectors import StatsCollector


class EnhancedStatsCollector(StatsCollector):
    """
    Collettore di statistiche avanzato che tiene traccia di metriche
    aggiuntive come velocità di crawling, statistiche per dominio e più.
    """
    
    def __init__(self, crawler):
        """
        Inizializza il collettore di statistiche.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
        """
        super(EnhancedStatsCollector, self).__init__(crawler)
        self.crawler = crawler
        self.start_time = time.time()
        
        # Store per metriche avanzate
        self._domain_stats = defaultdict(lambda: defaultdict(int))
        self._status_stats = defaultdict(int)
        self._crawling_speed_history = []
        self._crawling_speed_window = []
        
        # Intervallo di tempo per il calcolo della velocità (in secondi)
        self.speed_interval = 30
        self.last_speed_check = self.start_time
        self.items_since_last_check = 0
        
        # Finestra di tempo per calcolare velocità media (ultimi N valori)
        self.speed_window_size = 10
        
        self.logger = logging.getLogger('stats_collector')
        self.logger.info("EnhancedStatsCollector inizializzato")
    
    def set_value(self, key, value, spider=None):
        """
        Imposta un valore nelle statistiche.
        
        Args:
            key (str): Chiave della statistica
            value: Valore della statistica
            spider (Spider, optional): Spider associato
        """
        super(EnhancedStatsCollector, self).set_value(key, value, spider)
        
        # Traccia statistiche per dominio
        if key.startswith('domain/'):
            parts = key.split('/')
            if len(parts) >= 3:
                domain = parts[1]
                stat_type = '/'.join(parts[2:])
                self._domain_stats[domain][stat_type] = value
        
        # Traccia statistiche di codici HTTP
        elif key.startswith('downloader/response_status_count/'):
            status_code = key.split('/')[-1]
            try:
                self._status_stats[int(status_code)] = value
            except (ValueError, TypeError):
                pass
    
    def inc_value(self, key, count=1, start=0, spider=None):
        """
        Incrementa un valore nelle statistiche.
        
        Args:
            key (str): Chiave della statistica
            count (int, optional): Valore di incremento
            start (int, optional): Valore iniziale se non esiste
            spider (Spider, optional): Spider associato
        """
        super(EnhancedStatsCollector, self).inc_value(key, count, start, spider)
        
        # Traccia statistiche per dominio
        if key.startswith('domain/'):
            parts = key.split('/')
            if len(parts) >= 3:
                domain = parts[1]
                stat_type = '/'.join(parts[2:])
                self._domain_stats[domain][stat_type] += count
        
        # Traccia statistiche di codici HTTP
        elif key.startswith('downloader/response_status_count/'):
            status_code = key.split('/')[-1]
            try:
                self._status_stats[int(status_code)] += count
            except (ValueError, TypeError):
                pass
        
        # Traccia elementi processati per calcolo velocità
        if key == 'item_scraped_count' or key == 'response_received_count':
            self.items_since_last_check += count
            
            # Calcola velocità ogni intervallo
            current_time = time.time()
            if current_time - self.last_speed_check >= self.speed_interval:
                elapsed = current_time - self.last_speed_check
                speed = self.items_since_last_check / elapsed if elapsed > 0 else 0
                
                # Aggiorna finestra scorrevole
                self._crawling_speed_window.append(speed)
                if len(self._crawling_speed_window) > self.speed_window_size:
                    self._crawling_speed_window.pop(0)
                
                # Salva nella storia completa
                self._crawling_speed_history.append(speed)
                
                # Imposta statistiche di velocità
                self.set_value('crawling_speed/current_items_per_sec', speed, spider)
                
                if self._crawling_speed_window:
                    window_avg = sum(self._crawling_speed_window) / len(self._crawling_speed_window)
                    self.set_value('crawling_speed/window_avg', window_avg, spider)
                
                if self._crawling_speed_history:
                    total_avg = sum(self._crawling_speed_history) / len(self._crawling_speed_history)
                    self.set_value('crawling_speed/total_avg', total_avg, spider)
                    
                    # Calcola anche la velocità per l'ultimo minuto, 5 minuti e 15 minuti
                    self._calculate_time_window_speeds(spider)
                
                # Calcola anche statistiche per dominio
                self._calculate_domain_speeds(spider)
                
                # Reset contatori
                self.last_speed_check = current_time
                self.items_since_last_check = 0
    
    def get_value(self, key, default=None, spider=None):
        """
        Ottiene un valore dalle statistiche.
        
        Args:
            key (str): Chiave della statistica
            default: Valore di default se non esiste
            spider (Spider, optional): Spider associato
            
        Returns:
            Il valore della statistica o il default
        """
        # Prima controlla nel store standard
        value = super(EnhancedStatsCollector, self).get_value(key, None, spider)
        if value is not None:
            return value
            
        # Poi controlla nelle statistiche per dominio
        if key.startswith('domain/'):
            parts = key.split('/')
            if len(parts) >= 3:
                domain = parts[1]
                stat_type = '/'.join(parts[2:])
                return self._domain_stats[domain].get(stat_type, default)
        
        return default
    
    def get_stats(self, spider=None):
        """
        Ottiene tutte le statistiche e aggiunge metriche calcolate.
        
        Args:
            spider (Spider, optional): Spider associato
            
        Returns:
            dict: Dizionario con tutte le statistiche
        """
        # Ottieni le statistiche di base
        stats = super(EnhancedStatsCollector, self).get_stats(spider)
        
        # Calcola il tempo totale di esecuzione
        elapsed_time = time.time() - self.start_time
        stats['elapsed_time_seconds'] = elapsed_time
        
        # Aggiungi statistiche sulle richieste e tempi medi
        responses = stats.get('response_received_count', 0)
        
        if responses > 0 and elapsed_time > 0:
            # Velocità media in pagine/sec
            stats['pages_per_second'] = responses / elapsed_time
            
            # Velocità media in pagine/min
            stats['pages_per_minute'] = responses / (elapsed_time / 60)
            
            # Tempo medio per pagina
            stats['avg_time_per_page_ms'] = (elapsed_time / responses) * 1000
        
        # Aggiungi statistiche sui codici di stato HTTP
        success_count = sum(count for code, count in self._status_stats.items() if 200 <= code < 300)
        redirect_count = sum(count for code, count in self._status_stats.items() if 300 <= code < 400)
        client_error_count = sum(count for code, count in self._status_stats.items() if 400 <= code < 500)
        server_error_count = sum(count for code, count in self._status_stats.items() if 500 <= code < 600)
        
        stats['status_category/2xx'] = success_count
        stats['status_category/3xx'] = redirect_count
        stats['status_category/4xx'] = client_error_count
        stats['status_category/5xx'] = server_error_count
        
        if responses > 0:
            stats['status_category/2xx_percent'] = (success_count / responses) * 100
            stats['status_category/3xx_percent'] = (redirect_count / responses) * 100
            stats['status_category/4xx_percent'] = (client_error_count / responses) * 100
            stats['status_category/5xx_percent'] = (server_error_count / responses) * 100
        
        # Aggiungi statistiche per dominio
        domain_summary = {}
        for domain, domain_data in self._domain_stats.items():
            domain_summary[domain] = {
                'pages': domain_data.get('pages', 0),
                'success': domain_data.get('success', 0),
                'errors': domain_data.get('errors', 0),
                'items': domain_data.get('items', 0)
            }
        
        stats['domains'] = domain_summary
        
        return stats
    
    def _calculate_domain_speeds(self, spider):
        """
        Calcola le velocità di crawling per dominio.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        if not hasattr(spider, 'domain_counts'):
            return
            
        # Calcola la velocità per ogni dominio
        for domain, count in spider.domain_counts.items():
            prev_count = self.get_value(f'domain/{domain}/prev_count', 0, spider)
            domain_speed = (count - prev_count) / self.speed_interval if self.speed_interval > 0 else 0
            
            self.set_value(f'domain/{domain}/prev_count', count, spider)
            self.set_value(f'domain/{domain}/speed', domain_speed, spider)
    
    def _calculate_time_window_speeds(self, spider):
        """
        Calcola le velocità di crawling per finestre temporali diverse.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        # Estrai i timestamp e i valori dalla storia
        now = time.time()
        
        # Controlla se ci sono abbastanza dati per calcolare le medie
        if not self._crawling_speed_history:
            return
            
        # Calcola velocità per diverse finestre temporali
        one_min_ago = now - 60
        five_min_ago = now - 300
        fifteen_min_ago = now - 900
        
        # Ultimo minuto
        one_min_speeds = [s for t, s in zip(self._crawling_speed_history, self._crawling_speed_window) 
                          if t >= one_min_ago]
        if one_min_speeds:
            one_min_avg = sum(one_min_speeds) / len(one_min_speeds)
            self.set_value('crawling_speed/1min_avg', one_min_avg, spider)
            
        # Ultimi 5 minuti
        five_min_speeds = [s for t, s in zip(self._crawling_speed_history, self._crawling_speed_window)
                          if t >= five_min_ago]
        if five_min_speeds:
            five_min_avg = sum(five_min_speeds) / len(five_min_speeds)
            self.set_value('crawling_speed/5min_avg', five_min_avg, spider)
            
        # Ultimi 15 minuti
        fifteen_min_speeds = [s for t, s in zip(self._crawling_speed_history, self._crawling_speed_window)
                             if t >= fifteen_min_ago]
        if fifteen_min_speeds:
            fifteen_min_avg = sum(fifteen_min_speeds) / len(fifteen_min_speeds)
            self.set_value('crawling_speed/15min_avg', fifteen_min_avg, spider)