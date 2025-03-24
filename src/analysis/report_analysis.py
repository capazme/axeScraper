#!/usr/bin/env python3
"""
Enhanced Accessibility Analysis Module

Processes data from accessibility tests, generates visualizations,
and creates comprehensive reports with actionable recommendations.
"""

import os
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from datetime import datetime
import pickle
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json

# Import configuration management
from utils.config_manager import ConfigurationManager
from utils.logging_config import get_logger
from utils.output_manager import OutputManager

# Initialize configuration manager
config_manager = ConfigurationManager(project_name="axeScraper")

class AccessibilityAnalyzer:
    """
    Optimized: Accessibility analysis tool that processes data from axe DevTools
    and Crawler, generating accurate metrics and reports with clear visualizations.
    """
    
    def __init__(self, log_level=None, max_workers=None, output_manager=None):
        """Initialize the analyzer with logging configuration and parallelism options."""
        # Use standardized logging from configuration manager
        self.logger = get_logger("report_analysis", 
                           config_manager.get_logging_config()["components"]["report_analysis"])
        
        # Store output manager if provided
        self.output_manager = output_manager
        
        # Get domain info from output manager if available
        if output_manager:
            self.domain_slug = output_manager.domain_slug
        else:
            self.domain_slug = "unknown_domain"
        
        # Use configuration or defaults
        self.max_workers = max_workers or config_manager.get_int("REPORT_ANALYSIS_MAX_WORKERS", 4)

        
        # Define impact severity mapping for consistent scoring with extended weights
        self.impact_weights = {
            'critical': 4,
            'serious': 3, 
            'moderate': 2, 
            'minor': 1,
            'unknown': 0
        }
            
        # WCAG categories mapping
        self.wcag_categories = {
            'color-contrast': {'category': 'Perceivable', 'criterion': '1.4.3', 'name': 'Contrast (Minimum)'},
            'aria-roles': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
            'keyboard': {'category': 'Operable', 'criterion': '2.1.1', 'name': 'Keyboard'},
            'document-title': {'category': 'Perceivable', 'criterion': '2.4.2', 'name': 'Page Titled'},
            'image-alt': {'category': 'Perceivable', 'criterion': '1.1.1', 'name': 'Non-text Content'},
            'label': {'category': 'Perceivable', 'criterion': '1.3.1', 'name': 'Info and Relationships'},
            'link-name': {'category': 'Perceivable', 'criterion': '2.4.4', 'name': 'Link Purpose (In Context)'},
            'list': {'category': 'Perceivable', 'criterion': '1.3.1', 'name': 'Info and Relationships'},
            'heading-order': {'category': 'Perceivable', 'criterion': '2.4.6', 'name': 'Headings and Labels'},
            'frame-title': {'category': 'Perceivable', 'criterion': '2.4.1', 'name': 'Bypass Blocks'},
            'html-has-lang': {'category': 'Perceivable', 'criterion': '3.1.1', 'name': 'Language of Page'},
            'html-lang-valid': {'category': 'Perceivable', 'criterion': '3.1.1', 'name': 'Language of Page'},
            'aria-allowed-attr': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
            'aria-required-attr': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
            'aria-required-children': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
            'aria-required-parent': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
            'form-field-multiple-labels': {'category': 'Perceivable', 'criterion': '3.3.2', 'name': 'Labels or Instructions'},
            'button-name': {'category': 'Operable', 'criterion': '2.4.4', 'name': 'Link Purpose (In Context)'},
            'duplicate-id': {'category': 'Robust', 'criterion': '4.1.1', 'name': 'Parsing'},
            'empty-heading': {'category': 'Perceivable', 'criterion': '2.4.6', 'name': 'Headings and Labels'},
        }
        
        # Solutions for common issues
        self.solution_mapping = {
            'color-contrast': {
                'description': 'Increase contrast ratio to at least 4.5:1 for normal text or 3:1 for large text',
                'technical': 'Use CSS to adjust text and background colors; verify with a contrast checker tool',
                'impact': 'Affects users with low vision, color blindness, or reading on mobile in bright light'
            },
            'aria-roles': {
                'description': 'Use valid ARIA role values according to specifications',
                'technical': 'Check ARIA roles against WAI-ARIA specification; remove invalid roles',
                'impact': 'Affects screen reader users who rely on correct role semantics'
            },
            'image-alt': {
                'description': 'Add descriptive alt text to images',
                'technical': 'Use the alt attribute on all <img> elements with meaningful descriptions',
                'impact': 'Affects screen reader users who cannot see images'
            },
            'document-title': {
                'description': 'Add an appropriate title tag in the document head',
                'technical': 'Ensure <title> element exists in <head> with a descriptive page title',
                'impact': 'Affects all users for page identification, especially screen reader users'
            },
            'label': {
                'description': 'Associate form controls with proper labels',
                'technical': 'Use <label> with for attribute, or aria-labelledby, or aria-label',
                'impact': 'Affects screen reader users and voice recognition software users'
            },
            'link-name': {
                'description': 'Ensure links have accessible text content',
                'technical': 'Add text within the <a> element or use aria-label/aria-labelledby',
                'impact': 'Affects screen reader users who need to understand link purpose'
            },
            'frame-title': {
                'description': 'Add title attribute to iframe elements',
                'technical': 'Add descriptive title attribute to all <iframe> elements',
                'impact': 'Affects screen reader users who need context for frame content'
            },
            'keyboard': {
                'description': 'Make all interactive elements keyboard accessible',
                'technical': 'Ensure all interactions can be accessed with Tab, Enter, Space, Escape keys',
                'impact': 'Affects keyboard-only users, including many with motor disabilities'
            },
            'html-has-lang': {
                'description': 'Add a lang attribute to the HTML element',
                'technical': 'Add lang="xx" to the <html> element with the appropriate language code',
                'impact': 'Affects screen readers that need language information for proper pronunciation'
            },
            'button-name': {
                'description': 'Provide accessible names for all buttons',
                'technical': 'Add text content to <button> elements or use aria-label/aria-labelledby',
                'impact': 'Affects screen reader users who need to understand button purpose'
            },
        }
        
        # Page type pattern detection
        self.page_type_patterns = {
            'homepage': [r'/$', r'/index\.html$', r'/home$'],
            'search': [r'/search', r'/cerca', r'/find'],
            'product': [r'/product', r'/prodotto', r'/item'],
            'category': [r'/category', r'/categoria', r'/department'],
            'cart': [r'/cart', r'/carrello', r'/basket'],
            'checkout': [r'/checkout', r'/acquista', r'/payment'],
            'login': [r'/login', r'/accedi', r'/signin'],
            'register': [r'/register', r'/registrazione', r'/signup'],
            'account': [r'/account', r'/profilo', r'/user'],
            'contact': [r'/contact', r'/contatti', r'/support'],
            'article': [r'/article', r'/articolo', r'/post', r'/blog'],
            'about': [r'/about', r'/chi-siamo', r'/azienda'],
        }
        
        # Cache for improving performance
        self._url_type_cache = {}
        self._normalized_url_cache = {}
        self._wcag_mapping_cache = {}
      
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL (lowercase, no fragments) using a cache for better performance.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        if not url or not isinstance(url, str):
            return ""
        if url in self._normalized_url_cache:
            return self._normalized_url_cache[url]
        try:
            parsed = urlparse(url)
            normalized_url = urlunparse((
                parsed.scheme.lower() if parsed.scheme else 'http',
                parsed.netloc.lower(),
                parsed.path,
                '',
                parsed.query,
                ''
            ))
            self._normalized_url_cache[url] = normalized_url
            return normalized_url
        except Exception:
            self._normalized_url_cache[url] = url
            return url
            
    def get_page_type(self, url: str) -> str:
        """
        Identify page type based on predefined patterns in the URL.
        
        Args:
            url: URL to identify
            
        Returns:
            Identified page type
        """
        if url in self._url_type_cache:
            return self._url_type_cache[url]
        for page_type, patterns in self.page_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    self._url_type_cache[url] = page_type
                    return page_type
        self._url_type_cache[url] = 'other'
        return 'other'
    
    def load_data(self, input_excel: Optional[str] = None, crawler_state: Optional[str] = None) -> pd.DataFrame:
        """Load data from an Excel file and optionally integrate crawler data."""
        # Use output manager to get default paths if not provided
        if self.output_manager:
            if input_excel is None:
                input_excel = str(self.output_manager.get_path(
                    "axe", f"accessibility_report_{self.output_manager.domain_slug}.xlsx"))
                
            if crawler_state is None:
                crawler_state = str(self.output_manager.get_path(
                    "crawler", f"crawler_state_{self.output_manager.domain_slug}.pkl"))

        self.logger.info(f"Loading data from {input_excel}")
        input_path = Path(input_excel)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file {input_excel} not found")
        df = pd.read_excel(input_excel)
        self.logger.info(f"Loaded Excel with {len(df)} rows")
        required_columns = ['violation_id', 'impact', 'page_url']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
        df = self._clean_data(df)
        if crawler_state:
            df = self._integrate_crawler_data(df, crawler_state)
        return df
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and normalize data.
        
        Args:
            df: DataFrame to clean
            
        Returns:
            Cleaned DataFrame
        """
        clean_df = df.copy()
        original_count = len(clean_df)
        clean_df = clean_df.dropna(subset=['violation_id', 'impact', 'page_url'])
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            normalized_urls = list(executor.map(self.normalize_url, clean_df['page_url']))
        clean_df['normalized_url'] = normalized_urls
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            page_types = list(executor.map(self.get_page_type, clean_df['normalized_url']))
        clean_df['page_type'] = page_types
        clean_df['impact'] = clean_df['impact'].str.lower().str.strip()
        valid_impacts = list(self.impact_weights.keys())
        clean_df.loc[~clean_df['impact'].isin(valid_impacts), 'impact'] = 'unknown'
        clean_df = clean_df.drop_duplicates(subset=['normalized_url', 'violation_id'])
        clean_df['analysis_date'] = datetime.now().strftime("%Y-%m-%d")
        clean_df['wcag_category'] = clean_df['violation_id'].apply(self._get_wcag_category)
        clean_df['wcag_criterion'] = clean_df['violation_id'].apply(self._get_wcag_criterion)
        clean_df['wcag_name'] = clean_df['violation_id'].apply(self._get_wcag_name)
        clean_df['severity_score'] = clean_df['impact'].map(self.impact_weights)
        self.logger.info(f"Original rows: {original_count}, remaining: {len(clean_df)}")
        return clean_df
        
    def _get_wcag_category(self, violation_id: str) -> str:
        """Get WCAG category for a violation ID."""
        key = next((k for k in self.wcag_categories if k in violation_id.lower()), None)
        return self.wcag_categories[key]['category'] if key else "Other"
        
    def _get_wcag_criterion(self, violation_id: str) -> str:
        """Get WCAG criterion for a violation ID."""
        key = next((k for k in self.wcag_categories if k in violation_id.lower()), None)
        return self.wcag_categories[key]['criterion'] if key else "N/A"
        
    def _get_wcag_name(self, violation_id: str) -> str:
        """Get WCAG name for a violation ID."""
        key = next((k for k in self.wcag_categories if k in violation_id.lower()), None)
        return self.wcag_categories[key]['name'] if key else "Other"
    
    # In src/analysis/report_analysis.py
    def _integrate_crawler_data(self, df: pd.DataFrame, crawler_state: str) -> pd.DataFrame:
        """
        Integrate crawler data, e.g., templates and page depth.
        Handles different state file formats for better compatibility.
        
        Args:
            df: DataFrame to integrate with
            crawler_state: Path to crawler state file
            
        Returns:
            Integrated DataFrame
        """
        self.logger.info(f"Integrating crawler data from {crawler_state}")
        if not os.path.exists(crawler_state):
            self.logger.warning(f"Crawler state file {crawler_state} not found")
            return df
        
        try:
            with open(crawler_state, 'rb') as f:
                state = pickle.load(f)
            
            # Handle different state file formats
            url_tree = {}
            structures = {}
            
            # New multi-domain format
            if isinstance(state, dict) and "domain_data" in state:
                self.logger.info("Found multi-domain crawler state format")
                # Extract data for this domain
                domain_slug = self.domain_slug
                
                for domain_key, domain_data in state["domain_data"].items():
                    domain_name = domain_key.rstrip(':')  # Handle domains that end with colon
                    if domain_slug in domain_name or domain_slug.replace('_', '') in domain_name:
                        # Found matching domain
                        if "url_tree" in domain_data:
                            url_tree = domain_data["url_tree"]
                        if "structures" in domain_data:
                            structures = domain_data["structures"]
                        self.logger.info(f"Found matching domain data for {domain_name}")
            
            # Old format or direct domain data
            elif isinstance(state, dict):
                # Check if state contains direct domain data
                if "url_tree" in state:
                    url_tree = state.get("url_tree", {})
                if "structures" in state:
                    structures = state.get("structures", {})
                self.logger.info(f"Using direct domain data from state file")
            
            # Map templates to URLs
            url_to_template = {}
            for template, data in structures.items():
                # Handle different structure formats
                if isinstance(data, dict):
                    if "url" in data:
                        url_to_template[self.normalize_url(data["url"])] = template
                    if "urls" in data and isinstance(data["urls"], list):
                        for url in data["urls"]:
                            url_to_template[self.normalize_url(url)] = template
                    elif "url_list" in data and isinstance(data["url_list"], list):
                        for url in data["url_list"]:
                            url_to_template[self.normalize_url(url)] = template
            
            self.logger.info(f"Mapped {len(url_to_template)} URLs to templates")
            
            # Add template information to DataFrame
            df['template'] = df['normalized_url'].map(
                lambda url: next((t for u, t in url_to_template.items() if u == url), "Unknown")
            )
            
            # Continue with depth calculation - existing code here...
            
            self.logger.info(f"Successfully integrated crawler data into {len(df)} rows")
            return df
        
        except Exception as e:
            self.logger.error(f"Error integrating crawler data: {e}", exc_info=True)
            return df
    def calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """
        Calculate basic accessibility metrics.
        
        Args:
            df: DataFrame with accessibility data
            
        Returns:
            Dictionary of metrics
        """
        if df.empty:
            self.logger.warning("Empty DataFrame, cannot calculate metrics")
            return self._empty_metrics()
        
        metrics = {}
        metrics['Total Violations'] = len(df)
        metrics['Unique Pages'] = df['normalized_url'].nunique()
        metrics['Unique Violation Types'] = df['violation_id'].nunique()
        impact_counts = df['impact'].value_counts().to_dict()
        for impact, count in sorted(impact_counts.items(), key=lambda x: self.impact_weights.get(x[0], 0), reverse=True):
            metrics[f'{impact.capitalize()} Violations'] = count
        unique_pages = metrics['Unique Pages']
        avg_per_page = metrics['Total Violations'] / unique_pages if unique_pages > 0 else 0
        metrics['Average Violations per Page'] = round(avg_per_page, 2)
        total_severity = df['severity_score'].sum()
        metrics['Weighted Severity Score'] = round(total_severity / unique_pages, 2) if unique_pages > 0 else 0
        pages_with_critical = df[df['impact'] == 'critical']['normalized_url'].nunique()
        critical_page_pct = (pages_with_critical / unique_pages * 100) if unique_pages > 0 else 0
        metrics['Pages with Critical Issues (%)'] = round(critical_page_pct, 2)
        page_type_metrics = {}
        for page_type, group in df.groupby('page_type'):
            type_pages = group['normalized_url'].nunique()
            page_type_metrics[page_type] = {
                'pages': type_pages,
                'violations': len(group),
                'avg_per_page': round(len(group) / type_pages, 2) if type_pages > 0 else 0,
                'critical': group[group['impact'] == 'critical']['normalized_url'].nunique(),
                'critical_pct': round((group[group['impact'] == 'critical']['normalized_url'].nunique() / type_pages) * 100, 2) if type_pages > 0 else 0
            }
        metrics['Page Type Analysis'] = page_type_metrics
        wcag_criteria = df.groupby(['wcag_category', 'wcag_criterion', 'wcag_name']).size().reset_index(name='count')
        wcag_criteria = wcag_criteria.sort_values('count', ascending=False)
        top_wcag = {}
        for _, row in wcag_criteria.head(5).iterrows():
            criterion_key = f"{row['wcag_category']} ({row['wcag_criterion']})"
            top_wcag[criterion_key] = {
                'name': row['wcag_name'],
                'count': row['count'],
                'percentage': round((row['count'] / metrics['Total Violations']) * 100, 2)
            }
        metrics['Top WCAG Issues'] = top_wcag
        critical_factor = (pages_with_critical / unique_pages) if unique_pages > 0 else 0
        weighted_violation_score = (
            (impact_counts.get('critical', 0) * 4) + 
            (impact_counts.get('serious', 0) * 3) + 
            (impact_counts.get('moderate', 0) * 2) + 
            (impact_counts.get('minor', 0) * 1)
        ) / max(unique_pages, 1)
        critical_penalty = critical_factor * 20
        conformance_score = max(0, 100 - min(100, (weighted_violation_score * 2 + critical_penalty)))
        metrics['WCAG Conformance Score'] = round(conformance_score, 1)
        if conformance_score >= 95:
            conformance_level = 'AA (Nearly conformant)'
        elif conformance_score >= 85:
            conformance_level = 'A (Partially conformant)'
        elif conformance_score >= 70:
            conformance_level = 'Non-conformant (Minor issues)'
        elif conformance_score >= 40:
            conformance_level = 'Non-conformant (Moderate issues)'
        else:
            conformance_level = 'Non-conformant (Major issues)'
        metrics['WCAG Conformance Level'] = conformance_level
        self.logger.info(f"Calculated advanced metrics for {metrics['Total Violations']} violations across {metrics['Unique Pages']} pages")
        return metrics
    
    def _empty_metrics(self) -> Dict:
        """Return default empty metrics when no data is available."""
        return {
            'Total Violations': 0,
            'Unique Pages': 0,
            'Unique Violation Types': 0,
            'Average Violations per Page': 0,
            'Critical Violations': 0,
            'Serious Violations': 0,
            'Moderate Violations': 0,
            'Minor Violations': 0,
            'Weighted Severity Score': 0,
            'Pages with Critical Issues (%)': 0,
            'Page Type Analysis': {},
            'WCAG Conformance Level': 'Unknown',
            'WCAG Conformance Score': 0,
            'Top WCAG Issues': {}
        }
    
    def create_aggregations(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        Create informative aggregations from the cleaned DataFrame.
        
        Args:
            df: Cleaned DataFrame
            
        Returns:
            Dictionary of aggregation DataFrames
        """
        if df.empty:
            self.logger.warning("Empty DataFrame, cannot create aggregations")
            return {'By Impact': pd.DataFrame(), 'By Page': pd.DataFrame(), 
                    'By Violation': pd.DataFrame(), 'Common Issues': pd.DataFrame()}
        
        aggregations = {}
        
        # Aggregation by impact
        try:
            agg_impact = (df.groupby('impact')
                         .agg(Total_Violations=('violation_id', 'count'),
                              Unique_Pages=('normalized_url', 'nunique'),
                              Avg_Per_Page=('violation_id', lambda x: len(x) / df['normalized_url'].nunique() if df['normalized_url'].nunique() > 0 else 0))
                         .reset_index())
            total = agg_impact['Total_Violations'].sum()
            agg_impact['Percentage'] = (agg_impact['Total_Violations'] / total * 100).round(2) if total > 0 else 0
            agg_impact['Priority_Index'] = agg_impact['impact'].map(self.impact_weights) * agg_impact['Unique_Pages']
            impact_order = {impact: i for i, impact in enumerate(self.impact_weights.keys())}
            agg_impact['impact_order'] = agg_impact['impact'].map(lambda x: impact_order.get(x, 999))
            agg_impact = agg_impact.sort_values('impact_order').drop('impact_order', axis=1)
            numeric_cols = ['Avg_Per_Page', 'Percentage', 'Priority_Index']
            agg_impact[numeric_cols] = agg_impact[numeric_cols].round(2)
            aggregations['By Impact'] = agg_impact
        except Exception as e:
            self.logger.error(f"Error creating impact aggregation: {e}")
            aggregations['By Impact'] = pd.DataFrame()
        
        # Aggregation by page
        try:
            agg_page = df.groupby('normalized_url', as_index=False).agg(
                Total_Violations=pd.NamedAgg(column='violation_id', aggfunc='count'),
                Original_URL=pd.NamedAgg(column='page_url', aggfunc='first'),
                Page_Type=pd.NamedAgg(column='page_type', aggfunc='first'),
                Critical_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'critical')),
                Serious_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'serious')),
                Moderate_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'moderate')),
                Minor_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'minor')),
                Unique_Violations=pd.NamedAgg(column='violation_id', aggfunc='nunique'),
                WCAG_Categories=pd.NamedAgg(column='wcag_category', aggfunc=lambda x: len(set(x)))
            )
            if 'page_depth' in df.columns:
                depth_data = df.groupby('normalized_url')['page_depth'].first()
                agg_page['Page_Depth'] = agg_page['normalized_url'].map(depth_data)
            if 'template' in df.columns:
                template_data = df.groupby('normalized_url')['template'].first()
                agg_page['Template'] = agg_page['normalized_url'].map(template_data)
            agg_page['Priority_Score'] = (
                agg_page['Critical_Violations'] * 4 + 
                agg_page['Serious_Violations'] * 3 + 
                agg_page['Moderate_Violations'] * 2 +
                agg_page['Minor_Violations'] * 1
            )
            max_score = agg_page['Priority_Score'].max()
            if max_score > 0:
                agg_page['Accessibility_Index'] = 100 - (agg_page['Priority_Score'] / max_score * 100)
            else:
                agg_page['Accessibility_Index'] = 100
            top_pages = agg_page.sort_values('Priority_Score', ascending=False).head(15)
            top_pages['Display_URL'] = top_pages['Original_URL'].apply(lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else str(x))
            top_pages['Accessibility_Index'] = top_pages['Accessibility_Index'].round(2)
            self.logger.info(f"Page aggregation created with {len(top_pages)} rows")
            if len(top_pages) > 0:
                aggregations['By Page'] = top_pages
            else:
                self.logger.warning("No pages found in aggregation, adding placeholder")
                placeholder = pd.DataFrame({
                    'normalized_url': ['No issues found'],
                    'Total_Violations': [0],
                    'Original_URL': ['No URL'],
                    'Page_Type': ['N/A'],
                    'Critical_Violations': [0],
                    'Serious_Violations': [0],
                    'Moderate_Violations': [0],
                    'Minor_Violations': [0],
                    'Unique_Violations': [0],
                    'WCAG_Categories': [0],
                    'Priority_Score': [0],
                    'Accessibility_Index': [100],
                    'Display_URL': ['No URL']
                })
                aggregations['By Page'] = placeholder
        except Exception as e:
            self.logger.error(f"Error creating page aggregation: {e}")
            aggregations['By Page'] = pd.DataFrame()
        
        # Aggregation by violation type
        try:
            agg_violation = (df.groupby('violation_id')
                            .agg(Total_Violations=('violation_id', 'count'),
                                 Affected_Pages=('normalized_url', 'nunique'),
                                 WCAG_Category=('wcag_category', 'first'),
                                 WCAG_Criterion=('wcag_criterion', 'first'),
                                 WCAG_Name=('wcag_name', 'first'))
                            .reset_index())
            impact_mode = df.groupby('violation_id')['impact'].agg(lambda x: x.mode()[0] if not x.mode().empty else "unknown")
            agg_violation['Most_Common_Impact'] = agg_violation['violation_id'].map(impact_mode)
            for impact in ['critical', 'serious', 'moderate', 'minor']:
                impact_counts = df[df['impact'] == impact].groupby('violation_id').size()
                agg_violation[f'{impact.capitalize()}_Count'] = agg_violation['violation_id'].map(impact_counts).fillna(0).astype(int)
            total = agg_violation['Total_Violations'].sum()
            agg_violation['Percentage'] = (agg_violation['Total_Violations'] / total * 100).round(2) if total > 0 else 0
            agg_violation['Priority_Score'] = (
                agg_violation['Critical_Count'] * 4 + 
                agg_violation['Serious_Count'] * 3 + 
                agg_violation['Moderate_Count'] * 2 +
                agg_violation['Minor_Count'] * 1
            )
            def get_solution_info(violation_id):
                for key in self.solution_mapping:
                    if key in violation_id.lower():
                        return self.solution_mapping[key]
                return {
                    'description': 'Check WCAG guidelines for this violation',
                    'technical': 'Refer to WCAG documentation',
                    'impact': 'May affect users with disabilities'
                }
            solutions = [get_solution_info(vid) for vid in agg_violation['violation_id']]
            agg_violation['Solution_Description'] = [s['description'] for s in solutions]
            agg_violation['Technical_Solution'] = [s['technical'] for s in solutions]
            agg_violation['User_Impact'] = [s['impact'] for s in solutions]
            agg_violation = agg_violation.sort_values('Priority_Score', ascending=False)
            aggregations['By Violation'] = agg_violation
        except Exception as e:
            self.logger.error(f"Error creating violation aggregation: {e}")
            aggregations['By Violation'] = pd.DataFrame()
        
        # Common issues by impact level and page type
        try:
            impact_page_type_violations = []
            for impact in df['impact'].unique():
                for page_type in df['page_type'].unique():
                    subset = df[(df['impact'] == impact) & (df['page_type'] == page_type)]
                    if subset.empty:
                        continue
                    violation_counts = subset['violation_id'].value_counts()
                    if violation_counts.empty:
                        continue
                    most_common = violation_counts.index[0]
                    count = violation_counts.iloc[0]
                    total_in_category = len(subset)
                    percentage = round((count / total_in_category) * 100, 2)
                    affected_pages = subset[subset['violation_id'] == most_common]['normalized_url'].nunique()
                    wcag_info = subset[subset['violation_id'] == most_common].iloc[0]
                    solution = "Check WCAG guidelines"
                    for key, value in self.solution_mapping.items():
                        if key in most_common.lower():
                            solution = value['description']
                            break
                    impact_page_type_violations.append({
                        'Impact': impact,
                        'Page_Type': page_type,
                        'Most_Common_Violation': most_common,
                        'Count': count,
                        'Percentage': percentage, 
                        'Affected_Pages': affected_pages,
                        'WCAG_Category': wcag_info['wcag_category'],
                        'WCAG_Criterion': wcag_info['wcag_criterion'],
                        'Suggested_Solution': solution
                    })
            if impact_page_type_violations:
                common_df = pd.DataFrame(impact_page_type_violations)
                impact_order = {impact: i for i, impact in enumerate(self.impact_weights.keys())}
                common_df['impact_order'] = common_df['Impact'].map(lambda x: impact_order.get(x, 999))
                common_df = common_df.sort_values(['impact_order', 'Page_Type']).drop('impact_order', axis=1)
                aggregations['Common Issues'] = common_df
            else:
                aggregations['Common Issues'] = pd.DataFrame()
        except Exception as e:
            self.logger.error(f"Error creating common issues aggregation: {e}")
            aggregations['Common Issues'] = pd.DataFrame()
            
        # Aggregation by page type
        try:
            page_type_agg = df.groupby('page_type').agg(
                Total_Pages=pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                Total_Violations=pd.NamedAgg(column='violation_id', aggfunc='count'),
                Critical_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'critical')),
                Serious_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'serious')),
                Most_Common_Violation=pd.NamedAgg(column='violation_id', aggfunc=lambda x: x.value_counts().index[0] if len(x) > 0 else "None")
            ).reset_index()
            page_type_agg['Avg_Per_Page'] = (page_type_agg['Total_Violations'] / page_type_agg['Total_Pages']).round(2)
            page_type_agg['Priority_Score'] = (
                page_type_agg['Critical_Violations'] * 4 + 
                page_type_agg['Serious_Violations'] * 3
            ) / page_type_agg['Total_Pages'].clip(lower=1)
            def get_top_wcag(page_type):
                subset = df[df['page_type'] == page_type]
                if subset.empty:
                    return "N/A"
                top_wcag = subset.groupby('wcag_category').size().sort_values(ascending=False)
                if top_wcag.empty:
                    return "N/A"
                return top_wcag.index[0]
            page_type_agg['Top_WCAG_Category'] = page_type_agg['page_type'].apply(get_top_wcag)
            page_type_agg = page_type_agg.sort_values('Priority_Score', ascending=False)
            aggregations['By Page Type'] = page_type_agg
        except Exception as e:
            self.logger.error(f"Error creating page type aggregation: {e}")
            aggregations['By Page Type'] = pd.DataFrame()
        
        # Add aggregation by page section (public/authenticated)
        if 'page_section' in df.columns:
            try:
                agg_section = df.groupby('page_section').agg(
                    Total_Violations=pd.NamedAgg(column='violation_id', aggfunc='count'),
                    Unique_Pages=pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                    Critical_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'critical')),
                    Serious_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'serious')),
                    Moderate_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'moderate')),
                    Minor_Violations=pd.NamedAgg(column='impact', aggfunc=lambda x: sum(x == 'minor')),
                    Unique_Violations=pd.NamedAgg(column='violation_id', aggfunc='nunique'),
                    WCAG_Categories=pd.NamedAgg(column='wcag_category', aggfunc=lambda x: len(set(x)))
                ).reset_index()
                
                # Calculate priority score and metrics
                agg_section['Priority_Score'] = (
                    agg_section['Critical_Violations'] * 4 + 
                    agg_section['Serious_Violations'] * 3 + 
                    agg_section['Moderate_Violations'] * 2 +
                    agg_section['Minor_Violations'] * 1
                )
                
                # Calculate violations per page
                agg_section['Violations_Per_Page'] = agg_section['Total_Violations'] / \
                                                    agg_section['Unique_Pages'].clip(lower=1)
                
                # Sort by section
                agg_section = agg_section.sort_values('page_section')
                
                aggregations['By Section'] = agg_section
            except Exception as e:
                self.logger.error(f"Error creating section aggregation: {e}")
                aggregations['By Section'] = pd.DataFrame()
        
        return aggregations

    def create_charts(self, metrics: Dict, aggregations: Dict[str, pd.DataFrame], 
                     data_df: pd.DataFrame) -> Dict[str, str]:
        """
        Create charts using the output manager for consistent paths.
        
        Args:
            metrics: Dictionary of metrics
            aggregations: Dictionary of aggregation DataFrames
            data_df: Source DataFrame
            
        Returns:
            Dictionary mapping chart types to file paths
        """
        # Get charts directory from output manager
        if self.output_manager:
            charts_dir = self.output_manager.get_path("charts")
        else:
            charts_dir = Path("./charts")
            charts_dir.mkdir(exist_ok=True)
            
        self.logger.info(f"Generating charts in {charts_dir}")

        chart_files = {}
        
        # Optimized color palette for accessibility
        colors = {
            'critical': '#E63946',
            'serious': '#F4A261',
            'moderate': '#2A9D8F',
            'minor': '#457B9D',
            'unknown': '#BDBDBD'
        }
        
        wcag_colors = {
            'Perceivable': '#0077B6',
            'Operable': '#00B4D8',
            'Understandable': '#90BE6D',
            'Robust': '#F9C74F',
            'Other': '#ADADAD'
        }
        
        plt.style.use('seaborn-v0_8-whitegrid')
        sns.set_style("whitegrid")
        plt.rcParams['figure.dpi'] = 150
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
        plt.rcParams['axes.labelsize'] = 12
        plt.rcParams['axes.titlesize'] = 16
        plt.rcParams['xtick.labelsize'] = 10
        plt.rcParams['ytick.labelsize'] = 10
        
        # 1. Donut chart for impact distribution
        if 'By Impact' in aggregations and not aggregations['By Impact'].empty:
            fig, ax = plt.subplots(figsize=(10, 7))
            
            impact_df = aggregations['By Impact'].copy()
            impact_labels = impact_df['impact']
            sizes = impact_df['Total_Violations']
            impact_colors = [colors.get(i, '#BDBDBD') for i in impact_labels]
            
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=None,
                autopct=lambda pct: f"{pct:.1f}%\n({int(pct*sum(sizes)/100)})" if pct > 3 else '',
                startangle=90,
                wedgeprops={'width': 0.5, 'edgecolor': 'w', 'linewidth': 1.5},
                colors=impact_colors
            )
            
            for text in autotexts:
                text.set_color('white')
                text.set_fontweight('bold')
            
            center_circle = plt.Circle((0, 0), 0.3, fc='white')
            ax.add_patch(center_circle)
            
            total_violations = sum(sizes)
            unique_pages = metrics.get('Unique Pages', 0)
            ax.text(0, 0.1, f"Violations\nby Impact", 
                   ha='center', va='center',
                   fontsize=16, fontweight='bold')
            
            if unique_pages > 0:
                ax.text(0, -0.1, f"{round(total_violations/unique_pages, 1)}\nper page", 
                       ha='center', va='center',
                       fontsize=12)
            
            legend_labels = []
            for impact, count, pct in zip(impact_labels, sizes, impact_df['Percentage']):
                legend_labels.append(f"{impact.capitalize()} ({count}, {pct}%)")
            
            ax.legend(wedges, legend_labels, title="Impact Level", 
                     loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
            
            plt.title('Accessibility Violations by Impact Level', fontsize=16)
            plt.tight_layout(rect=[0, 0, 1, 1])
            chart_path = charts_dir / 'chart_impact.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            chart_files['impact'] = str(chart_path)
        
        # 2. Bar chart for problematic pages
        if 'By Page' in aggregations and not aggregations['By Page'].empty:
            fig, ax = plt.subplots(figsize=(12, 8))
            
            pages_df = aggregations['By Page'].head(10).copy()
            pages_df = pages_df.sort_values('Priority_Score')
            
            labels = []
            for url, page_type in zip(pages_df['Display_URL'], pages_df['Page_Type']):
                labels.append(f"{url}\n[{page_type}]")
            
            ax.barh(labels, pages_df['Minor_Violations'], 
                   color=colors['minor'], label='Minor',
                   edgecolor='white', linewidth=0.5)
            ax.barh(labels, pages_df['Moderate_Violations'], 
                   left=pages_df['Minor_Violations'], 
                   color=colors['moderate'], label='Moderate',
                   edgecolor='white', linewidth=0.5)
            ax.barh(labels, pages_df['Serious_Violations'], 
                   left=pages_df['Minor_Violations'] + pages_df['Moderate_Violations'], 
                   color=colors['serious'], label='Serious',
                   edgecolor='white', linewidth=0.5)
            ax.barh(labels, pages_df['Critical_Violations'], 
                   left=pages_df['Minor_Violations'] + pages_df['Moderate_Violations'] + pages_df['Serious_Violations'], 
                   color=colors['critical'], label='Critical',
                   edgecolor='white', linewidth=0.5)
            
            for i, (total, score, index) in enumerate(zip(
                pages_df['Total_Violations'], 
                pages_df['Priority_Score'],
                pages_df.get('Accessibility_Index', [0]*len(pages_df))
            )):
                ax.text(
                    total + 0.5, 
                    i, 
                    f"Total: {total} | Score: {score:.1f}" + (f" | Index: {index:.1f}" if index > 0 else ""), 
                    va='center',
                    fontweight='bold',
                    fontsize=9
                )
            
            ax.set_title('Top 10 Problematic Pages by Violation Severity', fontsize=16)
            ax.set_xlabel('Number of Violations', fontsize=12)
            ax.set_ylabel('Page URL', fontsize=12)
            
            legend = ax.legend(
                title="Severity Level",
                loc='lower right',
                frameon=True,
                framealpha=0.9,
                edgecolor='gray'
            )
            legend.get_title().set_fontweight('bold')
            
            plt.grid(axis='x', linestyle='--', alpha=0.7)
            plt.tight_layout()
            
            chart_path = charts_dir / 'chart_top_pages.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            chart_files['top_pages'] = str(chart_path)
        
        # 3. Bar chart for violation types with WCAG info
        if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
            plt.figure(figsize=(12, 8))
            
            violations_df = aggregations['By Violation'].head(10).copy()
            violations_df = violations_df.sort_values('Total_Violations')
            
            labels = []
            for vid, category, criterion in zip(
                violations_df['violation_id'], 
                violations_df['WCAG_Category'],
                violations_df['WCAG_Criterion']
            ):
                labels.append(f"{vid}\n[{category} {criterion}]")
            
            bar_colors = [colors.get(impact, '#BDBDBD') for impact in violations_df['Most_Common_Impact']]
            
            bars = plt.barh(
                labels, 
                violations_df['Total_Violations'],
                color=bar_colors, 
                alpha=0.8,
                edgecolor='white', 
                linewidth=0.5
            )
            
            for i, bar in enumerate(bars):
                width = bar.get_width()
                affected = violations_df.iloc[i]['Affected_Pages']
                plt.text(
                    width + 1, 
                    bar.get_y() + bar.get_height()/2,
                    f"{violations_df.iloc[i]['Percentage']}% ({affected} pages)",
                    va='center',
                    fontweight='bold',
                    fontsize=9
                )
            
            plt.title('Most Common Accessibility Violations', fontsize=16)
            plt.xlabel('Number of Occurrences', fontsize=12)
            
            handles = [plt.Rectangle((0,0),1,1, color=colors[k]) for k in ['critical', 'serious', 'moderate', 'minor']]
            plt.legend(
                handles, 
                ['Critical', 'Serious', 'Moderate', 'Minor'],
                title="Impact Level", 
                loc='lower right',
                frameon=True,
                framealpha=0.9
            )
            
            plt.grid(axis='x', linestyle='--', alpha=0.7)
            plt.tight_layout()
            
            chart_path = charts_dir / 'chart_violation_types.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            chart_files['violation_types'] = str(chart_path)
            
        # 4. Chart for WCAG categorization
        if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
            wcag_df = aggregations['By Violation'].copy()
            wcag_counts = wcag_df.groupby('WCAG_Category')[['Total_Violations']].sum().reset_index()
            wcag_counts = wcag_counts.sort_values('Total_Violations', ascending=True)
            
            fig, ax = plt.subplots(figsize=(10, 6))
            bar_colors = [wcag_colors.get(cat, '#ADADAD') for cat in wcag_counts['WCAG_Category']]
            bars = ax.barh(
                wcag_counts['WCAG_Category'], 
                wcag_counts['Total_Violations'],
                color=bar_colors,
                edgecolor='white',
                linewidth=0.8
            )
            
            total = wcag_counts['Total_Violations'].sum()
            for i, bar in enumerate(bars):
                count = wcag_counts.iloc[i]['Total_Violations']
                percentage = (count / total * 100) if total > 0 else 0
                ax.text(
                    bar.get_width() + 0.5, 
                    bar.get_y() + bar.get_height()/2,
                    f"{count} ({percentage:.1f}%)",
                    va='center',
                    fontsize=10
                )
            
            ax.set_title('WCAG Principles Breakdown', fontsize=16)
            ax.set_xlabel('Number of Violations', fontsize=12)
            ax.set_ylabel('WCAG Principle', fontsize=12)
            
            plt.figtext(
                0.05, 0.01, 
                "Perceivable: Content must be presentable to users in ways they can perceive\n"
                "Operable: User interface components must be operable\n"
                "Understandable: Information and operation must be understandable\n"
                "Robust: Content must be robust enough to work with assistive technologies",
                fontsize=8,
                wrap=True
            )
            
            plt.grid(axis='x', linestyle='--', alpha=0.7)
            plt.tight_layout(rect=[0, 0.05, 1, 0.98])
            
            chart_path = charts_dir / 'chart_wcag_categories.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            chart_files['wcag_categories'] = str(chart_path)
            
        # 5. Heat map for page type and impact
        if 'By Page Type' in aggregations and not aggregations['By Page Type'].empty and 'By Impact' in aggregations:
            try:
                impact_df = aggregations['By Impact'].copy()
                page_type_df = aggregations['By Page Type'].copy()
                
                pivot_data = []
                for page_type in page_type_df['page_type']:
                    row_data = {'page_type': page_type}
                    # Use the DataFrame passed as parameter (data_df) to access the 'page_type' column
                    page_subset = data_df[data_df['page_type'] == page_type]
                    
                    page_count = page_subset['normalized_url'].nunique()
                    
                    for impact in ['critical', 'serious', 'moderate', 'minor']:
                        count = page_subset['impact'].value_counts().get(impact, 0)
                        row_data[impact] = count / max(page_count, 1)
                        
                    pivot_data.append(row_data)
                
                pivot_df = pd.DataFrame(pivot_data)
                
                if not pivot_df.empty and len(pivot_df) > 1:
                    plt.figure(figsize=(12, 8))
                    heatmap_data = pivot_df.set_index('page_type')
                    cmap = sns.color_palette("YlOrRd", as_cmap=True)
                    
                    ax = sns.heatmap(
                        heatmap_data, 
                        annot=True, 
                        fmt=".2f", 
                        cmap=cmap,
                        linewidths=.5,
                        cbar_kws={'label': 'Violations per Page'}
                    )
                    
                    plt.title('Violations per Page Type and Impact Level', fontsize=16)
                    plt.ylabel('Page Type', fontsize=12)
                    plt.xlabel('Impact Level', fontsize=12)
                    plt.xticks(rotation=0)
                    plt.tight_layout()
                    
                    chart_path = charts_dir / 'chart_page_type_heatmap.png'
                    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    
                    chart_files['page_type_heatmap'] = str(chart_path)
            except Exception as e:
                self.logger.error(f"Error creating page type heatmap: {e}")
                
        # 6. Chart for templates
        if 'template' in data_df.columns:
            try:
                template_data = []
                for template in data_df['template'].unique():
                    if template == "Unknown":
                        continue
                    template_subset = data_df[data_df['template'] == template]
                    template_pages = template_subset['normalized_url'].nunique()
                    if template_pages < 2:
                        continue
                    template_data.append({
                        'template': template,
                        'pages': template_pages,
                        'total_violations': len(template_subset),
                        'avg_per_page': len(template_subset) / template_pages,
                        'critical': template_subset[template_subset['impact'] == 'critical']['normalized_url'].nunique(),
                        'critical_pct': (template_subset[template_subset['impact'] == 'critical']['normalized_url'].nunique() / template_pages) * 100
                    })
                
                if template_data:
                    template_df = pd.DataFrame(template_data)
                    template_df = template_df.sort_values('avg_per_page', ascending=False).head(10)
                    
                    plt.figure(figsize=(12, 8))
                    
                    template_df['template_short'] = template_df['template'].apply(
                        lambda x: x[-25:] if len(x) > 25 else x
                    )
                    
                    bars = plt.bar(
                        template_df['template_short'],
                        template_df['avg_per_page'],
                        color='#4472C4',
                        alpha=0.8,
                        edgecolor='white',
                        linewidth=0.8
                    )
                    
                    ax2 = plt.twinx()
                    ax2.plot(
                        template_df['template_short'],
                        template_df['critical_pct'],
                        'ro-',
                        linewidth=2,
                        markersize=8,
                        alpha=0.7
                    )
                    
                    plt.title('Accessibility Issues by Template', fontsize=16)
                    plt.ylabel('Average Violations per Page', fontsize=12)
                    ax2.set_ylabel('Pages with Critical Issues (%)', color='r', fontsize=12)
                    
                    for i, bar in enumerate(bars):
                        plt.text(
                            bar.get_x() + bar.get_width()/2,
                            bar.get_height() + 0.2,
                            f"{bar.get_height():.1f}",
                            ha='center',
                            fontsize=9
                        )
                    
                    plt.xticks(rotation=45, ha='right')
                    plt.tight_layout()
                    
                    chart_path = charts_dir / 'chart_template_analysis.png'
                    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    
                    chart_files['template_analysis'] = str(chart_path)
            except Exception as e:
                self.logger.error(f"Error creating template analysis chart: {e}")
                
        return chart_files
    
    def load_template_data(self, pickle_file: str) -> Tuple[pd.DataFrame, Dict]:
        """
        Optimized: Load template data with more robust structure.
        
        Args:
            pickle_file: Path to pickle file with template data
            
        Returns:
            Tuple of (templates DataFrame, state dictionary)
        """
        self.logger.info(f"Loading template data from {pickle_file}")
        
        if not os.path.exists(pickle_file):
            raise FileNotFoundError(f"Template pickle file '{pickle_file}' not found")
            
        try:
            with open(pickle_file, "rb") as f:
                state = pickle.load(f)
                
            if "structures" not in state:
                self.logger.warning("Pickle file doesn't contain expected 'structures' key")
                state["structures"] = {}
                
            structures = state.get("structures", {})
            self.logger.info(f"Loaded {len(structures)} template structures")
            
            templates = []
            for template, data in structures.items():
                rep_url = data.get('url', '')
                template_urls = data.get('urls', [])
                
                if not template_urls and 'url_list' in data:
                    template_urls = data.get('url_list', [])
                
                if not template_urls and rep_url:
                    template_urls = [rep_url]
                
                templates.append({
                    'Template': template,
                    'Representative URL': rep_url,
                    'Normalized Rep URL': self.normalize_url(rep_url),
                    'Count': data.get('count', len(template_urls) if template_urls else 0),
                    'Template Pages': template_urls,
                    'Template Depth': data.get('depth', 0)
                })
                
            templates_df = pd.DataFrame(templates)
            
            if not templates_df.empty:
                templates_df = templates_df.sort_values('Count', reverse=True)
                
            self.logger.info(f"Processed {len(templates_df)} templates")
            return templates_df, state
            
        except Exception as e:
            self.logger.error(f"Error loading template data: {e}")
            raise
    
    def _analyze_single_template(self, row, axe_df, analyzed_urls) -> Dict:
        """
        Analyze a template on a representative sample (one page per template) and
        calculate projected violations across the site by multiplying by occurrences.
        
        Args:
            row: A row from the templates DataFrame
            axe_df: DataFrame with accessibility data
            analyzed_urls: Set of analyzed URLs
        
        Returns:
            Dictionary with analysis data for the template
        """
        template_name = row['Template']
        rep_url = row['Representative URL']
        norm_rep_url = row['Normalized Rep URL']
        occurrence = row['Count']  # Number of pages for this template
        rep_violations = axe_df[axe_df['normalized_url'] == norm_rep_url]
        sample_violation_count = len(rep_violations)
        impact_counts = rep_violations['impact'].value_counts().to_dict()
        projected_total = sample_violation_count * occurrence
        projected_critical = impact_counts.get('critical', 0) * occurrence
        projected_serious = impact_counts.get('serious', 0) * occurrence
        projected_moderate = impact_counts.get('moderate', 0) * occurrence
        projected_minor = impact_counts.get('minor', 0) * occurrence
        if occurrence > 0:
            priority_score = (
                projected_critical * 4 +
                projected_serious * 3 +
                projected_moderate * 2 +
                projected_minor * 1
            ) / occurrence
        else:
            priority_score = 0
        if priority_score > 5:
            criticality = "High"
        elif priority_score > 2:
            criticality = "Medium"
        else:
            criticality = "Low"
        result = {
            'Template': template_name,
            'Representative URL': rep_url,
            'Occurrence': occurrence,
            'Sample Violations': sample_violation_count,
            'Projected Total Violations': projected_total,
            'Projected Critical': projected_critical,
            'Projected Serious': projected_serious,
            'Projected Moderate': projected_moderate,
            'Projected Minor': projected_minor,
            'Priority Score': round(priority_score, 2),
            'Criticality': criticality,
            'Projection Note': "Computed as: (Violations on representative page) x (Template occurrence)"
        }
        return result

    def analyze_templates(self, templates_df: pd.DataFrame, axe_df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze templates based on a representative page per template and project
        total violations across the entire site by multiplying by occurrences.
        
        Args:
            templates_df: DataFrame with template data
            axe_df: DataFrame with accessibility data
            
        Returns:
            DataFrame with template analysis
        """
        self.logger.info("Analyzing templates and projecting violations based on representative sample")
        if templates_df.empty or axe_df.empty:
            self.logger.warning("Empty DataFrames, cannot analyze templates")
            return pd.DataFrame()
        analyzed_urls = set(axe_df['normalized_url'].unique())
        self.logger.info(f"Found {len(analyzed_urls)} unique analyzed URLs")
        template_results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for _, row in templates_df.iterrows():
                futures.append(
                    executor.submit(
                        self._analyze_single_template,
                        row,
                        axe_df,
                        analyzed_urls
                    )
                )
            for future in futures:
                try:
                    result = future.result()
                    if result:
                        template_results.append(result)
                except Exception as e:
                    self.logger.error(f"Error analyzing template: {e}")
        result_df = pd.DataFrame(template_results)
        if not result_df.empty:
            result_df = result_df.sort_values('Priority Score', ascending=False)
        self.logger.info(f"Template analysis complete: {len(result_df)} templates processed")
        return result_df

    def generate_report(self, axe_df: pd.DataFrame, metrics: Dict, 
                            aggregations: Dict[str, pd.DataFrame], chart_files: Dict[str, str],
                            template_df: Optional[pd.DataFrame] = None, 
                            output_excel: Optional[str] = None) -> str:
        """
        Generate a comprehensive Excel report with improved presentation.
        
        Args:
            axe_df: DataFrame with accessibility data
            metrics: Dictionary of metrics
            aggregations: Dictionary of aggregation DataFrames
            chart_files: Dictionary of chart file paths
            template_df: DataFrame with template analysis
            output_excel: Path to output Excel file
            
        Returns:
            Path to generated Excel file
        """
        # If using OutputManager
        if hasattr(self, 'output_manager') and self.output_manager:
            if output_excel is None:
                output_excel = str(self.output_manager.get_path(
                    "analysis", f"final_analysis_{self.output_manager.domain_slug}.xlsx"))
                
            # Backup existing report if it exists
            if os.path.exists(output_excel) and hasattr(self.output_manager, 'backup_existing_file'):
                backup_path = self.output_manager.backup_existing_file(
                    "analysis", os.path.basename(output_excel))
                if backup_path:
                    self.logger.info(f"Backed up existing report to {backup_path}")
        
        self.logger.info(f"Generating report: {output_excel}")
        
        # Log the aggregation data sizes for debugging
        for name, df in aggregations.items():
            self.logger.info(f"Aggregation '{name}' has {len(df)} rows and columns: {list(df.columns)}")
        
        timestamp = datetime.now().strftime("%Y-%m-%d")
        
        with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            # Define Excel formatting styles
            title_format = workbook.add_format({
                'bold': True, 'font_size': 16, 'align': 'center',
                'valign': 'vcenter', 'bg_color': '#4472C4', 'font_color': 'white',
                'border': 1, 'text_wrap': True
            })
            subtitle_format = workbook.add_format({
                'bold': True, 'font_size': 14, 'align': 'left',
                'bg_color': '#D9E1F2', 'border': 1, 'text_wrap': True
            })
            header_format = workbook.add_format({
                'bold': True, 'bg_color': '#D9E1F2', 'border': 1,
                'align': 'center', 'valign': 'vcenter', 'text_wrap': True
            })
            cell_format = workbook.add_format({'border': 1, 'valign': 'top', 'text_wrap': True})
            num_format = workbook.add_format({'num_format': '#,##0', 'align': 'right', 'border': 1})
            metric_format = workbook.add_format({
                'bold': True, 'font_size': 13, 'align': 'center',
                'valign': 'vcenter', 'border': 1, 'bg_color': '#DDEBF7'
            })
            critical_format = workbook.add_format({
                'border': 1, 'bg_color': '#FFCCCC', 'align': 'right',
                'num_format': '#,##0'
            })
            
            # Create Executive Summary worksheet
            summary_ws = workbook.add_worksheet('Executive Summary')
            summary_ws.set_column('A:A', 40)
            summary_ws.set_column('B:B', 25)
            summary_ws.set_column('C:C', 35)
            summary_ws.merge_range('A1:C1', f'Accessibility Analysis Report - {timestamp}', title_format)
            summary_ws.merge_range('A2:C2', 'Executive Summary', subtitle_format)
            
            row = 3
            summary_ws.merge_range(f'A{row}:C{row}', 'Key Performance Indicators', subtitle_format)
            row += 1
            kpi_row = row
            conformance_score = metrics.get('WCAG Conformance Score', 0)
            conformance_level = metrics.get('WCAG Conformance Level', 'Unknown')
            score_color = '#92D050' if conformance_score >= 90 else '#FFEB9C' if conformance_score >= 75 else '#FF9999'
            score_format = workbook.add_format({
                'bold': True, 'font_size': 22, 'align': 'center',
                'valign': 'vcenter', 'border': 1, 'bg_color': score_color
            })
            summary_ws.merge_range(f'A{kpi_row}:A{kpi_row+3}', 'WCAG Conformance', metric_format)
            summary_ws.merge_range(f'B{kpi_row}:B{kpi_row+3}', conformance_score, score_format)
            summary_ws.write(kpi_row, 2, f"Level: {conformance_level}", cell_format)
            summary_ws.write(kpi_row+1, 2, f"Pages: {metrics.get('Unique Pages', 0)}", cell_format)
            summary_ws.write(kpi_row+2, 2, f"Violations: {metrics.get('Total Violations', 0)}", cell_format)
            
            row += 5
            summary_ws.merge_range(f'A{row}:C{row}', '', workbook.add_format({'bottom': 2, 'top': 2}))
            row += 1
            
            # Template Projection Metrics section (if available)
            if template_df is not None and not template_df.empty:
                row += 2
                summary_ws.merge_range(f'A{row}:C{row}', 'Template Projection Metrics', subtitle_format)
                row += 1
                total_proj = template_df['Projected Total Violations'].sum()
                total_proj_crit = template_df['Projected Critical'].sum()
                total_proj_serious = template_df['Projected Serious'].sum()
                total_proj_moderate = template_df['Projected Moderate'].sum()
                total_proj_minor = template_df['Projected Minor'].sum()
                avg_proj = template_df['Projected Total Violations'].mean()
                
                summary_ws.write(row, 0, 'Total Projected Violations', cell_format)
                summary_ws.write(row, 1, total_proj, num_format)
                summary_ws.write(row, 2, 'Sum of projected violations from template analysis', cell_format)
                row += 1
                summary_ws.write(row, 0, 'Total Projected Critical Violations', cell_format)
                summary_ws.write(row, 1, total_proj_crit, num_format)
                summary_ws.write(row, 2, 'Projected critical violations aggregated over all templates', cell_format)
                row += 1
                summary_ws.write(row, 0, 'Total Projected Serious Violations', cell_format)
                summary_ws.write(row, 1, total_proj_serious, num_format)
                summary_ws.write(row, 2, 'Projected serious violations aggregated over all templates', cell_format)
                row += 1
                summary_ws.write(row, 0, 'Total Projected Moderate Violations', cell_format)
                summary_ws.write(row, 1, total_proj_moderate, num_format)
                summary_ws.write(row, 2, 'Projected moderate violations aggregated over all templates', cell_format)
                row += 1
                summary_ws.write(row, 0, 'Total Projected Minor Violations', cell_format)
                summary_ws.write(row, 1, total_proj_minor, num_format)
                summary_ws.write(row, 2, 'Projected minor violations aggregated over all templates', cell_format)
                row += 1
                summary_ws.write(row, 0, 'Average Projected Violations per Template', cell_format)
                summary_ws.write(row, 1, round(avg_proj, 2), num_format)
                summary_ws.write(row, 2, 'Average number of projected violations per template', cell_format)
                row += 1
            
            row += 1
            summary_ws.merge_range(f'A{row}:C{row}', 'Detailed Metrics', subtitle_format)
            row += 1
            summary_ws.write(row, 0, 'Metric', header_format)
            summary_ws.write(row, 1, 'Value', header_format)
            summary_ws.write(row, 2, 'Description/Impact', header_format)
            row += 1
            
            metric_descriptions = {
                'Total Violations': 'Total number of accessibility issues detected across all pages',
                'Unique Pages': 'Number of unique pages analyzed',
                'Average Violations per Page': 'Average number of issues found on each page',
                'Critical Violations': 'Issues that severely impact accessibility for users with disabilities',
                'Serious Violations': 'Significant barriers that should be addressed with high priority',
                'Moderate Violations': 'Issues that impact some users and should be addressed',
                'Minor Violations': 'Minor issues that have limited impact on accessibility',
                'Weighted Severity Score': 'Combined score weighted by severity (lower is better)',
                'Pages with Critical Issues (%)': 'Percentage of pages with critical accessibility barriers'
            }
            
            for key, value in metrics.items():
                if key in ['Top WCAG Issues', 'Page Type Analysis', 'WCAG Conformance Score', 'WCAG Conformance Level']:
                    continue
                if 'Critical' in key and isinstance(value, (int, float)) and value > 0:
                    value_format = critical_format
                elif isinstance(value, (int, float)):
                    value_format = num_format
                else:
                    value_format = cell_format
                summary_ws.write(row, 0, key, cell_format)
                summary_ws.write(row, 1, value, value_format)
                summary_ws.write(row, 2, metric_descriptions.get(key, ""), cell_format)
                row += 1
            
            row += 1
            summary_ws.merge_range(f'A{row}:C{row}', 'Top Recommendations', subtitle_format)
            row += 1
            summary_ws.write(row, 0, 'Issue', header_format)
            summary_ws.write(row, 1, 'Priority', header_format)
            summary_ws.write(row, 2, 'Recommended Action', header_format)
            row += 1
            
            if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
                critical_issues = aggregations['By Violation'][
                    (aggregations['By Violation']['Most_Common_Impact'] == 'critical') |
                    (aggregations['By Violation']['Most_Common_Impact'] == 'serious')
                ].sort_values('Priority_Score', ascending=False).head(5)
                for _, issue in critical_issues.iterrows():
                    priority = issue['Most_Common_Impact'].capitalize()
                    priority_cell_format = workbook.add_format({
                        'border': 1, 
                        'align': 'center',
                        'bold': True,
                        'bg_color': '#FFCCCC' if priority == 'Critical' else '#FFEB9C',
                        'font_color': 'black' 
                    })
                    summary_ws.write(row, 0, issue['violation_id'], cell_format)
                    summary_ws.write(row, 1, priority, priority_cell_format)
                    tech_solution = issue.get('Technical_Solution', "See WCAG guidelines")
                    user_impact = f"\n\nImpact: {issue.get('User_Impact', '')}"
                    summary_ws.write(row, 2, tech_solution + user_impact, cell_format)
                    row += 1
            
            row += 2
            summary_ws.merge_range(f'A{row}:C{row}', 'Key Visualizations', subtitle_format)
            row += 1
            chart_y_pos = row
            if 'impact' in chart_files:
                summary_ws.insert_image(chart_y_pos, 0, chart_files['impact'], {'x_scale': 0.5, 'y_scale': 0.5})
                chart_y_pos += 18
            if 'wcag_categories' in chart_files:
                summary_ws.insert_image(chart_y_pos, 0, chart_files['wcag_categories'], {'x_scale': 0.5, 'y_scale': 0.5})
            
            # Create Detailed Analysis worksheet
            detail_ws = workbook.add_worksheet('Detailed Analysis')
            detail_ws.set_column('A:A', 40)
            for col in range(1, 10):
                detail_ws.set_column(col, col, 15)

            # Helper function to write DataFrames to Excel
            def write_dataframe(ws, dataframe, start_row, title, max_cols=15, include_help=False):
                if dataframe.empty:
                    self.logger.warning(f"Skipping empty DataFrame: {title}")
                    return start_row + 2
                
                self.logger.info(f"Writing DataFrame '{title}' with {len(dataframe)} rows and {len(dataframe.columns)} columns to row {start_row}")
                
                ws.merge_range(f'A{start_row}:G{start_row}', title, subtitle_format)
                start_row += 1
                
                if include_help:
                    help_text = f"This section shows {title.lower()} with detailed metrics and analysis."
                    ws.merge_range(f'A{start_row}:G{start_row}', help_text, 
                                workbook.add_format({'italic': True, 'font_color': '#595959'}))
                    start_row += 1
                
                cols_to_write = list(dataframe.columns)[:max_cols]
                
                for col_idx, col_name in enumerate(cols_to_write):
                    ws.write(start_row, col_idx, col_name, header_format)
                    if "URL" in col_name or "Template" in col_name:
                        ws.set_column(col_idx, col_idx, 40)
                    elif "Solution" in col_name or "Description" in col_name:
                        ws.set_column(col_idx, col_idx, 30)
                    else:
                        ws.set_column(col_idx, col_idx, 15)
                
                start_row += 1
                
                for r_idx, (_, row_data) in enumerate(dataframe.iterrows()):
                    base_row_format = workbook.add_format({
                        'border': 1,
                        'valign': 'top',
                        'bg_color': '#F2F2F2' if r_idx % 2 == 0 else 'white'
                    })
                    base_row_format.set_text_wrap()
                    
                    for c_idx, col_name in enumerate(cols_to_write):
                        if c_idx >= max_cols:
                            break
                        try:
                            value = row_data[col_name]
                        except KeyError:
                            self.logger.warning(f"Column {col_name} not found in row. Available: {row_data.index.tolist()}")
                            value = "N/A"
                        
                        cell_fmt = base_row_format
                        
                        if "Critical" in col_name and isinstance(value, (int, float)) and value > 0:
                            cell_fmt = workbook.add_format({
                                'border': 1,
                                'valign': 'top',
                                'bg_color': '#FFCCCB',
                                'num_format': '#,##0'
                            })
                        elif "Serious" in col_name and isinstance(value, (int, float)) and value > 0:
                            cell_fmt = workbook.add_format({
                                'border': 1,
                                'valign': 'top',
                                'bg_color': '#FFDEAD',
                                'num_format': '#,##0'
                            })
                        elif isinstance(value, (int, float)) and not pd.isna(value) and "Percentage" not in col_name:
                            cell_fmt = workbook.add_format({
                                'border': 1,
                                'valign': 'top',
                                'bg_color': '#F2F2F2' if r_idx % 2 == 0 else 'white',
                                'num_format': '#,##0'
                            })
                        
                        if col_name == 'Priority_Score' and isinstance(value, (int, float)):
                            if value > 5:
                                cell_fmt = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'num_format': '#,##0.00'
                                })
                            elif value > 2:
                                cell_fmt = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD', 'num_format': '#,##0.00'
                                })
                        
                        try:
                            if isinstance(value, (int, float)) and not pd.isna(value):
                                ws.write_number(start_row + r_idx, c_idx, value, cell_fmt)
                            else:
                                ws.write_string(start_row + r_idx, c_idx, str(value), cell_fmt)
                        except Exception as e:
                            self.logger.error(f"Error writing cell ({start_row + r_idx}, {c_idx}): {e}")
                            ws.write(start_row + r_idx, c_idx, str(value), cell_format)
                
                end_row = start_row + len(dataframe) + 1
                return end_row
            
            row = 1
            detail_ws.merge_range('A1:G1', 'Detailed Accessibility Analysis', title_format)
            
            for name, df in aggregations.items():
                row = write_dataframe(detail_ws, df, row + 1, name, include_help=True)
            
            # Create Template Analysis worksheet if template data is available
            if template_df is not None and not template_df.empty:
                template_ws = workbook.add_worksheet('Template Analysis')
                template_ws.set_column('A:A', 40)
                template_ws.set_column('B:B', 40)
                template_ws.set_column('C:H', 15)
                template_ws.set_column('I:I', 40)
                
                template_ws.merge_range('A1:I1', 'Template-Based Analysis', title_format)
                template_ws.merge_range('A2:I2', 'Projections based on analyzed pages with template detection', 
                                    workbook.add_format({'italic': True, 'font_color': '#595959'}))
                row = 3
                
                template_ws.merge_range('A3:I3', 
                                    'Template analysis helps identify common patterns of issues across similar pages. '
                                    'Higher confidence means more reliable predictions.',
                                    workbook.add_format({'italic': True, 'font_color': '#595959'}))
                row += 1
                
                for col_idx, col_name in enumerate(template_df.columns):
                    template_ws.write(row, col_idx, col_name, header_format)
                
                row += 1
                
                for r_idx, row_data in template_df.iterrows():
                    for c_idx, col_name in enumerate(template_df.columns):
                        value = row_data[col_name]
                        
                        row_format = workbook.add_format({
                            'border': 1,
                            'valign': 'top',
                            'text_wrap': True,
                            'bg_color': '#F2F2F2' if r_idx % 2 == 0 else 'white'
                        })
                        
                        if col_name == 'Priority Score':
                            if value > 4:
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'num_format': '#,##0.00'
                                })
                            elif value > 2:
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD', 'num_format': '#,##0.00'
                                })
                        elif col_name == 'Confidence (%)':
                            if value < 30:
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'num_format': '#,##0.00'
                                })
                            elif value < 70:
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD', 'num_format': '#,##0.00'
                                })
                            else:
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#C6EFCE', 'num_format': '#,##0.00'
                                })
                        elif col_name == 'Criticality':
                            if value == 'High':
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'bold': True
                                })
                            elif value == 'Medium':
                                row_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD'
                                })
                        elif 'Est. Critical' in col_name and isinstance(value, (int, float)) and value > 0:
                            row_format = workbook.add_format({
                                'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'num_format': '#,##0'
                            })
                        elif isinstance(value, (int, float)) and not pd.isna(value):
                            row_format.set_num_format('#,##0')
                        
                        if isinstance(value, (int, float)) and not pd.isna(value):
                            template_ws.write_number(row + r_idx, c_idx, value, row_format)
                        else:
                            template_ws.write_string(row + r_idx, c_idx, str(value), row_format)
                
                footer_row = row + len(template_df) + 1
                template_ws.merge_range(f'A{footer_row}:I{footer_row}', 
                                    'Note: Estimations are based on actual detected violations projected across all pages with similar templates.',
                                    workbook.add_format({'italic': True, 'font_color': '#595959'}))
            
            # Create Charts worksheet
            charts_ws = workbook.add_worksheet('Charts')
            charts_ws.merge_range('A1:G1', 'Accessibility Visualizations', title_format)
            charts_ws.merge_range('A2:G2', 'Data-driven visual analysis of accessibility issues', 
                            workbook.add_format({'italic': True, 'font_color': '#595959'}))
            
            chart_descriptions = {
                'impact': 'Shows distribution of violations by impact severity level. Critical and serious violations should be prioritized.',
                'top_pages': 'Identifies the most problematic pages that need immediate attention.',
                'violation_types': 'Displays the most common accessibility violation types across the site.',
                'wcag_categories': 'Breaks down violations by WCAG principle (Perceivable, Operable, Understandable, Robust).',
                'page_type_heatmap': 'Heat map showing violation density by page type and impact level.',
                'template_analysis': 'Compares accessibility issues across different page templates.'
            }
            
            chart_row = 3
            chart_col = 0
            
            for i, (name, path) in enumerate(chart_files.items()):
                if i > 0:
                    chart_row += 22
                    chart_col = 0
                
                charts_ws.merge_range(f'{chr(65 + chart_col)}{chart_row}:{chr(65 + chart_col + 6)}{chart_row}', 
                                    f'Chart: {name.replace("_", " ").title()}', subtitle_format)
                
                if name in chart_descriptions:
                    charts_ws.merge_range(f'{chr(65 + chart_col)}{chart_row+1}:{chr(65 + chart_col + 6)}{chart_row+1}', 
                                        chart_descriptions[name],
                                        workbook.add_format({'italic': True, 'font_color': '#595959'}))
                
                charts_ws.insert_image(chart_row + 2, chart_col, path, {'x_scale': 0.8, 'y_scale': 0.8})
            
            # Create Raw Data worksheet
            raw_ws = workbook.add_worksheet('Raw Data')
            raw_ws.merge_range('A1:G1', 'Raw Accessibility Data', title_format)
            raw_ws.merge_range('A2:G2', 'Complete dataset for detailed analysis and export', 
                            workbook.add_format({'italic': True, 'font_color': '#595959'}))
            
            if not axe_df.empty:
                for col_idx, col_name in enumerate(axe_df.columns):
                    raw_ws.write(3, col_idx, col_name, header_format)
                    if "URL" in col_name:
                        raw_ws.set_column(col_idx, col_idx, 60)
                    elif "description" in col_name.lower() or "html" in col_name.lower():
                        raw_ws.set_column(col_idx, col_idx, 40)
                    else:
                        raw_ws.set_column(col_idx, col_idx, 15)
                
                raw_ws.autofilter(3, 0, 3 + len(axe_df.columns) - 1, len(axe_df.columns) - 1)
                
                for r_idx, row in axe_df.iterrows():
                    for c_idx, col_name in enumerate(axe_df.columns):
                        value = row[col_name]
                        
                        base_format = workbook.add_format({
                            'border': 1,
                            'valign': 'top',
                            'text_wrap': True,
                            'bg_color': '#F8F8F8' if r_idx % 2 == 0 else 'white'
                        })
                        
                        if col_name == 'impact':
                            if value == 'critical':
                                cell_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'bold': True
                                })
                            elif value == 'serious':
                                cell_format = workbook.add_format({
                                    'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD'
                                })
                            else:
                                cell_format = base_format
                        else:
                            cell_format = base_format
                        
                        try:
                            if isinstance(value, (int, float)) and not pd.isna(value):
                                raw_ws.write_number(r_idx + 4, c_idx, value, cell_format)
                            else:
                                raw_ws.write_string(r_idx + 4, c_idx, str(value), cell_format)
                        except Exception as e:
                            self.logger.error(f"Error writing raw data: {e}")
                            raw_ws.write(r_idx + 4, c_idx, str(value), cell_format)
                            
            # Create Recommendations worksheet
            recommendations_ws = workbook.add_worksheet('Recommendations')
            recommendations_ws.merge_range('A1:G1', 'Detailed Recommendations', title_format)
            recommendations_ws.set_column('A:A', 25)
            recommendations_ws.set_column('B:B', 15)
            recommendations_ws.set_column('C:C', 15)
            recommendations_ws.set_column('D:D', 40)
            recommendations_ws.set_column('E:E', 40)
            recommendations_ws.set_column('F:F', 30)
            recommendations_ws.set_column('G:G', 15)
            
            row = 3
            recommendations_ws.write(row, 0, 'Violation ID', header_format)
            recommendations_ws.write(row, 1, 'Impact', header_format)
            recommendations_ws.write(row, 2, 'WCAG Reference', header_format)
            recommendations_ws.write(row, 3, 'Description', header_format)
            recommendations_ws.write(row, 4, 'Technical Solution', header_format)
            recommendations_ws.write(row, 5, 'User Impact', header_format)
            recommendations_ws.write(row, 6, 'Occurrences', header_format)
            row += 1
            
            if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
                violations_df = aggregations['By Violation'].sort_values('Priority_Score', ascending=False)
                
                for _, violation in violations_df.iterrows():
                    impact_format = cell_format
                    impact = violation.get('Most_Common_Impact', 'unknown')
                    
                    if impact == 'critical':
                        impact_format = workbook.add_format({
                            'border': 1, 'valign': 'top', 'bg_color': '#FFCCCB', 'bold': True,
                            'align': 'center', 'text_wrap': True
                        })
                    elif impact == 'serious':
                        impact_format = workbook.add_format({
                            'border': 1, 'valign': 'top', 'bg_color': '#FFDEAD',
                            'align': 'center', 'text_wrap': True
                        })
                    
                    description = "Check WCAG guidelines for this violation"
                    if 'Solution_Description' in violation:
                        description = violation['Solution_Description']
                        
                    tech_solution = "Refer to WCAG documentation"
                    if 'Technical_Solution' in violation:
                        tech_solution = violation['Technical_Solution']
                        
                    user_impact = "May affect users with disabilities"
                    if 'User_Impact' in violation:
                        user_impact = violation['User_Impact']
                        
                    wcag_ref = "N/A"
                    if 'WCAG_Category' in violation and 'WCAG_Criterion' in violation:
                        wcag_ref = f"{violation['WCAG_Category']} {violation['WCAG_Criterion']}"
                    
                    recommendations_ws.write(row, 0, violation['violation_id'], cell_format)
                    recommendations_ws.write(row, 1, impact.capitalize(), impact_format)
                    recommendations_ws.write(row, 2, wcag_ref, cell_format)
                    recommendations_ws.write(row, 3, description, cell_format)
                    recommendations_ws.write(row, 4, tech_solution, cell_format)
                    recommendations_ws.write(row, 5, user_impact, cell_format)
                    recommendations_ws.write(row, 6, violation['Total_Violations'], num_format)
                    
                    row += 1
        
        self.logger.info(f"Report generated successfully: {output_excel}")
        
        return output_excel

    def run_analysis(self, input_excel: Optional[str] = None, crawler_state: Optional[str] = None) -> str:
        """Run the complete analysis pipeline with standardized paths."""
        self.logger.info("Starting accessibility analysis")
        
        # Load data
        df = self.load_data(input_excel, crawler_state)
        
        # Calculate metrics
        metrics = self.calculate_metrics(df)
        
        # Create aggregations
        aggregations = self.create_aggregations(df)
        
        # Create charts
        chart_files = self.create_charts(metrics, aggregations, df)
        
        # Generate report
        output_excel = self.generate_report(df, metrics, aggregations, chart_files)
        
        self.logger.info("Analysis completed successfully")
        return output_excel


def main():
    """
    Main function to run the accessibility analysis tool from command line.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Optimized Accessibility Analysis Tool')
    parser.add_argument('--domain', '-d', required=True, help='Domain being analyzed')
    parser.add_argument('--input', '-i', help='Excel file with axe data')
    parser.add_argument('--crawler', '-c', help='Optional crawler state file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--workers', '-w', type=int, default=4, help='Number of parallel workers')
    
    args = parser.parse_args()
    
    try:
        # Initialize configuration manager for paths
        config = ConfigurationManager()
        domain_config = config.load_domain_config(args.domain)
        
        # Create output manager
        output_root = config.get_path("OUTPUT_DIR", "~/axeScraper/output")
        output_manager = OutputManager(
            base_dir=output_root,
            domain=args.domain,
            create_dirs=True
        )
        
        # Create analyzer
        analyzer = AccessibilityAnalyzer(
            max_workers=args.workers,
            output_manager=output_manager
        )
        
        # Get standardized paths if not provided
        input_excel = args.input
        crawler_state = args.crawler
        
        if not input_excel:
            input_excel = str(output_manager.get_path(
                "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
                
        if not crawler_state:
            crawler_state = str(output_manager.get_path(
                "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
        
        # Run analysis
        report_path = analyzer.run_analysis(input_excel, crawler_state)
        print(f"Analysis complete. Report saved to: {report_path}")
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error during execution: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())