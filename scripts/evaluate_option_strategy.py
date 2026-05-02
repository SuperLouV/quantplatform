"""Evaluate a simple options strategy from manual contract inputs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_platform.options import AccountProfile, OptionContract, OptionsAssistantService, OptionStrategyRequest, StockOptionContext


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate conservative options strategies without placing trades.")
    parser.add_argument("--strategy", choices=["cash_secured_put", "covered_call"], required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--underlying-price", type=float, required=True)
    parser.add_argument("--option-type", choices=["put", "call"], required=True)
    parser.add_argument("--strike", type=float, required=True)
    parser.add_argument("--expiration", required=True, help="Expiration date, YYYY-MM-DD")
    parser.add_argument("--bid", type=float, required=True)
    parser.add_argument("--ask", type=float, required=True)
    parser.add_argument("--delta", type=float)
    parser.add_argument("--iv", type=float)
    parser.add_argument("--volume", type=int)
    parser.add_argument("--open-interest", type=int)
    parser.add_argument("--equity", type=float, default=5_000)
    parser.add_argument("--cash", type=float, default=5_000)
    parser.add_argument("--max-cash-pct", type=float, default=0.4)
    parser.add_argument("--max-loss-pct", type=float, default=0.5)
    parser.add_argument("--allow-assignment", action="store_true", default=True)
    parser.add_argument("--no-assignment", action="store_false", dest="allow_assignment")
    parser.add_argument("--stock-shares", type=int, default=0)
    parser.add_argument("--stock-cost-basis", type=float)
    parser.add_argument("--support", type=float)
    parser.add_argument("--resistance", type=float)
    parser.add_argument("--earnings-days", type=int)
    parser.add_argument("--market-risk-state")
    parser.add_argument("--with-prompt", action="store_true", help="Also print a DeepSeek-ready prompt.")
    args = parser.parse_args()

    request = OptionStrategyRequest(
        strategy=args.strategy,
        account=AccountProfile(
            equity=args.equity,
            cash=args.cash,
            max_cash_per_trade_pct=args.max_cash_pct,
            max_loss_pct=args.max_loss_pct,
            allow_assignment=args.allow_assignment,
            stock_shares=args.stock_shares,
            stock_cost_basis=args.stock_cost_basis,
        ),
        stock=StockOptionContext(
            symbol=args.symbol.upper(),
            current_price=args.underlying_price,
            as_of=date.fromisoformat(args.as_of),
            support_price=args.support,
            resistance_price=args.resistance,
            earnings_days=args.earnings_days,
            market_risk_state=args.market_risk_state,
        ),
        contract=OptionContract(
            symbol=args.symbol.upper(),
            option_type=args.option_type,
            strike=args.strike,
            expiration=date.fromisoformat(args.expiration),
            bid=args.bid,
            ask=args.ask,
            delta=args.delta,
            implied_volatility=args.iv,
            volume=args.volume,
            open_interest=args.open_interest,
        ),
    )
    service = OptionsAssistantService()
    evaluation = service.evaluate(request)
    print(json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2))
    if args.with_prompt:
        print("\n--- AI PROMPT ---")
        print(service.build_ai_prompt(evaluation))


if __name__ == "__main__":
    main()
