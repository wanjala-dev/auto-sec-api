# Workspace Config Directory

Each organisation has its own subdirectory containing:

- `config.json` – manually curated workspace definition.
- `config.scraped.json` – optional output from the scraping utility for review.
- `assets/` – place to store downloaded logos, brochures, and other static files.

## Notes

- `recipients` (legacy: `children`) are the sponsored individuals imported into the workspace during bootstrap.
- `recipients_category` controls the default category applied to imported recipients.
