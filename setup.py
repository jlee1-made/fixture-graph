#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name="fixture-diagram",
    url="https://gitlab.com/jlee1-made/fixture-diagram",
    description="Draw graphs showing the test fixtures you've made",
    package_dir={"": "src"},
    packages=find_packages("src"),
    platforms=["any"],
    zip_safe=True,
)
