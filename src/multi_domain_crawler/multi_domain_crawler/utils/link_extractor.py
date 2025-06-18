# -*- coding: utf-8 -*-
"""
Estrattore di link avanzato che combina multiple strategie.
"""

import re
import html
import logging
from urllib.parse import urljoin, urldefrag
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from scrapy.linkextractors import LinkExtractor as ScrapyLinkExtractor
from scrapy.http import HtmlResponse, TextResponse

from ..utils.url_filters import URLFilters

logger = logging.getLogger(__name__)


class AdvancedLinkExtractor:
    """
    Classe per l'estrazione dei link che combina multiple strategie:
    1. LinkExtractor standard di Scrapy
    2. BeautifulSoup per pagine complesse
    3. Analisi di elementi interattivi (iframe, meta refresh)
    4. Regex per fallback
    """
    
    def __init__(self, allowed_domains=None, max_workers=4):
        """
        Inizializza l'estrattore con domini consentiti e numero di workers per il processing parallelo.
        
        Args:
            allowed_domains (list, optional): Lista di domini consentiti
            max_workers (int, optional): Numero massimo di worker per il processing parallelo
        """
        self.allowed_domains = allowed_domains or []
        self.max_workers = max_workers
        self.scrapy_extractor = ScrapyLinkExtractor(
            allow_domains=self.allowed_domains,
            deny_extensions=['.css', '.js', '.json', '.xml', '.pdf']
        )
        
        # Regex precompilate per estrazione fallback
        self.href_pattern = re.compile(r'href=["\'](.*?)["\']', flags=re.IGNORECASE)
        self.src_pattern = re.compile(r'src=["\'](.*?)["\']', flags=re.IGNORECASE)
        self.action_pattern = re.compile(r'action=["\'](.*?)["\']', flags=re.IGNORECASE)
        self.meta_refresh_pattern = re.compile(r'<meta[^>]*http-equiv=["\'](refresh)["\'][^>]*content=["\'](.*?)["\'][^>]*>', flags=re.IGNORECASE)
        
        # Inizializzazione ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
    
    def extract_links(self, response, current_domain=None):
        """
        Estrae i link da una risposta HTTP utilizzando multiple strategie.
        
        Args:
            response (Response): Risposta Scrapy
            current_domain (str, optional): Dominio corrente per filtro
            
        Returns:
            set: Set di URL unici estratti e filtrati
        """
        # Verifica che la risposta sia testuale (HTML o testo)
        if not isinstance(response, (HtmlResponse, TextResponse)):
            logger.debug(f"Response non testuale per URL: {response.url} (type: {type(response)})")
            return set()
        
        url = response.url
        html_text = response.text
        base_url = response.url
        
        # Se current_domain non specificato, estrailo dall'URL
        if not current_domain:
            current_domain = URLFilters.get_domain(url)
        
        # Esegui in parallelo le diverse strategie di estrazione
        futures = [
            self.executor.submit(self._extract_with_scrapy, response),
            self.executor.submit(self._extract_with_bs4, html_text, base_url, 'a', 'href'),
            self.executor.submit(self._extract_with_bs4, html_text, base_url, 'iframe', 'src'),
            self.executor.submit(self._extract_with_bs4, html_text, base_url, 'frame', 'src'),
            self.executor.submit(self._extract_with_bs4, html_text, base_url, 'form', 'action'),
            self.executor.submit(self._extract_meta_refresh, html_text, base_url),
            self.executor.submit(self._extract_with_regex, html_text, base_url)
        ]
        
        # Raccolta risultati
        all_links = set()
        for future in futures:
            try:
                links = future.result()
                all_links.update(links)
            except Exception as e:
                logger.error(f"Errore durante l'estrazione dei link: {e}")
        
        # Filtro per dominio e validità
        filtered_links = {
            link for link in all_links 
            if URLFilters.is_valid_url(link) and 
            (not self.allowed_domains or URLFilters.get_domain(link) in self.allowed_domains)
        }
        
        # Se specificato current_domain, filtra solo per quel dominio
        if current_domain:
            domain_links = {link for link in filtered_links if URLFilters.get_domain(link) == current_domain}
            return domain_links
            
        return filtered_links
    
    def _extract_with_scrapy(self, response):
        """
        Estrae i link utilizzando il LinkExtractor standard di Scrapy.
        
        Args:
            response (Response): Risposta Scrapy
            
        Returns:
            set: Set di URL estratti
        """
        try:
            links = {link.url for link in self.scrapy_extractor.extract_links(response)}
            return links
        except Exception as e:
            logger.error(f"Errore nell'estrazione con Scrapy: {e}")
            return set()
    
    def _extract_with_bs4(self, html_text, base_url, tag, attr):
        """
        Estrae i link utilizzando BeautifulSoup, cercando tag e attributi specifici.
        
        Args:
            html_text (str): Testo HTML
            base_url (str): URL base per risolvere link relativi
            tag (str): Tag HTML da cercare
            attr (str): Attributo del tag contenente l'URL
            
        Returns:
            set: Set di URL estratti
        """
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            links = set()
            
            for element in soup.find_all(tag, attrs={attr: True}):
                href = element.get(attr)
                if href:
                    href = html.unescape(href).strip()
                    if href:
                        full_link = urljoin(base_url, href)
                        full_link, _ = urldefrag(full_link)
                        links.add(full_link)
            
            return links
        except Exception as e:
            logger.error(f"Errore nell'estrazione con BeautifulSoup per {tag}.{attr}: {e}")
            return set()
    
    def _extract_meta_refresh(self, html_text, base_url):
        """
        Estrae URL dai meta tag refresh.
        
        Args:
            html_text (str): Testo HTML
            base_url (str): URL base per risolvere link relativi
            
        Returns:
            set: Set di URL estratti
        """
        try:
            links = set()
            
            # Cerca tutti i meta refresh con BeautifulSoup
            soup = BeautifulSoup(html_text, "html.parser")
            meta_tags = soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
            
            for meta in meta_tags:
                content = meta.get("content", "")
                match = re.search(r'url=([^;]+)', content, flags=re.IGNORECASE)
                if match:
                    refresh_url = html.unescape(match.group(1).strip())
                    full_link = urljoin(base_url, refresh_url)
                    full_link, _ = urldefrag(full_link)
                    links.add(full_link)
            
            # Fallback con regex
            matches = self.meta_refresh_pattern.findall(html_text)
            for _, content in matches:
                url_match = re.search(r'url=([^;]+)', content, flags=re.IGNORECASE)
                if url_match:
                    refresh_url = html.unescape(url_match.group(1).strip())
                    full_link = urljoin(base_url, refresh_url)
                    full_link, _ = urldefrag(full_link)
                    links.add(full_link)
            
            return links
        except Exception as e:
            logger.error(f"Errore nell'estrazione dei meta refresh: {e}")
            return set()
    
    def _extract_with_regex(self, html_text, base_url):
        """
        Estrae i link utilizzando espressioni regolari (metodo fallback).
        
        Args:
            html_text (str): Testo HTML
            base_url (str): URL base per risolvere link relativi
            
        Returns:
            set: Set di URL estratti
        """
        try:
            links = set()
            
            # Estrai href
            href_matches = self.href_pattern.findall(html_text)
            for href in href_matches:
                href = html.unescape(href).strip()
                if href:
                    full_link = urljoin(base_url, href)
                    full_link, _ = urldefrag(full_link)
                    links.add(full_link)
            
            # Estrai src
            src_matches = self.src_pattern.findall(html_text)
            for src in src_matches:
                src = html.unescape(src).strip()
                if src:
                    full_link = urljoin(base_url, src)
                    full_link, _ = urldefrag(full_link)
                    links.add(full_link)
            
            # Estrai action
            action_matches = self.action_pattern.findall(html_text)
            for action in action_matches:
                action = html.unescape(action).strip()
                if action:
                    full_link = urljoin(base_url, action)
                    full_link, _ = urldefrag(full_link)
                    links.add(full_link)
            
            return links
        except Exception as e:
            logger.error(f"Errore nell'estrazione con regex: {e}")
            return set()
    
    def close(self):
        """
        Chiude l'executor quando non più necessario.
        """
        if self.executor:
            self.executor.shutdown(wait=False)