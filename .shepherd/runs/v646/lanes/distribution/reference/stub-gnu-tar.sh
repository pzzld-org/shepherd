#!/bin/bash
for a in "$@"; do case "$a" in
  --uid|--uid=*|--gid|--gid=*|--uname|--uname=*|--gname|--gname=*)
    echo "tar: unrecognized option '$a'" >&2; exit 2;;
esac; done
exec /usr/bin/tar "$@"
