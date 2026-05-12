#!/usr/bin/env python3
"""Setup script for cocoview."""

from setuptools import setup, find_packages
import os

# Read README for long description
def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Local command center for Claude Code sessions"

setup(
    name="cocoview",
    version="0.1.0",
    description="Local command center for Claude Code sessions",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    author="Claude Code Community",
    url="https://github.com/gdagitrep/claude-code-viewer",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'claude_viewer': [
            'static/css/*.css',
            'static/js/*.js',
            'templates/*.html'
        ],
    },
    entry_points={
        'console_scripts': [
            'cocoview=claude_viewer.cli:main',
            'claude-viewer=claude_viewer.cli:main',
        ],
    },
    install_requires=[
        "fastapi>=0.104.1,<1.0.0",
        "uvicorn[standard]>=0.24.0,<1.0.0",
        "pydantic>=2.4.2,<3.0.0",
        "python-multipart>=0.0.6",
        "jinja2>=3.1.2,<4.0.0",
        "aiofiles>=23.2.1",
        "markdown>=3.5.1,<4.0.0",
        "pygments>=2.16.1,<3.0.0",
        "qrcode>=7.4,<9.0",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development",
        "Topic :: Text Processing",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Environment :: Web Environment",
    ],
    keywords="claude claude-code ai conversation control console web local-first cocoview",
    project_urls={
        "Bug Reports": "https://github.com/gdagitrep/claude-code-viewer/issues",
        "Source": "https://github.com/gdagitrep/claude-code-viewer",
        "Documentation": "https://github.com/gdagitrep/claude-code-viewer#readme",
    },
)
