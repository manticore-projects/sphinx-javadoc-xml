# Changelog

## 0.2.0 (2025-xx-xx)

- Full support for interfaces as top-level type definitions
- Type parameters with bounds (`<T extends Expression>`)
- Bounded wildcards (`? extends X`, `? super Y`)
- Exception declarations (`throws`)
- Enum constant comments, tags, and annotations
- Cross-linking to OpenJDK Javadoc for standard library types
- Internal cross-references between defined types
- New `javadoc-package` directive for package summaries
- New `:jdk-url:` option to configure JDK Javadoc base URL
- New `javadoc_jdk_url` config value in `conf.py`
- Proper PyPI packaging with classifiers and metadata
- Interface sections styled with green header

## 0.1.0 (2025-xx-xx)

- Initial release
- Parse XML doclet output into structured data model
- `javadoc-api` and `javadoc-class` directives
- JavaDoc-inspired CSS with summary tables and detail blocks
- `:public-only:` and `:package:` filter options
- Package name stripping from type references
