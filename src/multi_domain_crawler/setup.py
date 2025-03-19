#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('README.md', encoding='utf-8') as readme_file:
    readme = readme_file.read()

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='multi_domain_crawler',
    version='1.0.0',
    description='Crawler multi-dominio avanzato basato su Scrapy',
    long_description=readme,
    long_description_content_type='text/markdown',
    author='capazme',
    author_email='guglielmo.puzio00@gmail.com',
    url='https://github.com/capazme/axe-crawler',
    packages=find_packages(include=['multi_domain_crawler', 'multi_domain_crawler.*']),
    include_package_data=True,
    install_requires=requirements,
    license='MIT',
    zip_safe=False,
    keywords='crawler, scrapy, multi-domain, web-scraping, selenium',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
    scripts=[
        'scripts/run_crawler.sh',
        'scripts/run_fresh.sh',
    ],
)