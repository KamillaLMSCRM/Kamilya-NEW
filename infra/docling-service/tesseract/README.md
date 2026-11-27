# Tesseract security backport for Debian Bookworm

The Docling image installs the CLI and shared library together as
`5.3.0-2+kamilya2`. The build uses the verified Debian 5.3.0-2 source
archives, its package rules and the stock man pages. The language data
and the Docling configuration come from the runtime image.

| Upstream advisory | Backported commits |
| --- | --- |
| GHSA-7wf8-58wx-cg2r | `023f16ea0318`, `1490fe89b1d1` |
| GHSA-2h39-p3c8-3vp6 | `88f99fe5b495` |
| GHSA-fhxm-qh9p-wc39 | `6d67d0fd3c07`, plus fixed-pitch progress guard `afdc743a8441` |
| GHSA-xwwv-9h8h-xx8h (raster input, layout, word length and OSD) | `d663db0d2617`, `ad5a1813d4f3`, `3851f4178551`, `9d6a2471b4f9`, `1c6d2d29b2af`, `12538c836b0b`, `a7240347c4b0`, `da95ef0a5d61` |
| GHSA-75cw-g97f-pg6w | `b26ceb54baf0` |

Docling sends fresh PNGs to the CLI, uses packaged OSD for orientation, and
requests TSV for the configured LSTM languages. Direct TIFF handling, UNLV
output, custom zone files, untrusted model loading and legacy word recognition
are outside this backport's acceptance scope. The patch also excludes 5.5.5
layout changes and the abbreviation defect introduced in 5.5.3.

Check both installed Debian package versions with `dpkg-query`. Tesseract
continues to print the upstream version `5.3.0`. Before replacing the package,
compare authenticated Docling output on the same image-only PDFs for column
order, table cells, orientation and text in Russian, Kazakh and English.
Retire this overlay once a Debian package with equivalent fixes has passed
the same comparison.
