#!/usr/bin/env python3
"""
Script diagnostico per file crawler_state_*.pkl
"""
import sys
import pickle
from pathlib import Path


def main(pkl_path):
    pkl_path = Path(pkl_path)
    if not pkl_path.exists():
        print(f"File non trovato: {pkl_path}")
        return
    with open(pkl_path, 'rb') as f:
        state = pickle.load(f)

    # Trova la struttura giusta
    if 'structures' in state:
        structures = state['structures']
    elif 'domain_data' in state:
        # Prendi il primo dominio
        domain_data = next(iter(state['domain_data'].values()))
        structures = domain_data.get('structures', {})
    else:
        print("Formato file non riconosciuto.")
        return

    print(f"TEMPLATE TOTALI: {len(structures)}")
    total_urls = 0
    multi_url_templates = 0
    single_url_templates = 0
    example_templates = []
    for template, data in structures.items():
        urls = data.get('urls', [])
        count = len(urls)
        total_urls += count
        if count > 1:
            multi_url_templates += 1
        if count == 1:
            single_url_templates += 1
        example_templates.append((template, count, urls[:3]))

    print(f"URL TOTALI RACCOLTI: {total_urls}")
    print(f"Template con >1 URL: {multi_url_templates}")
    print(f"Template con 1 solo URL: {single_url_templates}")
    print("\nEsempi:")
    for tpl, cnt, urls in sorted(example_templates, key=lambda x: -x[1])[:5]:
        print(f"- {tpl}: {cnt} URL\n  Primi 3: {urls}")
    print("...")
    for tpl, cnt, urls in sorted(example_templates, key=lambda x: x[1])[:3]:
        print(f"- {tpl}: {cnt} URL\n  Primi 3: {urls}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python check_crawler_state.py <percorso_file_pkl>")
    else:
        main(sys.argv[1]) 