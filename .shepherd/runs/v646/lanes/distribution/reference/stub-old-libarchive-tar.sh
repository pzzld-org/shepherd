#!/bin/bash
for a in "$@"; do case "$a" in
  --owner|--owner=*) echo "tar: Option --owner=0 is not supported" >&2; exit 1;;
  --group|--group=*) echo "tar: Option --group=0 is not supported" >&2; exit 1;;
esac; done
exec /usr/bin/tar "$@"
