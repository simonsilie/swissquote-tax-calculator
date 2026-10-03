from collections import deque
from decimal import Decimal, ROUND_HALF_UP

import polars as pl


# Precision for share quantities (8 decimal places = 0.00000001 shares)
QUANTITY_PRECISION = Decimal("0.00000001")
# Precision for EUR amounts (cents)
AMOUNT_PRECISION = Decimal("0.01")
QUANTITY_ZERO = Decimal("0")


def _to_decimal(value: float | int | str | None, precision: Decimal = QUANTITY_PRECISION) -> Decimal:
    """Safely convert a value to Decimal, treating None as 0.

    Converts via ``str`` first so that binary floating-point artifacts
    (e.g. 0.1 as 0.1000000000000000055511151231257827) are avoided.
    """
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(precision, rounding=ROUND_HALF_UP)


def _round_decimal(value: Decimal, precision: Decimal = QUANTITY_PRECISION) -> Decimal:
    """Round to the given precision."""
    return value.quantize(precision, rounding=ROUND_HALF_UP)


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

    Uses Decimal for precise financial arithmetic to avoid floating-point errors.

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
    lots_by_isin: dict[str, deque[dict[str, Decimal]]] = {}
    results: list[dict[str, object]] = []

    for transaction in transactions:
        isin = str(transaction[isin_col])
        quantity = _to_decimal(transaction[quantity_col])
        transaction_type = str(transaction[type_col])
        if quantity <= QUANTITY_ZERO:
            raise ValueError(f"Ungültige Anzahl für {isin}: {quantity}")

        if transaction_type in purchase_types:
            cost_eur = _to_decimal(transaction[eur_col], AMOUNT_PRECISION).copy_negate()
            lots_by_isin.setdefault(isin, deque()).append(
                {"quantity": quantity, "cost_eur": cost_eur}
            )
            continue

        remaining_quantity = quantity
        acquisition_cost_eur = Decimal("0")
        lots = lots_by_isin.get(isin, deque())
        while remaining_quantity > QUANTITY_ZERO and lots:
            lot = lots[0]
            matched_quantity = min(remaining_quantity, lot["quantity"])
            # cost_eur is total cost for the lot; allocate proportionally
            acquisition_cost_eur += lot["cost_eur"] * (matched_quantity / lot["quantity"])
            lot["quantity"] = _round_decimal(lot["quantity"] - matched_quantity)
            remaining_quantity = _round_decimal(remaining_quantity - matched_quantity)
            if lot["quantity"] <= QUANTITY_ZERO:
                lots.popleft()

        if remaining_quantity > QUANTITY_ZERO:
            raise ValueError(
                f"Für Verkauf von {isin} fehlen {remaining_quantity:.8f} Stück im FIFO-Bestand. "
                "Ergänzen Sie Käufe aus Vorjahren in der CSV."
            )

        proceeds_eur = _to_decimal(transaction[eur_col], AMOUNT_PRECISION)
        acquisition_cost_eur = _round_decimal(acquisition_cost_eur, AMOUNT_PRECISION)
        results.append(
            {
                date_col: transaction[date_col],
                isin_col: isin,
                quantity_col: float(quantity),
                "Verkaufserloes_EUR": float(proceeds_eur),
                "Anschaffungskosten_EUR": float(acquisition_cost_eur),
                "Gewinn_Verlust_EUR": float(_round_decimal(proceeds_eur - acquisition_cost_eur, AMOUNT_PRECISION)),
            }
        )

    return pl.DataFrame(results) if results else pl.DataFrame(schema=result_schema)
