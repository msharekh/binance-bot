"""Commission accounting from exchange fills; never assume missing fees are zero."""
from decimal import Decimal


def order_commissions(client, order, rules):
    fills = order.get("fills") or []
    complete = bool(fills) and all(
        "commission" in f and "commissionAsset" in f for f in fills
    ) and sum((Decimal(f["qty"]) for f in fills), Decimal(0)) == Decimal(order["executedQty"])
    amounts = {}
    total = Decimal(0)
    base_fee = Decimal(0)
    base_value = Decimal(0)
    converted = False
    rates = {}
    for fill in fills:
        if "commission" not in fill or "commissionAsset" not in fill:
            continue
        asset = fill["commissionAsset"]
        fee = Decimal(fill["commission"])
        amounts[asset] = amounts.get(asset, Decimal(0)) + fee
        if not fee:
            continue
        if asset == rules["quote_asset"]:
            total += fee
        elif asset == rules["base_asset"]:
            base_fee += fee
            value = fee * Decimal(fill["price"])
            base_value += value
            total += value
        else:
            converted = True
            try:
                if asset not in rates:
                    rate = Decimal(client.get_symbol_ticker(
                        symbol=asset + rules["quote_asset"]
                    )["price"])
                    if not rate.is_finite() or rate <= 0:
                        raise ValueError("Invalid commission conversion price")
                    rates[asset] = rate
                total += fee * rates[asset]
            except Exception:
                # An auxiliary price lookup must not discard an executed order.
                complete = False
    return {
        "commissions": {a: str(v) for a, v in amounts.items()},
        "commission_quote": str(total) if complete else None,
        "commission_status": "missing" if not complete else "converted_estimate" if converted else "actual",
        "commission_conversion_rates": {a: str(v) for a, v in rates.items()},
        "base_commission_quantity": str(base_fee),
        "base_commission_quote": str(base_value),
    }


def entry_cost(quote_spent, fees, existing=None):
    """Base fees reduce inventory; do not also add them to its cash cost."""
    previous = (existing or {}).get("cost_basis_quote", "0" if not existing else None)
    if fees["commission_quote"] is None or previous is None:
        return None
    return str(Decimal(previous) + quote_spent + Decimal(fees["commission_quote"])
               - Decimal(fees["base_commission_quote"]))


def realized_profit(position, executed, proceeds, fees):
    tracked = Decimal(position["quantity"])
    removed = executed + Decimal(fees["base_commission_quantity"])
    cost = position.get("cost_basis_quote")
    status = "missing"
    net = None
    if cost is not None and fees["commission_quote"] is not None and removed <= tracked:
        allocated = Decimal(cost) * removed / tracked
        net = proceeds - allocated - Decimal(fees["commission_quote"]) + Decimal(fees["base_commission_quote"])
        status = "converted_estimate" if "converted_estimate" in (
            position.get("cost_basis_status"), fees["commission_status"]
        ) else "actual"
    return {"net_pnl_usdt": str(net) if net is not None else None,
            "pnl_status": status}, max(Decimal(0), tracked - removed)
