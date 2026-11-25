#!/bin/sh
# Lanzador de Nexo
DIR="$(dirname "$(readlink -f "$0")")"
cd "$DIR" && exec python3 -m nexo "$@"
