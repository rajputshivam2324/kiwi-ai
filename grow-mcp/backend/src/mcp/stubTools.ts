/**
 * Stub MCP-style tools for development when Groww MCP server is not available.
 * All data is placeholder; replace with real MCP once Groww server is connected.
 *
 * Tool categories:
 *  1. Instruments       — search, download, details
 *  2. Market Data       — quote, LTP, OHLC, candles, top movers
 *  3. Portfolio         — holdings
 *  4. Positions         — intraday open positions
 *  5. Orders            — place, modify, cancel, book, history, status
 *  6. Margin            — available margin, required margin
 *  7. Fundamentals      — revenue, profit, valuation ratios
 *  8. Technical Analysis— SMA, EMA, MACD, RSI, Bollinger Bands, ADX, Stochastic, Williams %R
 */

export interface StubToolDef {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, { type: string; description?: string; enum?: string[] }>;
    required?: string[];
  };
}

const stubResponse = (tool: string, message: string, data?: object) =>
  JSON.stringify({
    source: "stub",
    tool,
    message,
    data: data ?? {},
    disclaimer: "This is stub data. Connect Groww MCP server for real data.",
  });

// ─── Shared param fragments ────────────────────────────────────────────────
const symbolParam = { type: "string", description: "Stock/F&O symbol (e.g. RELIANCE, NIFTY)" };
const exchangeParam = { type: "string", description: "Exchange: NSE or BSE", enum: ["NSE", "BSE"] };
const segmentParam = {
  type: "string",
  description: "Segment: CASH or FNO",
  enum: ["CASH", "FNO"],
};
const orderTypeParam = {
  type: "string",
  description: "Order type",
  enum: ["MARKET", "LIMIT", "SL", "SL-M"],
};
const productParam = {
  type: "string",
  description: "Product: CNC (delivery), MIS (intraday), NRML (F&O carry-forward)",
  enum: ["CNC", "MIS", "NRML"],
};
const sideParam = {
  type: "string",
  description: "Transaction type",
  enum: ["BUY", "SELL"],
};
const periodParam = {
  type: "number",
  description: "Lookback period (default 14 for RSI/ADX, 20 for Bollinger, etc.)",
};
const startTimeParam = {
  type: "string",
  description: "Start datetime: YYYY-MM-DD HH:MM:SS",
};
const endTimeParam = {
  type: "string",
  description: "End datetime: YYYY-MM-DD HH:MM:SS",
};
const candleIntervalParam = {
  type: "string",
  description: "Candle interval",
  enum: ["1m", "5m", "10m", "15m", "30m", "1h", "1d"],
};

