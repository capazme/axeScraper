# -*- coding: utf-8 -*-
"""
Pipeline per l'elaborazione e il salvataggio dei dati per dominio.
"""

import os
import json
import pickle
import logging
from datetime import datetime
from collections import defaultdict

import pandas as pd
from scrapy.exceptions import DropItem

from multi_domain_crawler.utils.url_filters import URLFilters


class MultiDomainPipeline:
    """
    Pipeline specializzata per gestire output e statistiche
    separate per ogni dominio.
    """
    
    def __init__(self, output_dir, keep_html=False, report_format='all'):
        """
        Inizializza la pipeline.
        
        Args:
            output_dir (str): Directory per i dati di output
            keep_html (bool): Se conservare il contenuto HTML completo
            report_format (str): Formato dei report ('all', 'markdown', 'json', 'csv')
        """
        self.output_dir = output_dir
        self.keep_html = keep_html
        self.report_format = report_format
        
        # Dati per dominio
        self.domain_data = defaultdict(lambda: {
            'url_tree': defaultdict(set),
            'structures': {},
            'unique_pages': set(),
            'visited_urls': set(),
            'items': [],
            'error_urls': set(),
            'stats': defaultdict(int)
        })
        
        # Contatori e intervallo di salvataggio
        self.item_count = 0
        self.domain_counts = defaultdict(int)
        self.save_interval = 50  # Salva ogni 50 item per dominio
        self.flush_interval = 10  # Intervallo per flush su disco
        
        # Registro
        self.logger = logging.getLogger('domain_pipeline')
        
        # URL totali e ultimi URL processati per dominio
        self.total_urls = 0
        self.last_urls = defaultdict(list)
        self.max_last_urls = 10  # Ultimi N URL per dominio
        
    @classmethod
    def from_crawler(cls, crawler):
        """
        Crea un'istanza della pipeline dal crawler.
        
        Args:
            crawler (Crawler): Crawler di Scrapy
            
        Returns:
            MultiDomainPipeline: Istanza della pipeline
        """
        output_dir = crawler.settings.get('OUTPUT_DIR', 'output_crawler')
        keep_html = crawler.settings.getbool('PIPELINE_KEEP_HTML', False)
        report_format = crawler.settings.get('PIPELINE_REPORT_FORMAT', 'all')
        
        return cls(output_dir, keep_html, report_format)
        
    def open_spider(self, spider):
        """
        Preparazione all'avvio dello spider.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        # Assicurati che la directory esista
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        # Prepara directory per ogni dominio conosciuto
        if hasattr(spider, 'domains'):
            self.logger.info(f"Pipeline inizializzata per {len(spider.domains)} domini")
            for domain in spider.domains:
                domain_dir = os.path.join(self.output_dir, domain)
                if not os.path.exists(domain_dir):
                    os.makedirs(domain_dir)
                    
                # Carica stato precedente per il dominio
                self._load_domain_state(domain)
        
        # Controlla se è uno spider con un singolo dominio
        elif hasattr(spider, 'allowed_domains') and spider.allowed_domains:
            domain = spider.allowed_domains[0]
            domain_dir = os.path.join(self.output_dir, domain)
            if not os.path.exists(domain_dir):
                os.makedirs(domain_dir)
                
            # Carica stato precedente
            self._load_domain_state(domain)
            
        # Assicurati che ci sia una directory per risultati generali
        general_dir = os.path.join(self.output_dir, 'general')
        if not os.path.exists(general_dir):
            os.makedirs(general_dir)
    
    def process_item(self, item, spider):
        """
        Processa un item, raggruppando per dominio.
        
        Args:
            item (Item): Item da processare
            spider (Spider): Spider in esecuzione
            
        Returns:
            Item: Item processato
        """
        if 'domain' not in item or 'url' not in item:
            raise DropItem("Item mancante di domain o url")
            
        domain = item['domain']
        url = item['url']
        
        # Crea directory per dominio se non esiste già
        domain_dir = os.path.join(self.output_dir, domain)
        if not os.path.exists(domain_dir):
            os.makedirs(domain_dir)
        
        # Aggiorna contatori
        self.item_count += 1
        self.domain_counts[domain] += 1
        self.total_urls += 1
        
        # Aggiorna ultimi URL
        self._update_last_urls(domain, url)
        
        # Elabora URL, struttura e statistiche
        self._process_url_structure(item)
        
        # Salva l'item nella lista per dominio
        if not self.keep_html and 'content' in item:
            # Se non conserviamo l'HTML, salviamo solo un frammento
            content = item.get('content', '')
            if content and len(content) > 500:
                item['content'] = f"{content[:500]}... [content truncated]"
            
        # Aggiungi alla lista di items per questo dominio
        domain_data = self.domain_data[domain]
        domain_data['items'].append(dict(item))
        
        # Aggiorna statistiche per dominio
        domain_data['stats']['pages'] += 1
        
        if 'status' in item:
            status = item['status']
            if 200 <= status < 300:
                domain_data['stats']['success'] += 1
            elif 400 <= status < 500:
                domain_data['stats']['client_errors'] += 1
            elif 500 <= status < 600:
                domain_data['stats']['server_errors'] += 1
        
        # Aggiorna statistiche globali
        if hasattr(spider, 'crawler') and hasattr(spider.crawler, 'stats'):
            spider.crawler.stats.inc_value(f'domain/{domain}/pages')
            spider.crawler.stats.inc_value(f'pipeline/items_processed')
        
        # Salvataggio periodico per dominio
        if self.domain_counts[domain] % self.save_interval == 0:
            self._save_domain_state(domain)
            
        # Flush periodico su disco
        if self.item_count % self.flush_interval == 0:
            self._flush_to_disk()
            
        return item
    
    def close_spider(self, spider):
        """
        Operazioni di chiusura dello spider.
        
        Args:
            spider (Spider): Spider in esecuzione
        """
        # Salva stati finali e genera report per ogni dominio
        for domain in self.domain_data:
            if self.domain_counts[domain] > 0:
                self._save_domain_state(domain)
                self._generate_domain_report(domain)
                
        # Report consolidato per tutti i domini
        self._generate_consolidated_report()
        
        # Log dei risultati
        self.logger.info(f"Crawling completato per {self.total_urls} URL totali")
        for domain, count in sorted(self.domain_counts.items(), key=lambda x: x[1], reverse=True):
            self.logger.info(f"Dominio {domain}: {count} URL processati")
    
    def _process_url_structure(self, item):
        """
        Elabora la struttura dell'URL e aggiorna le statistiche.
        
        Args:
            item (Item): Item da processare
        """
        domain = item['domain']
        url = item['url']
        domain_data = self.domain_data[domain]
        
        # Registra URL nell'albero
        if 'referer' in item:
            referer = item['referer']
            domain_data['url_tree'][referer].add(url)
            
        # Aggiorna set di pagine uniche
        domain_data['unique_pages'].add(url)
        domain_data['visited_urls'].add(url)
        
        # Aggiorna struttura template
        if 'template' in item:
            template = item['template']
            if template in domain_data['structures']:
                domain_data['structures'][template]['count'] += 1
                # Aggiorna solo se l'URL è più corto (normalmente indica una pagina di livello superiore)
                if len(url) < len(domain_data['structures'][template]['url']):
                    domain_data['structures'][template]['url'] = url
            else:
                domain_data['structures'][template] = {
                    'url': url,
                    'count': 1,
                    'template': template,
                    'domain': domain
                }
    
    def _update_last_urls(self, domain, url):
        """
        Aggiorna la lista degli ultimi URL processati per dominio.
        
        Args:
            domain (str): Dominio dell'URL
            url (str): URL da aggiungere
        """
        # Aggiungi l'URL in cima (più recente)
        self.last_urls[domain].insert(0, url)
        
        # Mantieni solo gli ultimi N
        if len(self.last_urls[domain]) > self.max_last_urls:
            self.last_urls[domain] = self.last_urls[domain][:self.max_last_urls]
    
    def _load_domain_state(self, domain):
        """
        Carica lo stato precedente per un dominio.
        
        Args:
            domain (str): Dominio da caricare
        """
        domain_dir = os.path.join(self.output_dir, domain)
        state_file = os.path.join(domain_dir, f'crawler_state_{domain}.pkl')
        
        if os.path.exists(state_file):
            try:
                with open(state_file, 'rb') as f:
                    state = pickle.load(f)
                    
                    # Carica solo se i dati sono validi
                    if isinstance(state, dict):
                        # URL Tree
                        if 'url_tree' in state and isinstance(state['url_tree'], dict):
                            self.domain_data[domain]['url_tree'] = defaultdict(set, state['url_tree'])
                            
                        # Structures
                        if 'structures' in state and isinstance(state['structures'], dict):
                            self.domain_data[domain]['structures'] = state['structures']
                            
                        # Sets
                        if 'unique_pages' in state and isinstance(state['unique_pages'], set):
                            self.domain_data[domain]['unique_pages'] = state['unique_pages']
                            
                        if 'visited_urls' in state and isinstance(state['visited_urls'], set):
                            self.domain_data[domain]['visited_urls'] = state['visited_urls']
                            
                        # Statistiche
                        if 'stats' in state and isinstance(state['stats'], dict):
                            self.domain_data[domain]['stats'] = defaultdict(int, state['stats'])
                        
                        # Aggiorna il contatore per questo dominio
                        self.domain_counts[domain] = len(self.domain_data[domain]['unique_pages'])
                        
                        self.logger.info(f"Stato caricato per dominio {domain} da {state_file}")
                    else:
                        self.logger.warning(f"Formato stato non valido in {state_file}")
                        
            except Exception as e:
                self.logger.error(f"Errore caricando lo stato per {domain}: {e}")
    
    def _save_domain_state(self, domain):
        """
        Salva lo stato per un singolo dominio.
        
        Args:
            domain (str): Dominio da salvare
        """
        domain_dir = os.path.join(self.output_dir, domain)
        state_file = os.path.join(domain_dir, f'crawler_state_{domain}.pkl')
        
        # Ottieni i dati per questo dominio
        domain_data = self.domain_data[domain]
        
        # Converti strutture dati per il pickle
        state = {
            'url_tree': dict(domain_data['url_tree']),
            'structures': domain_data['structures'],
            'unique_pages': domain_data['unique_pages'],
            'visited_urls': domain_data['visited_urls'],
            'stats': dict(domain_data['stats'])
        }
        
        # Salva in modo sicuro
        tmp_file = state_file + '.tmp'
        with open(tmp_file, 'wb') as f:
            pickle.dump(state, f)
        
        os.replace(tmp_file, state_file)
        self.logger.debug(f"Stato salvato per dominio {domain} in {state_file}")
        
        # Salva anche gli item in un JSON separato
        self._save_items_json(domain)
    
    def _save_items_json(self, domain):
        """
        Salva gli item in un file JSON per dominio.
        
        Args:
            domain (str): Dominio per cui salvare gli item
        """
        domain_dir = os.path.join(self.output_dir, domain)
        items_file = os.path.join(domain_dir, f'items_{domain}.json')
        
        # Limita il numero di item per evitare file troppo grandi
        items = self.domain_data[domain]['items']
        max_items = 1000  # Salva solo gli ultimi N item
        
        if len(items) > max_items:
            items = items[-max_items:]
        
        # Salva in modo sicuro
        tmp_file = items_file + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        
        os.replace(tmp_file, items_file)
    
    def _flush_to_disk(self):
        """
        Forza il flush dei dati su disco per evitare perdite in caso di crash.
        """
        # Questo metodo potrebbe essere ampliato in futuro per gestire
        # operazioni di flush più complesse
        pass
    
    def _generate_domain_report(self, domain):
        """
        Genera report per un singolo dominio.
        
        Args:
            domain (str): Dominio per cui generare il report
        """
        domain_dir = os.path.join(self.output_dir, domain)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        domain_data = self.domain_data[domain]
        
        # Ordina i template per frequenza
        sorted_templates = sorted(
            domain_data['structures'].items(), 
            key=lambda x: x[1]['count'], 
            reverse=True
        )
        
        # Genera report in formato Markdown
        if self.report_format in ['all', 'markdown']:
            report_file = os.path.join(domain_dir, f'report_{domain}_{timestamp}.md')
            
            with open(report_file, 'w', encoding='utf-8') as f:
                # Intestazione
                f.write(f"# Report Crawling: {domain}\n\n")
                f.write(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Statistiche generali
                f.write("## Statistiche Generali\n\n")
                f.write(f"- Dominio: {domain}\n")
                f.write(f"- Pagine uniche processate: {len(domain_data['unique_pages'])}\n")
                f.write(f"- Template URL trovati: {len(domain_data['structures'])}\n")
                
                # Statistiche di errore
                f.write(f"- Successi (2xx): {domain_data['stats'].get('success', 0)}\n")
                f.write(f"- Errori client (4xx): {domain_data['stats'].get('client_errors', 0)}\n")
                f.write(f"- Errori server (5xx): {domain_data['stats'].get('server_errors', 0)}\n\n")
                
                # Ultimi URL visitati
                if domain in self.last_urls and self.last_urls[domain]:
                    f.write("## Ultimi URL visitati\n\n")
                    for i, url in enumerate(self.last_urls[domain], 1):
                        f.write(f"{i}. [{url}]({url})\n")
                    f.write("\n")
                
                # Template più comuni
                f.write("## Template URL Più Comuni\n\n")
                f.write("| # | Template | Conteggio | URL Esempio |\n")
                f.write("|---|----------|-----------|-------------|\n")
                
                for i, (template, data) in enumerate(sorted_templates[:20], 1):
                    f.write(f"| {i} | `{template}` | {data['count']} | [{data['url']}]({data['url']}) |\n")
                    
            self.logger.info(f"Report Markdown generato per dominio {domain} in {report_file}")
                
        # Genera report in formato JSON
        if self.report_format in ['all', 'json']:
            json_file = os.path.join(domain_dir, f'templates_{domain}_{timestamp}.json')
            
            with open(json_file, 'w', encoding='utf-8') as jf:
                json.dump({
                    'domain': domain,
                    'timestamp': datetime.now().isoformat(),
                    'templates': {t: v for t, v in sorted_templates},
                    'stats': {
                        'unique_pages': len(domain_data['unique_pages']),
                        'templates_count': len(domain_data['structures']),
                        'success': domain_data['stats'].get('success', 0),
                        'client_errors': domain_data['stats'].get('client_errors', 0),
                        'server_errors': domain_data['stats'].get('server_errors', 0)
                    },
                    'last_urls': self.last_urls.get(domain, [])
                }, jf, indent=2, ensure_ascii=False)
                
            self.logger.info(f"Report JSON generato per dominio {domain} in {json_file}")
            
        # Genera report in formato CSV
        if self.report_format in ['all', 'csv']:
            csv_file = os.path.join(domain_dir, f'templates_{domain}_{timestamp}.csv')
            
            # Preparazione dati
            template_data = []
            for template, data in sorted_templates:
                template_data.append({
                    'template': template,
                    'count': data['count'],
                    'example_url': data['url'],
                    'domain': domain
                })
                
            if template_data:
                df = pd.DataFrame(template_data)
                df.to_csv(csv_file, index=False, encoding='utf-8')
                self.logger.info(f"Report CSV generato per dominio {domain} in {csv_file}")
    
    def _generate_consolidated_report(self):
        """
        Genera un report consolidato per tutti i domini.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Report in formato Markdown
        if self.report_format in ['all', 'markdown']:
            report_file = os.path.join(self.output_dir, f'consolidated_report_{timestamp}.md')
            
            with open(report_file, 'w', encoding='utf-8') as f:
                # Intestazione
                f.write(f"# Report Consolidato Multi-Dominio\n\n")
                f.write(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Statistiche per dominio
                f.write("## Statistiche per Dominio\n\n")
                f.write("| Dominio | Pagine | Template | Successi | Errori Client | Errori Server |\n")
                f.write("|---------|--------|----------|----------|---------------|---------------|\n")
                
                total_pages = 0
                total_templates = 0
                total_success = 0
                total_client_errors = 0
                total_server_errors = 0
                
                # Ordina domini per numero di pagine
                sorted_domains = sorted(
                    self.domain_data.items(),
                    key=lambda x: len(x[1]['unique_pages']),
                    reverse=True
                )
                
                for domain, domain_data in sorted_domains:
                    pages = len(domain_data['unique_pages'])
                    templates = len(domain_data['structures'])
                    success = domain_data['stats'].get('success', 0)
                    client_errors = domain_data['stats'].get('client_errors', 0)
                    server_errors = domain_data['stats'].get('server_errors', 0)
                    
                    total_pages += pages
                    total_templates += templates
                    total_success += success
                    total_client_errors += client_errors
                    total_server_errors += server_errors
                    
                    if pages > 0:  # Solo domini con dati
                        f.write(f"| {domain} | {pages} | {templates} | {success} | {client_errors} | {server_errors} |\n")
                
                # Totale
                f.write(f"\n**Totale:** {total_pages} pagine, {total_templates} template, "
                      f"{total_success} successi, {total_client_errors} errori client, "
                      f"{total_server_errors} errori server\n\n")
                
                # Template più comuni per ogni dominio
                f.write("## Template più comuni per dominio\n\n")
                
                for domain, domain_data in sorted_domains:
                    if len(domain_data['structures']) == 0:
                        continue
                        
                    f.write(f"### {domain}\n\n")
                    
                    sorted_templates = sorted(
                        domain_data['structures'].items(), 
                        key=lambda x: x[1]['count'], 
                        reverse=True
                    )
                    
                    f.write("| # | Template | Conteggio | URL Esempio |\n")
                    f.write("|---|----------|-----------|-------------|\n")
                    
                    for i, (template, data) in enumerate(sorted_templates[:10], 1):
                        f.write(f"| {i} | `{template}` | {data['count']} | [{data['url']}]({data['url']}) |\n")
                    
                    f.write("\n")
                
                # Ultimi URL visitati per ogni dominio
                f.write("## Ultimi URL visitati per dominio\n\n")
                
                for domain in sorted(self.last_urls.keys(), key=lambda d: self.domain_counts.get(d, 0), reverse=True):
                    if not self.last_urls[domain]:
                        continue
                        
                    f.write(f"### {domain}\n\n")
                    for i, url in enumerate(self.last_urls[domain], 1):
                        f.write(f"{i}. [{url}]({url})\n")
                    
                    f.write("\n")
            
            self.logger.info(f"Report consolidato generato in {report_file}")
            
        # Report in formato JSON
        if self.report_format in ['all', 'json']:
            json_file = os.path.join(self.output_dir, f'consolidated_report_{timestamp}.json')
            
            # Prepara il report in formato JSON
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'domains': {},
                'totals': {
                    'domains': len(self.domain_data),
                    'pages': 0,
                    'templates': 0,
                    'success': 0,
                    'client_errors': 0,
                    'server_errors': 0
                },
                'last_urls': {}
            }
            
            for domain, domain_data in self.domain_data.items():
                if len(domain_data['unique_pages']) == 0:
                    continue
                    
                pages = len(domain_data['unique_pages'])
                templates = len(domain_data['structures'])
                success = domain_data['stats'].get('success', 0)
                client_errors = domain_data['stats'].get('client_errors', 0)
                server_errors = domain_data['stats'].get('server_errors', 0)
                
                report_data['totals']['pages'] += pages
                report_data['totals']['templates'] += templates
                report_data['totals']['success'] += success
                report_data['totals']['client_errors'] += client_errors
                report_data['totals']['server_errors'] += server_errors
                
                top_templates = sorted(
                    domain_data['structures'].items(),
                    key=lambda x: x[1]['count'],
                    reverse=True
                )[:10]
                
                report_data['domains'][domain] = {
                    'pages': pages,
                    'templates': templates,
                    'success': success,
                    'client_errors': client_errors,
                    'server_errors': server_errors,
                    'top_templates': {t: v for t, v in top_templates}
                }
                
                if domain in self.last_urls:
                    report_data['last_urls'][domain] = self.last_urls[domain]
            
            with open(json_file, 'w', encoding='utf-8') as jf:
                json.dump(report_data, jf, indent=2, ensure_ascii=False)
                
            self.logger.info(f"Report JSON consolidato generato in {json_file}")
            
        # Genera un CSV consolidato con tutti i template
        if self.report_format in ['all', 'csv']:
            csv_file = os.path.join(self.output_dir, f'all_templates_{timestamp}.csv')
            
            # Prepara i dati
            all_templates = []
            
            for domain, domain_data in self.domain_data.items():
                for template, data in domain_data['structures'].items():
                    all_templates.append({
                        'domain': domain,
                        'template': template,
                        'count': data['count'],
                        'example_url': data['url']
                    })
            
            if all_templates:
                df = pd.DataFrame(all_templates)
                df.to_csv(csv_file, index=False, encoding='utf-8')
                self.logger.info(f"Report CSV consolidato generato in {csv_file}")