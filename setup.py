#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name='aiohttp-request-id-logging',
    version='0.0.1',
    description='Setup proper request id logging for your Aiohttp app',
    classifiers=[
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    packages=find_packages(exclude=['doc', 'tests*']),
    install_requires=[
        'aiohttp',
    ])
