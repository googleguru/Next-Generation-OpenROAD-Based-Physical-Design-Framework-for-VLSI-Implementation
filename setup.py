from setuptools import setup, find_packages

setup(
    name="pdflow",
    version="1.0.0",
    description="Next-Generation Physical Design Framework for VLSI Implementation",
    author="R.Pavithra Guru",
    packages=find_packages(include=["src", "src.*"]),
    python_requires=">=3.10",
    install_requires=[
        "jinja2>=3.1",
        "pyyaml>=6.0",
        "matplotlib>=3.7",
        "pandas>=2.0",
        "numpy>=1.24",
        "rich>=13.0",
    ],
    extras_require={
        "bayes": ["scikit-learn>=1.3"],
        "parquet": ["pyarrow>=12.0"],
    },
    entry_points={
        "console_scripts": [
            "pdflow=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
    ],
)
