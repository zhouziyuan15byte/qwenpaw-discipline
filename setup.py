from setuptools import setup, find_packages

setup(
    name="qwenpaw-discipline",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["qwenpaw"],
    description="Discipline enforcement, context injection, and recovery cards for QwenPaw agents",
)