// ─── Tool Definitions ──────────────────────────────────────────────────────
export const STUB_TOOL_DEFINITIONS: StubToolDef[] = [
  // ── 1. INSTRUMENTS ──────────────────────────────────────────────────────
  {
    name: "download_instruments",
    description:
      "Download or refresh the complete list of tradeable instruments from NSE/BSE. " +
      "Call this once per session or when searching for new symbols.",
    inputSchema: {
      type: "object",
      properties: {
        exchange: exchangeParam,
        segment: segmentParam,
      },
    },
  },
  {
    name: "search_instruments",
    description:
      "Search tradeable instruments by name, trading symbol, Groww symbol, or segment/type. " +
      "Use to resolve user-entered names to exact symbols before placing orders.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Free-text search (e.g. 'Reliance', 'NIFTY CE')" },
        exchange: exchangeParam,
        segment: segmentParam,
        instrument_type: {
          type: "string",
          description: "Option type for F&O: CE or PE",
          enum: ["CE", "PE"],
        },
        limit: { type: "number", description: "Max results to return (default 10)" },
      },
      required: ["query"],
    },
  },
  {
    name: "get_instrument_details",
    description:
      "Get detailed metadata for a specific instrument: lot size, tick size, ISIN, expiry (for F&O), strike price, etc.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
      },
      required: ["symbol"],
    },
  },

  // ── 2. MARKET DATA ───────────────────────────────────────────────────────
  {
    name: "get_market_quote",
    description:
      "Get current price, day high/low, volume, 52-week high/low, and basic technical levels for a symbol.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
      },
      required: ["symbol"],
    },
  },
  {
    name: "get_ltp",
    description: "Get Last Traded Price (LTP) only — lightweight alternative to full market quote.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
      },
      required: ["symbol"],
    },
  },
  {
    name: "get_ohlc",
    description:
      "Get Open, High, Low, Close for the current or most recent trading session for a symbol.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
      },
      required: ["symbol"],
    },
  },
  {
    name: "get_historical_candles",
    description:
      "Fetch historical OHLCV candle data for a symbol over a date/time range. " +
      "Use for charting, backtesting, or feeding into technical analysis tools.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "get_top_gainers",
    description: "Get top gaining stocks for NSE or BSE for the current trading session.",
    inputSchema: {
      type: "object",
      properties: {
        exchange: exchangeParam,
        limit: { type: "number", description: "Number of results (default 10)" },
      },
    },
  },
  {
    name: "get_top_losers",
    description: "Get top losing stocks for NSE or BSE for the current trading session.",
    inputSchema: {
      type: "object",
      properties: {
        exchange: exchangeParam,
        limit: { type: "number", description: "Number of results (default 10)" },
      },
    },
  },
  {
    name: "get_most_active",
    description:
      "Get most actively traded stocks by volume for NSE or BSE for the current session.",
    inputSchema: {
      type: "object",
      properties: {
        exchange: exchangeParam,
        limit: { type: "number", description: "Number of results (default 10)" },
      },
    },
  },

  // ── 3. PORTFOLIO ─────────────────────────────────────────────────────────
  {
    name: "get_portfolio_holdings",
    description:
      "Get user's current portfolio holdings (delivery/CNC positions) including symbol, " +
      "quantity, average buy price, current value, and P&L. Requires user context.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },

  // ── 4. POSITIONS ─────────────────────────────────────────────────────────
  {
    name: "get_positions",
    description:
      "Get user's open intraday positions (MIS/NRML). Includes unrealised P&L, quantity, " +
      "average price for currently open trades. Requires user context.",
    inputSchema: {
      type: "object",
      properties: {
        segment: segmentParam,
      },
    },
  },

  // ── 5. ORDERS ────────────────────────────────────────────────────────────
  {
    name: "place_order",
    description:
      "Place a buy or sell order. MUST only be called after explicit user confirmation. " +
      "Never call without the user saying yes to the exact order details.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        side: sideParam,
        quantity: { type: "number", description: "Number of shares / lots" },
        order_type: orderTypeParam,
        product: productParam,
        price: { type: "number", description: "Required for LIMIT and SL orders" },
        trigger_price: { type: "number", description: "Required for SL and SL-M orders" },
        disclosed_quantity: {
          type: "number",
          description: "Disclosed quantity for iceberg orders (optional)",
        },
        validity: {
          type: "string",
          description: "Order validity",
          enum: ["DAY", "IOC"],
        },
      },
      required: ["symbol", "exchange", "side", "quantity", "order_type", "product"],
    },
  },
  {
    name: "modify_order",
    description:
      "Modify an existing pending order (price, quantity, order type, trigger price). " +
      "Requires explicit user confirmation before calling.",
    inputSchema: {
      type: "object",
      properties: {
        order_id: { type: "string", description: "Unique order ID to modify" },
        quantity: { type: "number", description: "New quantity (optional)" },
        price: { type: "number", description: "New limit price (optional)" },
        trigger_price: { type: "number", description: "New trigger price for SL orders (optional)" },
        order_type: orderTypeParam,
      },
      required: ["order_id"],
    },
  },
  {
    name: "cancel_order",
    description:
      "Cancel a pending order by order ID. " +
      "MUST only be called after explicit user confirmation.",
    inputSchema: {
      type: "object",
      properties: {
        order_id: { type: "string", description: "Unique order ID to cancel" },
      },
      required: ["order_id"],
    },
  },
  {
    name: "get_order_book",
    description:
      "Get the user's current order book — all orders placed in the current trading session " +
      "with their status (PENDING, EXECUTED, CANCELLED, REJECTED).",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "get_order_history",
    description:
      "Get historical order history for a given date range. Useful for reviewing past trades.",
    inputSchema: {
      type: "object",
      properties: {
        from_date: { type: "string", description: "Start date: YYYY-MM-DD" },
        to_date: { type: "string", description: "End date: YYYY-MM-DD" },
      },
      required: ["from_date", "to_date"],
    },
  },
  {
    name: "get_order_status",
    description: "Get the current status and details of a specific order by its order ID.",
    inputSchema: {
      type: "object",
      properties: {
        order_id: { type: "string", description: "Unique order ID" },
      },
      required: ["order_id"],
    },
  },
  {
    name: "get_trade_book",
    description:
      "Get the user's executed trades (fills) for the current trading session, " +
      "including fill price, quantity, and time.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },

  // ── 6. MARGIN ────────────────────────────────────────────────────────────
  {
    name: "get_available_margin",
    description:
      "Get user's available trading margins: equity, F&O, commodity, and cash balances. " +
      "Use before placing orders to check if user has sufficient funds.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "get_required_margin",
    description:
      "Calculate margin required to place a specific order before actually placing it. " +
      "Use this to inform users of required funds.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        side: sideParam,
        quantity: { type: "number", description: "Number of shares / lots" },
        order_type: orderTypeParam,
        product: productParam,
        price: { type: "number", description: "Limit price (optional, used for LIMIT orders)" },
      },
      required: ["symbol", "exchange", "side", "quantity", "order_type", "product"],
    },
  },

  // ── 7. FUNDAMENTALS ──────────────────────────────────────────────────────
  {
    name: "get_stock_fundamentals",
    description:
      "Get fundamental data for a stock: revenue, profit, margins, ROE, ROCE, EPS, P/E, " +
      "P/B, debt-to-equity, free cash flow. Use for financial health and valuation analysis.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
      },
      required: ["symbol"],
    },
  },

  // ── 8. TECHNICAL ANALYSIS ────────────────────────────────────────────────
  {
    name: "calculate_sma",
    description:
      "Calculate Simple Moving Average (SMA) for a symbol over a given period and time range. " +
      "Common periods: 20, 50, 100, 200.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: periodParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "period", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_ema",
    description:
      "Calculate Exponential Moving Average (EMA) for a symbol. " +
      "Common periods: 9, 12, 20, 26, 50, 200.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: periodParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "period", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_macd",
    description:
      "Calculate MACD (Moving Average Convergence Divergence) line, signal line, and histogram. " +
      "Default fast=12, slow=26, signal=9.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        fast_period: { type: "number", description: "Fast EMA period (default 12)" },
        slow_period: { type: "number", description: "Slow EMA period (default 26)" },
        signal_period: { type: "number", description: "Signal EMA period (default 9)" },
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_rsi",
    description:
      "Calculate Relative Strength Index (RSI) to measure momentum. " +
      "Standard period is 14. Above 70 = overbought, below 30 = oversold.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: periodParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_bollinger_bands",
    description:
      "Calculate Bollinger Bands (upper, middle, lower) for a symbol. " +
      "Standard: period=20, std_dev=2. Used to assess price volatility.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: { type: "number", description: "SMA period (default 20)" },
        std_dev: { type: "number", description: "Standard deviation multiplier (default 2)" },
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_adx",
    description:
      "Calculate Average Directional Index (ADX) to measure trend strength (not direction). " +
      "ADX > 25 indicates a strong trend. Also returns +DI and -DI.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: periodParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_stochastic",
    description:
      "Calculate Stochastic Oscillator (%K and %D lines). " +
      "Identifies overbought (>80) and oversold (<20) conditions.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        k_period: { type: "number", description: "%K period (default 14)" },
        d_period: { type: "number", description: "%D smoothing period (default 3)" },
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
  {
    name: "calculate_williams_r",
    description:
      "Calculate Williams %R momentum oscillator. " +
      "Ranges from -100 to 0; above -20 = overbought, below -80 = oversold.",
    inputSchema: {
      type: "object",
      properties: {
        symbol: symbolParam,
        exchange: exchangeParam,
        segment: segmentParam,
        period: periodParam,
        start_time: startTimeParam,
        end_time: endTimeParam,
        interval: candleIntervalParam,
      },
      required: ["symbol", "start_time", "end_time", "interval"],
    },
  },
];

