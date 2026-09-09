# CLAUDE.md

## Project Context

Rules for Claude Code in this repository: swisstopo Rapid Mapping Processor.

Users are geospatial specialists, not professional programmers. 

The goal is to preserve the existing scientific and operational logic while improving maintainability, transparency and automation.

Whenever uncertainty exists, preserve existing functionality and output

Maintainability and readability take priority over elegance.

## Core principle

Simple code, few modules, functions instead of classes. 

A domain expert with basic Python knowledge must still be able to understand, modify, and trust the workflow.

## Architecture

```
rapidmapping_processor.py   main workflow, CLI, orchestration
configuration.py            STAC IDs, INT/PROD endpoints, product definitions, COG settings
utilities/                  only for clearly reusable technical functions
```

- No new classes without a strong technical reason. Existing classes stay; do not refactor them away.
- No new `.py` module unless the function does not reasonably fit in `rapidmapping_processor.py`, `configuration.py`, or an existing utility. Briefly justify any new module before creating it.
- No new dependencies without first checking whether the standard library or an existing module (`rasterio`, GDAL) already covers it.
- Avoid: design patterns, factories, dependency injection, ORM, microservices, unnecessary async/threading, abstract base classes.

## Critical domain logic (do not change without reason)

- **INT/PROD**: INT stays the default. Environment URLs are defined centrally in `configuration.py`, never hardcoded. Never make PROD the default by accident.
- **STAC naming**: item ID `ram-YYYY-MM-DDthhmmsscc`, asset suffix preserved (e.g. `-ebn-photo.jpg`). STAC IDs are an external interface; do not change them as part of an unrelated refactor.
- **DMC4**: bands 1-4 = R/G/B/NIR; RGB = 1,2,3; NRG = 4,1,2. Workflow: strips → RGB/NRG → VRT mosaic → COG → thumbnail → STAC. Do not introduce an extra processing layer.
- **Geodata**: never silently change CRS, EPSG, geotransform, pixel size, band data, or nodata. EPSG:2056 (LV95) applies to DMC4 input even when the file has no CRS.
- **COG**: use `rasterio.shutil.copy(..., driver="COG")` instead of `gdal_translate`, for PyInstaller compatibility.
- **Timestamps**: never replace a missing acquisition timestamp with the current date.
- **Credentials**: never commit, log, or include in error messages. Treat accidental exposure as a security incident, not just something to delete from the working tree.

## Errors and logging

Error messages must be understandable to non-programmers: what happened, why, what to do. For batch processing, clearly distinguish SUCCESS / WARNING / ERROR.

## Process for every change

1. Read the existing code before changing anything.
2. Look for the smallest solution: does changing one existing function suffice?
3. Add a new module only if needed, with a brief justification.
4. No incidental refactoring, no unnecessary renaming.
5. Review `git diff` before committing: STAC names, URLs, CRS, defaults, credentials, unnecessary files.
6. Report briefly at the end: Changed / Tested / Risks.

## Decision priority

1. Correct output 2. Data integrity 3. Operational reliability 4. Maintainability 5. Simplicity 6. Performance 7. Code elegance

**Golden rule:** before adding any class, module, or dependency, ask "Is this really necessary?" If not, don't create it.
