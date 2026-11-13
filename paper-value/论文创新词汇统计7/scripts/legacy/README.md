# Legacy Scripts

These scripts are retained for compatibility or specialized workflows and are not default entrypoints:
- `calculate_impact_v2_lowmem.py`: low-memory impact calculation variant
- `calculate_impact_v2_optimized.py`: optimized experimental impact variant
- `apply_abstract_layer.py`: abstract-layer mapping for RPUs
- `convert_rpu_to_spans.py`: convert RPUs to token-level spans
- `inference_research_structure.py`: research-structure inference utility
- `inspect_opinion_meta.py`: inspect LMDB opinion metadata quality
- `mine_phrases.py`: phrase mining utility
- `normalize_cores.py`: core-term normalization utility
- `rpu_full_extraction.py`: full RPU extraction (T5 variant)
- `rpu_full_extraction_deberta.py`: full RPU extraction (DeBERTa variant)
- `rpu_validator.py`: RPU rule validator
- `supplement_paper_metadata.py`: supplement paper metadata into DB

Default recommendation:
- `scripts/pipeline/calculate_impact_v2.py`

Root compatibility launchers have been removed; use canonical paths under `scripts/` directly.