// ─── Stub Executor ─────────────────────────────────────────────────────────
export async function executeStubTool(
  name: string,
  args: Record<string, unknown>
): Promise<{ content: Array<{ type: "text"; text: string }>; isError?: boolean }> {
  const sym = (args.symbol as string) || "UNKNOWN";
  const ok = (data?: object) => ({
    content: [{ type: "text" as const, text: stubResponse(name, `${name} stub for ${sym}.`, data) }],
  });

  switch (name) {
    // ── Instruments ──────────────────────────────────────────────────────
    case "download_instruments":
      return ok({ status: "stub", instruments_count: 0 });
    case "search_instruments":
      return ok({ results: [] });
    case "get_instrument_details":
      return ok({
        trading_symbol: sym,
        isin: null,
        lot_size: null,
        tick_size: null,
        expiry: null,
        strike: null,
      });

    // ── Market Data ───────────────────────────────────────────────────────
    case "get_market_quote":
      return ok({ last_price: null, day_high: null, day_low: null, volume: null, week52_high: null, week52_low: null });
    case "get_ltp":
      return ok({ ltp: null });
    case "get_ohlc":
      return ok({ open: null, high: null, low: null, close: null });
    case "get_historical_candles":
      return ok({ candles: [] });
    case "get_top_gainers":
      return ok({ gainers: [] });
    case "get_top_losers":
      return ok({ losers: [] });
    case "get_most_active":
      return ok({ stocks: [] });

    // ── Portfolio ─────────────────────────────────────────────────────────
    case "get_portfolio_holdings":
      return ok({ holdings: [] });

    // ── Positions ─────────────────────────────────────────────────────────
    case "get_positions":
      return ok({ positions: [] });

    // ── Orders ────────────────────────────────────────────────────────────
    case "place_order":
      return {
        content: [{ type: "text", text: stubResponse(name, "Order stubbed — real execution requires Groww MCP.", { order_id: null, status: "stub" }) }],
      };
    case "modify_order":
      return ok({ order_id: args.order_id, status: "stub_modified" });
    case "cancel_order":
      return ok({ order_id: args.order_id, status: "stub_cancelled" });
    case "get_order_book":
      return ok({ orders: [] });
    case "get_order_history":
      return ok({ orders: [] });
    case "get_order_status":
      return ok({ order_id: args.order_id, status: null });
    case "get_trade_book":
      return ok({ trades: [] });

    // ── Margin ────────────────────────────────────────────────────────────
    case "get_available_margin":
      return ok({ equity: 1500000.50, fno: 450000.00, cash: 250000.00 });
    case "get_required_margin":
      return ok({ required_margin: args.quantity ? Number(args.quantity) * 1520.0 : 15200.00, symbol: sym });

    // ── Fundamentals ──────────────────────────────────────────────────────
    case "get_stock_fundamentals":
      return ok({
        revenue_trend: "Consistent YoY growth of ~15%", profit_trend: "Operating margins expanded by 200 bps", margins: "18.5% net profit margin",
        roe: "22.4%", roce: "25.1%", eps: "₹145.20", pe: "24.5", pb: "5.2",
        debt_to_equity: "0.15", free_cash_flow: "₹15,000 Cr",
      });

    // ── Technical Analysis ────────────────────────────────────────────────
    case "calculate_sma":
      return ok({ period: args.period, values: [] });
    case "calculate_ema":
      return ok({ period: args.period, values: [] });
    case "calculate_macd":
      return ok({ macd_line: [], signal_line: [], histogram: [] });
    case "calculate_rsi":
      return ok({ period: args.period, values: [] });
    case "calculate_bollinger_bands":
      return ok({ upper: [], middle: [], lower: [] });
    case "calculate_adx":
      return ok({ adx: [], plus_di: [], minus_di: [] });
    case "calculate_stochastic":
      return ok({ k: [], d: [] });
    case "calculate_williams_r":
      return ok({ period: args.period, values: [] });

    default:
      return {
        content: [{ type: "text", text: `Unknown stub tool: ${name}` }],
        isError: true,
      };
  }
}
