# Grand Brasil - BI Estoque

## Project Overview
Business Intelligence dashboard for used car inventory management. Reads stock data from DealerUp Excel/CSV exports, analyzes aging, recommends price reductions, and scores B2B wholesale candidates.

## Tech Stack
- **Language:** Python 3.12
- **Dashboard:** Streamlit
- **Data Processing:** Pandas, Pydantic v2
- **Charts:** Plotly
- **Config:** YAML (business rules) + .env (secrets)
- **Testing:** pytest

## Data Source
- **Platform:** DealerUp (app.dugestao.com.br)
- **Format:** CSV/Excel exports (semicolon-delimited, Brazilian formats)
- **FIPE data:** Will be included in DealerUp export via CODIGO FIPE column (no external API needed)

## Project Structure
```
Coding/
  CLAUDE.md               # This file
  config.yaml             # Business rules: aging thresholds, pricing rules, B2B weights
  requirements.txt        # Python dependencies
  run.py                  # Entry point: python run.py -> launches Streamlit
  grand_brasil/           # Main package
    config.py             # Loads config.yaml + .env
    models/               # Pydantic data models (Vehicle, AgingResult, etc.)
    ingestion/            # Strategy pattern: CSV/Excel reader + field mapping
    analysis/             # Business logic: aging, pricing, b2b_scoring, inventory_summary
    dashboard/            # Streamlit UI: app.py, pages/, components/, styles/
    utils/                # currency.py, date_utils.py, validators.py
  tests/                  # pytest suite (61 tests)
```

## DealerUp Column Mapping
Key fields: `MARCA` -> brand, `MODELO` -> model, `A/M` -> year_model (second value),
`D.E` -> days_in_stock, `VL VENDA` -> asking_price, `VL CUSTO` -> purchase_cost,
`CUSTO AJUSTADO` = Custo + Despesas - Bonus, `SIT` -> status.
`FAMILIA` and `COR INTERNA` are skipped (redundant/irrelevant).

## Development Guidelines

### Code Style
- Follow PEP 8 conventions
- Use type hints for all function signatures
- Prefer Pydantic models for data schemas
- Keep business logic in `analysis/`, separate from dashboard UI

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Dashboard labels: Portuguese (PT-BR)

### Project Conventions
- All business thresholds go in `config.yaml` (not hardcoded)
- Secrets go in `.env` (gitignored)
- Ingestion uses Strategy pattern (base.py ABC -> csv_ingestion.py, etc.)
- Vehicle model is the shared data contract across all modules
- Brazilian formats: dates "dd/mm/yyyy", currency "R$ 85.000,00", CSV delimiter ";"

### Testing
- Tests in `tests/` mirroring source structure
- Run: `py -m pytest tests/ -v`
- Fixtures in `tests/fixtures/` and `tests/conftest.py`

### Git
- Commit messages should be concise and describe the "why"
- Branch naming: `feature/`, `fix/`, `refactor/` prefixes
