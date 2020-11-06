#!/bin/sh

set -e

exec mypy $(find src/ -name '*.py')
