# wled-studio

Tooling for building **verifiable custom WLED firmware**: reproduce a vendor's published WLED build
byte for byte, then add your own effects on top, and prove that nothing else changed before
anything is flashed.

**Status: early work in progress. Nothing here is ready for use yet.**

This repository contains no WLED source code. The build fetches WLED and its usermods from their
upstream repositories at pinned versions.
