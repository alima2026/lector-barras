CREATE TABLE IF NOT EXISTS stock_imports (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_by TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS stock_items (
    id BIGSERIAL PRIMARY KEY,
    sku TEXT NOT NULL,
    description TEXT,
    brand TEXT,
    source_location TEXT,
    nodum_quantity NUMERIC(14, 3) NOT NULL DEFAULT 0,
    current_quantity NUMERIC(14, 3) NOT NULL DEFAULT 0,
    last_import_id BIGINT REFERENCES stock_imports(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sku)
);

CREATE TABLE IF NOT EXISTS sales_imports (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_by TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sales (
    id BIGSERIAL PRIMARY KEY,
    sale_date DATE,
    sku TEXT NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL DEFAULT 0,
    customer TEXT,
    document_number TEXT,
    source_import_id BIGINT REFERENCES sales_imports(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pallets (
    id BIGSERIAL PRIMARY KEY,
    pallet_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS warehouse_movements (
    id BIGSERIAL PRIMARY KEY,
    movement_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    movement_type TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL DEFAULT 0,
    from_location TEXT,
    to_location TEXT,
    pallet_code TEXT REFERENCES pallets(pallet_code),
    performed_by TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    file_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    table_name TEXT,
    record_id TEXT,
    user_name TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_stock_items_sku ON stock_items(sku);
CREATE INDEX IF NOT EXISTS idx_sales_sku ON sales(sku);
CREATE INDEX IF NOT EXISTS idx_movements_sku ON warehouse_movements(sku);
CREATE INDEX IF NOT EXISTS idx_movements_pallet ON warehouse_movements(pallet_code);
CREATE INDEX IF NOT EXISTS idx_audit_event_at ON audit_log(event_at);

