# -*- coding: utf-8 -*-
"""
Utilità per il filtraggio e la manipolazione degli URL.
"""

import re
import html
from urllib.parse import urlparse, urljoin, urldefrag


class URLFilters:
    """
    Classe che fornisce metodi statici per filtrare e manipolare URL.
    """
    
    # Estensioni di file da escludere
    EXCLUDED_EXTENSIONS = {
        # Immagini
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff',
        # Documenti
        '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv',
        # Audio e video
        '.mp3', '.mp4', '.avi', '.mov', '.flv', '.wmv', '.wav', '.ogg',
        # Archivi
        '.zip', '.rar', '.tar', '.gz', '.7z',
        # CSS/JS
        '.css', '.js', '.json', '.xml',
        # Altri
        '.txt', '.md', '.exe', '.dmg', '.iso', '.apk', '.ipa'
    }
    
    # Schemi URL consentiti
    ALLOWED_SCHEMES = {'http', 'https', ''}
    
    # Pattern di URL da escludere
    EXCLUDED_PATTERNS = [
        r'^javascript:',      # Link JavaScript
        r'^mailto:',          # Email
        r'^tel:',             # Telefono
        r'^data:',            # Data URI
        r'^#',                # Ancore
        r'^about:',           # About
        r'^file:',            # File locale
        r'^ftp:',             # FTP
    ]
    
    # Stringhe da evitare negli URL (percorsi comuni per file statici)
    EXCLUDED_PATHS = [
        '/wp-content/uploads/',
        '/assets/',
        '/static/',
        '/images/',
        '/js/',
        '/css/',
        '/fonts/',
        '/download/',
        '/downloads/',
        '/media/',
        '/admin/',
        '/wp-admin/',
        '/wp-json/',
        '/wp-login',
        '/wp-includes/',
        '/xmlrpc.php',
    ]
    
    @staticmethod
    def is_valid_url(url):
        """
        Verifica se un URL è valido per il crawling.
        
        Args:
            url (str): URL da verificare
            
        Returns:
            bool: True se l'URL è valido, False altrimenti
        """
        if not url or not isinstance(url, str):
            return False
            
        # Decodifica HTML entities
        url = html.unescape(url.strip())
        
        # Verifica pattern da escludere
        for pattern in URLFilters.EXCLUDED_PATTERNS:
            if re.match(pattern, url, re.IGNORECASE):
                return False
                
        # Verifica lo schema
        try:
            parsed = urlparse(url)
            if parsed.scheme and parsed.scheme.lower() not in URLFilters.ALLOWED_SCHEMES:
                return False
        except Exception:
            return False
            
        # Verifica estensione
        if any(url.lower().endswith(ext) for ext in URLFilters.EXCLUDED_EXTENSIONS):
            return False
            
        # Verifica percorsi da escludere
        if any(path in url.lower() for path in URLFilters.EXCLUDED_PATHS):
            return False
        
        return True
    
    @staticmethod
    def normalize_url(url, base_url=None):
        """
        Normalizza un URL, rimuovendo frammenti e aggiungendo uno schema se necessario.
        
        Args:
            url (str): URL da normalizzare
            base_url (str, optional): URL base per la risoluzione di URL relativi
            
        Returns:
            str: URL normalizzato o None se non valido
        """
        if not url:
            return None
            
        # Decodifica HTML entities
        url = html.unescape(url.strip())
        
        # Risolvi URL relativi se presente un base_url
        if base_url:
            url = urljoin(base_url, url)
        
        # Rimuovi frammenti (#)
        url, _ = urldefrag(url)
        
        # Assicurati che ci sia uno schema
        if not urlparse(url).scheme:
            # URL senza schema, aggiungi https:// come default
            if url.startswith('//'):
                url = 'https:' + url
            else:
                url = 'https://' + url
        
        return url

    @staticmethod
    def get_domain(url):
        """
        Estrae il dominio da un URL o restituisce il dominio se già in formato dominio.
        
        Args:
            url (str): URL o dominio
            
        Returns:
            str: Dominio estratto o None se non valido
        """
        if not url:
            return None
            
        try:
            # Se è già un dominio semplice (non contiene schema o percorso)
            if '/' not in url and '://' not in url:
                domain = url.lower()
                # Rimuovi www. se presente
                if domain.startswith('www.'):
                    domain = domain[4:]
                return domain
                
            # Altrimenti, è un URL completo, estrarre il dominio
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            
            # Rimuovi www. dal dominio
            if netloc.startswith('www.'):
                netloc = netloc[4:]
                
            return netloc or None  # Assicurati di restituire None se netloc è vuoto
        except Exception:
            return None
        
    @staticmethod
    def is_same_domain(url1, url2):
        """
        Verifica se due URL appartengono allo stesso dominio.
        
        Args:
            url1 (str): Primo URL
            url2 (str): Secondo URL
            
        Returns:
            bool: True se gli URL appartengono allo stesso dominio, False altrimenti
        """
        domain1 = URLFilters.get_domain(url1)
        domain2 = URLFilters.get_domain(url2)
        
        return domain1 and domain2 and domain1 == domain2
    
    @staticmethod
    def get_url_template(url):
        """
        Genera un template da un URL, sostituendo numeri e identificatori con placeholder.
        
        Args:
            url (str): URL da cui generare il template
            
        Returns:
            str: Template generato
        """
        try:
            url = html.unescape(url)
            parsed = urlparse(url)
            
            # Suddividi il percorso in segmenti
            segments = [seg for seg in parsed.path.split('/') if seg]
            normalized_segments = []
            
            # Normalizza ogni segmento
            for seg in segments:
                # Sostituisci numeri con {num}
                seg_norm = re.sub(r'\d+', '{num}', seg)
                
                # Identifica slug (testo-con-trattini)
                if '-' in seg_norm and len(seg_norm) > 10:
                    seg_norm = '{slug}'
                    
                # Identifica UUID/GUID
                if re.match(r'^[a-f0-9\-]{8,}$', seg, re.IGNORECASE):
                    seg_norm = '{id}'
                    
                normalized_segments.append(seg_norm)
                
            # Ricostruisci il percorso normalizzato
            template = '/' + '/'.join(normalized_segments)
            
            # Aggiungi dominio come prefisso per templates multi-dominio
            domain = URLFilters.get_domain(url)
            if domain:
                template = f"{domain}:{template}"
                
            return template
        except Exception:
            return url  # Fallback al URL originale