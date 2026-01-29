import os
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv
from openai import OpenAI

# Load API key from .env
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not set in environment variables.")

client = OpenAI(api_key=api_key)

def fetch_stock_data(ticker, period="6mo", interval="1d"):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"No data found for {ticker}")

    # Handle multi-index columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df = df[['Close']].copy()
    df.reset_index(inplace=True)
    return df

def generate_signals(df):
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['Signal'] = ""
    valid_idx = df['MA20'].notna()
    df.loc[valid_idx & (df['Close'] > df['MA5']), 'Signal'] = "Buy"
    df.loc[valid_idx & (df['Close'] < df['MA5']), 'Signal'] = "Sell"
    return df

def get_ai_insight(ticker, signal):
    prompt = f"Provide a concise AI insight for {ticker} stock. Current signal: {signal}"
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300
    )
    return response.choices[0].message.content.strip()

def plot_stock_with_insight(df, ticker, insight):
    # Create subplot: chart + AI insight text box
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        specs=[[{"type": "scatter"}],
               [{"type": "table"}]],
        vertical_spacing=0.1
    )

    # Stock price & moving averages
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], mode='lines', name='Close'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['MA5'], mode='lines', name='MA5'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['MA20'], mode='lines', name='MA20'), row=1, col=1)

    # Buy/Sell markers
    buys = df[df['Signal'] == 'Buy']
    sells = df[df['Signal'] == 'Sell']
    fig.add_trace(go.Scatter(x=buys['Date'], y=buys['Close'], mode='markers',
                             marker=dict(color='green', size=10), name='Buy Signal'), row=1, col=1)
    fig.add_trace(go.Scatter(x=sells['Date'], y=sells['Close'], mode='markers',
                             marker=dict(color='red', size=10), name='Sell Signal'), row=1, col=1)

    # AI insight as a table (simpler than text box, easy formatting)
    fig.add_trace(go.Table(
        header=dict(values=[f"AI Insight for {ticker}"], fill_color='lightgrey'),
        cells=dict(values=[[insight]])
    ), row=2, col=1)

    fig.update_layout(
        height=700,
        title=f"{ticker} Stock Price, Signals & AI Insight",
        xaxis_title="Date",
        yaxis_title="Price",
        showlegend=True
    )

    fig.show()

def main():
    tickers = input("Enter stock tickers (comma-separated, e.g., AAPL, MSFT, GOOG): ")
    tickers = [t.strip().upper() for t in tickers.split(",")]

    for ticker in tickers:
        print(f"\nFetching data for {ticker}...")
        try:
            df = fetch_stock_data(ticker)
            df = generate_signals(df)
            latest_signal = df['Signal'].iloc[-1] if df['Signal'].iloc[-1] else "No clear signal"
            print(f"Latest signal for {ticker}: {latest_signal}")

            insight = get_ai_insight(ticker, latest_signal)
            print(f"AI insight for {ticker}: {insight}")

            plot_stock_with_insight(df, ticker, insight)

        except Exception as e:
            print(f"Error fetching data or generating insight for {ticker}: {e}")

if __name__ == "__main__":
    main()
