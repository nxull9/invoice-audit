"""Load invoice data and reconstruct the invoice key.

Money is read as integer cents. Dates are parsed non-destructively so unparseable
values remain reportable. `invoice_id` is not unique — the `line_id` prefix is the
real key, and `build_invoice_units` restores it.
"""

import pandas as pd

MONEY = ['invoice_total_cents', 'unit_price_cents', 'line_total_cents']


def load_invoices(data_root, hospital):
    """One row per invoice row (note: not per invoice — see build_invoice_units)."""
    df = pd.read_csv(f'{data_root}/invoices/{hospital}_invoices.csv', dtype=str)
    df['invoice_total_cents'] = pd.to_numeric(df['invoice_total_cents']).astype('Int64')
    for c in ['invoice_date', 'admission_date', 'discharge_date']:
        df[c + '_raw'] = df[c]
        df[c] = pd.to_datetime(df[c], format='%Y-%m-%d', errors='coerce')
    return df


def load_line_items(data_root, hospital):
    """One row per line item, sorted the way the contracts require them counted.

    Several rules are defined over line items 'in Service Date order, and where two
    line items share a Service Date, in ascending order of line identifier'. We sort
    once here so every later pass inherits that order.
    """
    df = pd.read_csv(f'{data_root}/invoices/{hospital}_line_items.csv', dtype=str)
    for c in ['quantity', 'unit_price_cents', 'line_total_cents']:
        df[c] = pd.to_numeric(df[c]).astype('Int64')
    df['service_date_raw'] = df['service_date']
    df['service_date'] = pd.to_datetime(df['service_date'], format='%Y-%m-%d', errors='coerce')
    df['source_seq'] = df['line_id'].str.split('-').str[1]      # 'H1-L00068-01' -> 'L00068'
    return df.sort_values(['service_date', 'line_id'], na_position='last').reset_index(drop=True)


def build_invoice_units(invoices, line_items):
    """Attach the real invoice key (`source_seq`) to every invoice row.

    Where an identifier is reused, the rows are paired with their line groups in
    ascending order of both invoice date and line sequence. That pairing reproduces
    the stated invoice totals exactly for all five reused identifiers on hospital 1,
    and the label file always describes the *later* of the pair. So we treat the
    earlier invoice as legitimate and flag the later one.
    """
    groups = (line_items.groupby(['invoice_id', 'source_seq'])['line_total_cents']
                        .sum().reset_index().sort_values(['invoice_id', 'source_seq']))
    inv = invoices.sort_values(['invoice_id', 'invoice_date']).copy()

    inv['_rank'] = inv.groupby('invoice_id').cumcount()
    groups['_rank'] = groups.groupby('invoice_id').cumcount()
    merged = inv.merge(groups[['invoice_id', 'source_seq', '_rank']],
                       on=['invoice_id', '_rank'], how='left')
    merged['reuses_id'] = merged['_rank'] > 0
    return merged.drop(columns='_rank')


def load_labels(data_root, hospital='hospital_1'):
    """Ground truth for the development hospital. Categories are `|`-separated."""
    df = pd.read_csv(f'{data_root}/labels/{hospital}_labels.csv', dtype=str)
    df['is_erroneous'] = df['is_erroneous'].astype(int)
    df['expected_total_cents'] = pd.to_numeric(df['expected_total_cents']).astype('Int64')
    df['categories'] = df['error_categories'].fillna('').apply(
        lambda s: [c.strip() for c in s.split('|') if c.strip()])
    return df
