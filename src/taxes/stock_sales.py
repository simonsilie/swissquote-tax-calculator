from collections import deque

import polars as pl


def calculate_realized_stock_results(
    dataframe: pl.DataFrame,
    purchase_types: list[str],
    sale_types: list[str],
    date_col: str,
    type_col: str,
    isin_col: str,
    quantity_col: str,
    eur_col: str,
) -> pl.DataFrame:
    """Calculate realized stock gains and losses using FIFO cost-basis matching.

    Raises:
        ValueError: If required columns are missing, data is incomplete, or
            the FIFO lot inventory is insufficient for a sale.
    """
    result_schema = {
        date_col: pl.Datetime,
        isin_col: pl.String,
        quantity_col: pl.Float64,
        "Verkaufserloes_EUR": pl.Float64,
        "Anschaffungskosten_EUR": pl.Float64,
        "Gewinn_Verlust_EUR": pl.Float64,
    }
    security_transactions = dataframe.filter(pl.col(type_col).is_in(purchase_types + sale_types))
    if security_transactions.is_empty():
        return pl.DataFrame(schema=result_schema)

    required_cols = [isin_col, quantity_col]
    missing = [column for column in required_cols if column not in dataframe.columns]
    if missing:
        raise ValueError(f"Fehlende Spalten für die Aktienverkäufe: {missing}")

    if security_transactions[isin_col].is_null().any() or security_transactions[quantity_col].is_null().any():
        raise ValueError("Aktienkäufe und -verkäufe benötigen ISIN und Anzahl")

    transactions = security_transactions.sort(date_col).to_dicts()
    lots_by_isin: dict[str, deque[dict[str, float]]] = {}
    results: list[dict[str, object]] = []

    for transaction in transactions:
        isin = str(transaction[isin_col])
        quantity = float(transaction[quantity_col])
        transaction_type = str(transaction[type_col])
        if quantity <= 0:
            raise ValueError(f"Ungültige Anzahl für {isin}: {quantity}")

        if transaction_type in purchase_types:
            lots_by_isin.setdefault(isin, deque()).append(
                {"quantity": quantity, "cost_eur": -float(transaction[eur_col])}
            )
            continue

        remaining_quantity = quantity
        acquisition_cost_eur = 0.0
        lots = lots_by_isin.get(isin, deque())
        while remaining_quantity > 1e-9 and lots:
            lot = lots[0]
            matched_quantity = min(remaining_quantity, lot["quantity"])
            acquisition_cost_eur += lot["cost_eur"] * matched_quantity / lot["quantity"]
            lot["quantity"] -= matched_quantity
            remaining_quantity -= matched_quantity
            if lot["quantity"] <= 1e-9:
                lots.popleft()

        if remaining_quantity > 1e-9:
            raise ValueError(
                f"Für Verkauf von {isin} fehlen {remaining_quantity:.8g} Stück im FIFO-Bestand. "
                "Ergänzen Sie Käufe aus Vorjahren in der CSV."
            )

        proceeds_eur = float(transaction[eur_col])
        results.append(
            {
                date_col: transaction[date_col],
                isin_col: isin,
                quantity_col: quantity,
                "Verkaufserloes_EUR": proceeds_eur,
                "Anschaffungskosten_EUR": acquisition_cost_eur,
                "Gewinn_Verlust_EUR": proceeds_eur - acquisition_cost_eur,
            }
        )

    return pl.DataFrame(results) if results else pl.DataFrame(schema=result_schema)
