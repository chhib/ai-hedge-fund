# Trading Agent Strategy Overview

## Core Analysis Agents

### 📊 **Fundamentals Analyst**
Evaluates company health through specific financial thresholds. The code checks ROE > 15%, net margin > 20%, operating margin > 15% for profitability; revenue/earnings/book value growth > 10% for growth; current ratio > 1.5 and debt-to-equity < 0.5 for financial health; and P/E < 25, P/B < 3, P/S < 5 for valuation. Each category generates bullish/bearish signals weighted equally.

### 📈 **Technical Analyst**
Combines five technical strategies with weighted confidence scores. Calculates trend signals using EMA crossovers (8/21/55 periods) and ADX for strength; mean reversion using z-scores, Bollinger Bands, and RSI (14/28); momentum from 1/3/6-month returns and volume; volatility regimes using 21-day rolling standard deviation; and statistical arbitrage using Hurst exponent. Weights: trend 25%, mean reversion 20%, momentum 25%, volatility 15%, stat arb 15%.

### 💭 **Sentiment Analyst**
Analyzes market sentiment through two data sources. Processes insider trades with 60% weight (transaction_shares < 0 = bearish, > 0 = bullish) and company calendar events with 40% weight (dividends = bullish, reports = neutral). Calculates weighted bullish vs bearish signals to determine overall sentiment.

### 💰 **Valuation Analyst**
Calculates intrinsic value using four methods. Enhanced DCF (35% weight) with WACC calculation and bear/base/bull scenarios; Owner Earnings (35%) using net income + depreciation - maintenance capex - working capital change; EV/EBITDA (20%) using median historical multiples; Residual Income Model (10%) using book value + present value of excess returns. Signals bullish if weighted gap > 15%, bearish if < -15%.

### ⚠️ **Risk Manager**
Calculates position limits based on volatility and correlation. Computes 60-day historical volatility and annualizes it; builds correlation matrix across all positions; adjusts base position limit (20% of portfolio) by volatility factor (low vol <15% allows up to 25%, high vol >50% caps at 10%) and correlation multiplier (high correlation >0.8 reduces by 30%). Ensures total exposure doesn't exceed available cash.

## Legendary Investor Agents

### 🎩 **Warren Buffett**
Known for value investing with margin of safety. The code calculates owner earnings (net income + depreciation - maintenance capex), requires ROE > 15% and debt/equity < 0.5, checks for consistent earnings growth over 4+ periods, analyzes book value per share CAGR, and uses conservative 3-stage DCF (Stage 1: 5 years at 8% cap, Stage 2: 5 years at 4% cap, Terminal: 2.5%). Requires 30% margin of safety for bullish signal.

### 👴 **Ben Graham**
The father of value investing. Code implements Graham Number = √(22.5 × EPS × BVPS) and net-net analysis (current assets - total liabilities vs market cap). Scores companies on earnings stability (positive EPS consistency), financial strength (current ratio > 2, D/E < 0.5), and dividend track record. Prefers 50% margin of safety using Graham Number.

### 🧠 **Charlie Munger**
Buffett's partner known for mental models. The code heavily weights moat strength (35%) checking ROIC > 15% consistency, management quality (25%) analyzing FCF/NI ratio and insider buy ratio, business predictability (25%) using revenue/margin volatility, and valuation (15%) using normalized FCF yield. Applies correlation adjustment for position sizing and requires quality score > 0.7 for bullish signals.

### 🎯 **Peter Lynch**
Famous for "invest in what you know" and ten-baggers. Code calculates PEG ratio (P/E ÷ annualized EPS growth), scores revenue/EPS CAGR with thresholds at 25%/10%/2%, evaluates debt/equity < 0.5 and operating margin > 20%, analyzes insider buying patterns, and weights growth 30%, valuation 25%, fundamentals 20%, calendar events 15%, insider activity 10%.

### 🔬 **Phil Fisher**
Pioneer of growth investing through scuttlebutt research. The code analyzes revenue/EPS CAGR (20%/10%/3% thresholds), R&D as % of revenue (3-15% optimal range), operating margin consistency using standard deviation, management efficiency via ROE > 20% and debt/equity ratios, and applies P/E < 20 and P/FCF < 20 for valuation with 35% growth weight.

### 💼 **Bill Ackman**
Activist investor seeking operational improvements. Code evaluates business quality through revenue CAGR and operating margins > 15%, identifies activism potential when revenue growth > 15% but margins < 10%, analyzes capital allocation via debt ratios and share buybacks, calculates simple DCF with 6% growth and 15x terminal multiple for doubling potential in 2-3 years.

### 🔮 **Cathie Wood**
ARK Invest founder focused on disruptive innovation. The code scores disruptive potential via revenue growth acceleration and R&D intensity > 15% of revenue, analyzes gross margin expansion trends, checks operating leverage (revenue growing faster than expenses), uses aggressive DCF assumptions (20% growth, 15% discount rate, 25x terminal), with 30% weight on disruption metrics.

### 🔍 **Michael Burry**
"The Big Short" investor known for contrarian deep value. Code screens for FCF yield > 15% (extraordinary), > 12% (very high), or > 8% (respectable), EV/EBIT < 6 for deep value, net cash positions (cash > debt), net insider buying over 12 months as catalyst, and upcoming calendar events (reports/dividends) as additional catalysts.

### 🌍 **Mohnish Pabrai**
Copies great investors with "heads I win, tails I don't lose much" philosophy. The code scores downside protection via net cash position and current ratio > 2, calculates simple FCF yield valuation with 10% threshold for exceptional value, analyzes doubling potential through revenue/FCF growth trends, prefers asset-light businesses (capex < 5% of revenue).

### 📊 **Stanley Druckenmiller**
Macro trader famous for "breaking the Bank of England." Code calculates revenue/EPS annualized CAGR with 8%/4%/1% thresholds, analyzes price momentum (50%/20% return thresholds), evaluates risk via debt/equity < 0.3 and daily return volatility < 1%, performs valuation using P/E, P/FCF, EV/EBIT, EV/EBITDA with sub-15x preference, weights growth/momentum 35%, risk/reward 20%.

### 🚀 **Rakesh Jhunjhunwala**
India's most successful investor. The code requires ROE > 20% with bonus points above 15%, calculates revenue/income/EPS CAGR with 20%/15%/10% thresholds, checks debt ratio < 0.5 and current ratio > 2.0, analyzes share buybacks (negative issuance) and dividend payments, uses DCF with quality-adjusted discount rates (12-18%) and requires 30% margin of safety.

### 🏛️ **Aswath Damodaran**
NYU professor and valuation expert. Code implements CAPM cost of equity (risk-free + β × equity risk premium), analyzes 5-year revenue CAGR with 8%/3% scoring thresholds, performs FCFF DCF with growth fade from high to terminal 2.5% by year 10, checks ROIC > 10% for reinvestment efficiency, calculates margin of safety vs reasonable value (10x-20x FCF multiples).

## Portfolio Management

### 📋 **Portfolio Manager**
Makes final trading decisions based on all agent inputs. The code aggregates signals from all analysts, weights by confidence levels, applies position limits from Risk Manager, determines allowed actions (buy/sell/short/cover/hold) based on cash and margin, generates quantity-specific orders within risk limits. Uses compressed signal format to minimize LLM token usage.

## System Architecture

The system operates as an ensemble where each agent analyzes the same tickers independently, produces signal/confidence/reasoning outputs, and feeds into the Portfolio Manager for final decision aggregation. Risk Manager acts as a safety overlay, preventing excessive concentration or volatility exposure.